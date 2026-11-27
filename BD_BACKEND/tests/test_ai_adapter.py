"""Tests for the provider-neutral AI adapter, using only the scripted FakeProvider (M3-A6).

Needed because the adapter's promises are what keep NL search safe: invalid JSON is a failure,
only transient errors are retried and only a bounded number of times, and logs never carry the
prompt or the answer. No database and no live provider call: the fake stands in for Gemini.
"""

import logging
from collections.abc import Callable

import pytest
from pydantic import BaseModel

from app.ai.adapter import (
    AiInvalidOutputError,
    AiUnavailableError,
    PromptRef,
    StructuredResult,
    build_provider,
    generate_structured,
)
from app.ai.fake import (
    FakeProvider,
    rate_limited_error,
    rejected_error,
    server_error,
    timeout_error,
)
from app.config import Settings

PROMPT = PromptRef("TEST_PROMPT", 1)


class Answer(BaseModel):
    """A tiny output schema for the tests."""

    value: int


def _call(
    provider: FakeProvider, *, max_retries: int = 2, sleeps: list[float] | None = None
) -> StructuredResult[Answer]:
    """Run generate_structured against the fake with no real waiting."""
    recorded = sleeps if sleeps is not None else []
    return generate_structured(
        provider=provider,
        task="test",
        prompt=PROMPT,
        model="test-model",
        system_prompt="system",
        user_content="SECRET-SENTENCE",
        response_schema={"type": "object"},
        output_model=Answer,
        timeout_seconds=5,
        max_retries=max_retries,
        sleep=recorded.append,
    )


def test_valid_answer_is_returned_validated() -> None:
    """A valid JSON answer comes back as the Pydantic model, with the model name and prompt."""
    provider = FakeProvider([{"value": 7}])

    result = _call(provider)

    assert result.output == Answer(value=7)
    assert result.model == "test-model"
    assert result.prompt == PROMPT
    assert len(provider.calls) == 1


@pytest.mark.parametrize("bad_text", ["not json at all", '{"value": "seven"}', "[1, 2]", ""])
def test_invalid_json_or_schema_is_a_failure_and_not_retried(bad_text: str) -> None:
    """Text that is not valid JSON for the schema raises AiInvalidOutputError after one call."""
    provider = FakeProvider([bad_text])

    with pytest.raises(AiInvalidOutputError):
        _call(provider)

    assert len(provider.calls) == 1


@pytest.mark.parametrize("error", [timeout_error, rate_limited_error, server_error])
def test_transient_failure_is_retried_then_succeeds(error: Callable[[], Exception]) -> None:
    """A timeout, 429 or 5xx is retried; a later good answer is returned, with backoff waits."""
    provider = FakeProvider([error(), {"value": 1}])
    sleeps: list[float] = []

    result = _call(provider, sleeps=sleeps)

    assert result.output.value == 1
    assert len(provider.calls) == 2
    assert len(sleeps) == 1 and sleeps[0] > 0


def test_retries_are_bounded() -> None:
    """With max_retries=2 a provider that always times out is called 3 times, then unavailable."""
    provider = FakeProvider([timeout_error()])
    sleeps: list[float] = []

    with pytest.raises(AiUnavailableError):
        _call(provider, max_retries=2, sleeps=sleeps)

    assert len(provider.calls) == 3
    assert len(sleeps) == 2
    # Exponential: the second wait is longer than the largest the first could be.
    assert sleeps[1] > 0.5 * 2 * 0.5 - 1e-9


def test_zero_retries_means_one_attempt() -> None:
    """max_retries=0 makes exactly one attempt before giving up."""
    provider = FakeProvider([server_error()])

    with pytest.raises(AiUnavailableError):
        _call(provider, max_retries=0)

    assert len(provider.calls) == 1


def test_permanent_failure_is_not_retried() -> None:
    """A rejected request (for example a bad key) is unavailable at once, with no retry."""
    provider = FakeProvider([rejected_error()])
    sleeps: list[float] = []

    with pytest.raises(AiUnavailableError):
        _call(provider, sleeps=sleeps)

    assert len(provider.calls) == 1
    assert sleeps == []


def test_log_has_facts_but_never_the_prompt_or_answer(caplog: pytest.LogCaptureFixture) -> None:
    """The log line names prompt ID, version, model and tokens, and holds none of the text."""
    provider = FakeProvider([{"value": 3}])

    with caplog.at_level(logging.INFO, logger="app.ai"):
        _call(provider)

    record = next(r for r in caplog.records if r.getMessage() == "ai_call")
    assert record.prompt_id == "TEST_PROMPT"
    assert record.prompt_version == 1
    assert record.model == "test-model"
    assert record.input_tokens == 10
    assert "SECRET-SENTENCE" not in caplog.text
    assert '"value"' not in caplog.text


def test_failure_log_holds_only_the_error_class(caplog: pytest.LogCaptureFixture) -> None:
    """A bad answer is logged by error class only, so an echoed sentence cannot leak."""
    provider = FakeProvider(["SECRET-SENTENCE is not json"])

    with caplog.at_level(logging.INFO, logger="app.ai"), pytest.raises(AiInvalidOutputError):
        _call(provider)

    assert "SECRET-SENTENCE" not in caplog.text
    assert any(getattr(r, "error_class", None) == "JSONDecodeError" for r in caplog.records)


@pytest.mark.parametrize("key", [None, ""])
def test_missing_key_means_ai_unavailable(key: str | None) -> None:
    """No GEMINI_API_KEY: build_provider raises AiUnavailableError, not a startup failure."""
    settings = Settings(database_url="postgresql+psycopg://x:y@localhost/z", gemini_api_key=key)

    with pytest.raises(AiUnavailableError):
        build_provider(settings)
