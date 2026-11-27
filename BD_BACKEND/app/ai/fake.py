"""A scripted AI provider for tests (M3-A6).

Needed because tests must never call Gemini (CLAUDE.md). FakeProvider plays back a list of
canned outcomes, one per call: a JSON answer, or an error to raise (timeout, 429, 5xx, bad
JSON). It also records what it was asked, so tests can prove no contact detail was sent and
that the sentence travelled as data. Lives in app/ai/ (not tests/) so the API tests can plug it
in through the same dependency the real provider uses.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.adapter import (
    PermanentProviderError,
    ProviderResult,
    TransientProviderError,
)

# One scripted outcome: a dict (sent as JSON), a raw string (sent as is, to test bad JSON) or an
# exception to raise.
Outcome = dict[str, Any] | str | Exception


@dataclass
class FakeCall:
    """What one call asked for, kept so tests can inspect it."""

    model: str
    system_prompt: str
    user_content: str
    response_schema: dict[str, Any]
    timeout_seconds: float


@dataclass
class FakeProvider:
    """Plays back scripted outcomes in order; the last one repeats when the script runs out."""

    outcomes: list[Outcome]
    calls: list[FakeCall] = field(default_factory=list)

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        response_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResult:
        """Record the call, then return or raise the next scripted outcome."""
        self.calls.append(
            FakeCall(model, system_prompt, user_content, response_schema, timeout_seconds)
        )
        index = min(len(self.calls), len(self.outcomes)) - 1
        outcome = self.outcomes[index]
        if isinstance(outcome, Exception):
            raise outcome
        text = outcome if isinstance(outcome, str) else json.dumps(outcome)
        return ProviderResult(text=text, input_tokens=10, output_tokens=5)


def timeout_error() -> TransientProviderError:
    """A scripted timeout."""
    return TransientProviderError("timeout")


def rate_limited_error() -> TransientProviderError:
    """A scripted HTTP 429."""
    return TransientProviderError("429")


def server_error() -> TransientProviderError:
    """A scripted HTTP 5xx."""
    return TransientProviderError("503")


def rejected_error() -> PermanentProviderError:
    """A scripted non-retryable failure (for example a bad key)."""
    return PermanentProviderError("rejected")
