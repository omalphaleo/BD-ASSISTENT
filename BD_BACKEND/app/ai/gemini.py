"""Gemini implementation of the AI provider interface (M3-A6, D-056, D-060).

Needed because this is the one place that imports the google-genai SDK (ai-adapter rule); the
rest of the app only sees AiProvider. It asks for JSON that follows the supplied schema and
maps SDK errors onto the adapter's two kinds: retryable (timeout, 429, 5xx) and permanent
(rejected key or request). It is not exercised by automated tests, which use FakeProvider; it
is checked by hand with a free-tier key on test data (D-062).
"""

from typing import Any

from google import genai
from google.genai import errors, types

from app.ai.adapter import PermanentProviderError, ProviderResult, TransientProviderError

HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_FLOOR = 500
HTTP_REQUEST_TIMEOUT = 408
MS_PER_SECOND = 1000


class GeminiProvider:
    """Calls Gemini's generate-content API with structured JSON output."""

    def __init__(self, api_key: str) -> None:
        """Keep the key for the client built per call (the timeout differs per call)."""
        self._api_key = api_key

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        response_schema: dict[str, Any],
        timeout_seconds: float,
    ) -> ProviderResult:
        """Ask the model for JSON matching `response_schema` and return the answer text.

        Raises:
            TransientProviderError: timeout, HTTP 408, 429 or 5xx.
            PermanentProviderError: any other API error (for example an invalid key).
        """
        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * MS_PER_SECOND)),
        )
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_json_schema=response_schema,
            # Interpreting a sentence should be repeatable, not creative.
            temperature=0,
        )
        try:
            response = client.models.generate_content(
                model=model, contents=user_content, config=config
            )
        except errors.APIError as error:
            code = error.code
            if code in (HTTP_REQUEST_TIMEOUT, HTTP_TOO_MANY_REQUESTS) or (
                isinstance(code, int) and code >= HTTP_SERVER_ERROR_FLOOR
            ):
                raise TransientProviderError(f"gemini http {code}") from error
            raise PermanentProviderError(f"gemini http {code}") from error
        except Exception as error:  # noqa: BLE001 - the SDK raises transport errors of many types
            # Network and timeout failures come from the HTTP layer, not from APIError.
            raise TransientProviderError(type(error).__name__) from error

        usage = response.usage_metadata
        return ProviderResult(
            text=response.text or "",
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )
