"""Provider-neutral AI adapter: one function that returns schema-validated JSON (M3-A6, D-060).

Needed so no other module talks to a model provider (ai-adapter rule). Services call
generate_structured() with a prompt ID and version from PROMPT.md and get back a validated
Pydantic object, or one of two errors: AiUnavailableError (provider down, slow, rate limited or
not configured) and AiInvalidOutputError (the answer was not valid JSON for the schema, which is
a failure and never text to use). The adapter retries only transient failures, a bounded number
of times with exponential backoff and jitter (plan section 9), and logs prompt ID, version, model,
latency and token counts, never the prompt or the answer, because those can hold lead data.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger("app.ai")

# First retry waits about this long; later retries double it. Jitter scales each wait by 0.5-1.5
# so several callers do not retry in step.
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_FACTOR = 2
JITTER_LOW = 0.5
JITTER_SPAN = 1.0


class AiError(Exception):
    """Base class of every failure the adapter reports to its callers."""


class AiUnavailableError(AiError):
    """The provider could not answer: not configured, timed out, rate limited or down."""


class AiInvalidOutputError(AiError):
    """The provider answered, but not with JSON that matches the expected schema."""


class TransientProviderError(Exception):
    """Raised by a provider for a failure worth retrying (timeout, 429, 5xx)."""


class PermanentProviderError(Exception):
    """Raised by a provider for a failure retrying cannot fix (bad key, rejected request)."""


@dataclass(frozen=True)
class PromptRef:
    """The prompt a call uses: its ID and version in PROMPT.md. Every call must name one."""

    id: str
    version: int


@dataclass(frozen=True)
class ProviderResult:
    """What a provider returns: the answer text and the token counts it reported."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class StructuredResult[OutputT: BaseModel]:
    """A validated answer plus the facts worth showing or auditing about the call."""

    output: OutputT
    model: str
    prompt: PromptRef


class AiProvider(Protocol):
    """What a model provider must offer. Gemini and the test fake implement it."""

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        response_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResult:
        """Return the model's JSON answer text.

        Raises:
            TransientProviderError: timeout, rate limit or server error (the adapter retries).
            PermanentProviderError: any failure that retrying cannot fix.
        """
        ...


def _backoff_seconds(retry_number: int) -> float:
    """Wait before retry number `retry_number` (0-based): exponential, with jitter."""
    base = BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR**retry_number)
    return base * (JITTER_LOW + random.random() * JITTER_SPAN)  # noqa: S311 - not security related


def build_provider(settings: Settings) -> AiProvider:
    """Return the configured provider (Gemini).

    Raises:
        AiUnavailableError: no GEMINI_API_KEY is set, so AI features are off.
    """
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise AiUnavailableError("GEMINI_API_KEY is not set")
    # Imported here so the SDK loads only when AI is really used, and only app/ai/gemini.py
    # ever imports it.
    from app.ai.gemini import GeminiProvider

    return GeminiProvider(api_key=settings.gemini_api_key.get_secret_value())


def generate_structured[OutputT: BaseModel](
    *,
    provider: AiProvider,
    task: str,
    prompt: PromptRef,
    model: str,
    system_prompt: str,
    user_content: str,
    response_schema: dict[str, Any],
    output_model: type[OutputT],
    timeout_seconds: float,
    max_retries: int,
    sleep: Callable[[float], None] = time.sleep,
) -> StructuredResult[OutputT]:
    """Call the provider and return its answer validated against `output_model`.

    Args:
        provider: the model provider to call.
        task: short task name for the logs, for example "nl_search".
        prompt: the PROMPT.md ID and version this call uses.
        model: provider model name (configuration, not code).
        system_prompt: fixed instructions; never contains lead data.
        user_content: the allow-listed payload as text.
        response_schema: JSON schema the provider is asked to follow.
        output_model: Pydantic model the answer must validate against.
        timeout_seconds: limit for one attempt.
        max_retries: extra attempts after the first for transient failures only.
        sleep: waiting function; tests pass a no-op so they do not wait.

    Raises:
        AiUnavailableError: every attempt failed with a transient or permanent provider error.
        AiInvalidOutputError: the answer was not valid JSON for `output_model`. Not retried:
            asking again is a new cost and the user can simply try again.
    """
    attempts = 0
    started = time.perf_counter()
    while True:
        attempts += 1
        try:
            result = provider.generate(
                model=model,
                system_prompt=system_prompt,
                user_content=user_content,
                response_schema=response_schema,
                timeout_seconds=timeout_seconds,
            )
            break
        except TransientProviderError as error:
            if attempts > max_retries:
                _log(task, prompt, model, started, attempts, error_class=type(error).__name__)
                raise AiUnavailableError("the AI provider did not answer in time") from error
            sleep(_backoff_seconds(attempts - 1))
        except PermanentProviderError as error:
            _log(task, prompt, model, started, attempts, error_class=type(error).__name__)
            raise AiUnavailableError("the AI provider rejected the request") from error

    try:
        output = output_model.model_validate(json.loads(result.text))
    except (json.JSONDecodeError, ValidationError) as error:
        # Only the error class is logged: the text of the answer may echo the sentence typed.
        _log(task, prompt, model, started, attempts, error_class=type(error).__name__)
        raise AiInvalidOutputError("the AI answer did not match the expected format") from error

    _log(
        task,
        prompt,
        model,
        started,
        attempts,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    return StructuredResult(output=output, model=model, prompt=prompt)


def _log(
    task: str,
    prompt: PromptRef,
    model: str,
    started: float,
    attempts: int,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_class: str | None = None,
) -> None:
    """Write one structured log line about a call: facts only, never the prompt or the answer."""
    logger.info(
        "ai_call",
        extra={
            "task": task,
            "prompt_id": prompt.id,
            "prompt_version": prompt.version,
            "model": model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "attempts": attempts,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error_class": error_class,
        },
    )
