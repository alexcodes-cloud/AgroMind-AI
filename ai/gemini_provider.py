"""Official Google Gen AI SDK adapter for the two Gemini stages."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.api.config import Settings
from ai.farm_plan import FarmPlan
from ai.zone_report import ZoneReport


LOGGER = logging.getLogger("agromind.gemini")
MAX_TRANSIENT_RETRIES = 2
TRANSIENT_RETRY_BASE_SECONDS = 0.5


class ProviderError(RuntimeError):
    """Base class for safe provider failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_status: str = "",
        provider_message: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.provider_status = provider_status
        self.provider_message = provider_message


class ProviderConfigurationError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderUnsupportedRequestError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderNetworkError(ProviderError):
    pass


class ProviderUpstreamError(ProviderError):
    pass


class ProviderMalformedResponseError(ProviderError):
    pass


def _error_metadata(exc: Exception) -> tuple[int | None, str, str]:
    raw_code = getattr(exc, "status_code", None)
    if raw_code is None:
        raw_code = getattr(exc, "code", None)
    try:
        status_code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        status_code = None
    provider_status = str(getattr(exc, "status", None) or "").upper()
    provider_message = str(getattr(exc, "message", None) or str(exc))
    return status_code, provider_status, provider_message


def _classify_provider_exception(exc: Exception) -> ProviderError:
    status_code, provider_status, provider_message = _error_metadata(exc)
    message = provider_message.lower()
    metadata = {
        "status_code": status_code,
        "provider_status": provider_status,
        "provider_message": provider_message,
    }

    # Windows socket failures can contain the word "forbidden" even though no
    # HTTP response was received. Check transport failures before auth terms.
    if status_code in (408, 504) or provider_status == "DEADLINE_EXCEEDED" or isinstance(exc, TimeoutError) or any(
        term in message
        for term in ("timeout", "timed out", "deadline exceeded")
    ):
        return ProviderTimeoutError("Gemini request timed out", **metadata)
    if isinstance(exc, (ConnectionError, OSError)) or any(
        term in message
        for term in (
            "connection",
            "network",
            "dns",
            "socket",
            "access permissions",
            "winerror 10013",
            "temporarily unavailable",
        )
    ):
        return ProviderNetworkError("Gemini network request failed", **metadata)

    if status_code in (401, 403) or provider_status in {
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
    } or any(term in message for term in ("unauthorized", "api key", "authentication")):
        return ProviderAuthenticationError("Gemini authentication failed", **metadata)
    if status_code == 429 or provider_status in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"} or any(
        term in message for term in ("rate limit", "resource exhausted", "quota")
    ):
        return ProviderRateLimitError("Gemini rate limit or quota reached", **metadata)
    if (
        status_code in (400, 404)
        or provider_status in {"INVALID_ARGUMENT", "NOT_FOUND", "FAILED_PRECONDITION"}
        or any(
            term in message
            for term in (
                "model not found",
                "model is not available",
                "model is unavailable",
                "unsupported model",
                "not supported",
                "invalid argument",
            )
        )
    ):
        return ProviderUnsupportedRequestError(
            "Gemini rejected the model or request", **metadata
        )
    if status_code is not None and 500 <= status_code < 600 or provider_status in {
        "INTERNAL",
        "UNAVAILABLE",
        "UNKNOWN",
    }:
        return ProviderUpstreamError("Gemini upstream service failed", **metadata)
    return ProviderError("Gemini provider request failed", **metadata)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object, tolerating harmless prose or Markdown wrappers."""
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    # Some text-only models wrap otherwise valid JSON in an explanation or a
    # Markdown fence. Extract balanced object candidates; schema and evidence
    # validation still happens later in Stage1Analyzer.
    for start, character in enumerate(stripped):
        if character != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(stripped)):
            current = stripped[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    try:
                        candidate = json.loads(stripped[start : end + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(candidate, dict):
                        return candidate
                    break
    return None


def _response_text(response: Any) -> str | None:
    """Read text from the SDK property or from candidate content parts."""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        parts_text = [
            part_text
            for part in parts
            if isinstance(part_text := getattr(part, "text", None), str)
            and part_text.strip()
        ]
        if parts_text:
            return "".join(parts_text)
    return None


class GeminiProvider:
    """Small synchronous adapter that keeps SDK details out of the pipeline."""

    def __init__(self, settings: Settings, *, client: Any | None = None):
        self.settings = settings.validate()
        if not self.settings.gemini_api_key:
            if not self.settings.demo_fallback:
                raise ProviderConfigurationError("GEMINI_API_KEY is not configured")
            # The explicit demo fallback handles this provider error locally.
            # Keeping the provider object constructible lets the API use the
            # same orchestration path without ever inventing a Gemini result.
            self.client = None
        else:
            self.client = client or self._create_client()

    def _create_client(self) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderConfigurationError("google-genai is not installed") from exc

        try:
            http_options = types.HttpOptions(
                timeout=int(self.settings.gemini_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            return genai.Client(api_key=self.settings.gemini_api_key, http_options=http_options)
        except Exception as exc:
            raise ProviderConfigurationError("Gemini client could not be configured") from exc

    def _request_kwargs(
        self,
        prompt: str,
        *,
        response_schema: Any | None = None,
    ) -> dict[str, Any]:
        from google.genai import types

        request: dict[str, Any] = {
            "model": self.settings.gemini_model,
            "contents": prompt,
        }
        thinking_config = types.ThinkingConfig(
            thinking_level=self.settings.gemini_thinking_level
        )
        if self.settings.gemini_structured_output:
            request["config"] = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema or ZoneReport,
                max_output_tokens=self.settings.gemini_max_output_tokens,
                thinking_config=thinking_config,
            )
        else:
            # Keep Gemma in text mode by default, but cap generation so a
            # multi-zone report cannot spend the whole upstream deadline
            # producing unnecessary prose.
            from google.genai import types

            request["config"] = types.GenerateContentConfig(
                max_output_tokens=self.settings.gemini_max_output_tokens,
                thinking_config=thinking_config,
            )
        return request

    def request_summary(self) -> dict[str, Any]:
        """Return safe request metadata for diagnostics, never prompt/key data."""
        return {
            "model": self.settings.gemini_model,
            "timeout_seconds": self.settings.gemini_timeout_seconds,
            "structured_output": self.settings.gemini_structured_output,
            "max_output_tokens": self.settings.gemini_max_output_tokens,
            "thinking_level": self.settings.gemini_thinking_level,
            "demo_mode": self.settings.demo_mode,
            "demo_fallback": self.settings.demo_fallback,
            "config_fields": (
                [
                    "response_mime_type",
                    "response_schema",
                    "max_output_tokens",
                    "thinking_config",
                ]
                if self.settings.gemini_structured_output
                else ["max_output_tokens", "thinking_config"]
            ),
            "max_transient_retries": MAX_TRANSIENT_RETRIES,
        }

    def generate_content_response(
        self,
        prompt: str,
        *,
        response_schema: Any | None = None,
    ) -> Any:
        """Call Gemini with bounded retries for transient upstream 5xx errors."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderMalformedResponseError("Gemini prompt must not be empty")
        if self.client is None:
            raise ProviderConfigurationError("GEMINI_API_KEY is not configured")

        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                return self.client.models.generate_content(
                    **self._request_kwargs(prompt, response_schema=response_schema)
                )
            except ProviderError:
                raise
            except Exception as exc:
                classified = _classify_provider_exception(exc)
                is_retryable = isinstance(classified, ProviderUpstreamError) or (
                    isinstance(classified, ProviderTimeoutError)
                    and (
                        classified.status_code in (408, 504)
                        or classified.provider_status == "DEADLINE_EXCEEDED"
                    )
                )
                if not is_retryable or attempt >= MAX_TRANSIENT_RETRIES:
                    raise classified from exc
                delay = TRANSIENT_RETRY_BASE_SECONDS * (2**attempt)
                LOGGER.warning(
                    "Retrying Gemini upstream failure attempt=%s/%s delay_seconds=%s "
                    "status_code=%s provider_status=%s",
                    attempt + 1,
                    MAX_TRANSIENT_RETRIES,
                    delay,
                    classified.status_code,
                    classified.provider_status or "-",
                )
                time.sleep(delay)

        raise ProviderUpstreamError("Gemini upstream service failed")

    def generate_zone_report(self, prompt: str) -> dict[str, Any]:
        try:
            response = self.generate_content_response(prompt, response_schema=ZoneReport)
        except ProviderError:
            raise
        except Exception as exc:
            raise _classify_provider_exception(exc) from exc

        text = _response_text(response)
        if not isinstance(text, str) or not text.strip():
            raise ProviderMalformedResponseError("Gemini returned no text response")
        payload = _parse_json_object(text)
        if payload is None:
            raise ProviderMalformedResponseError(
                f"Gemini returned invalid JSON (response_characters={len(text)})"
            )
        return payload

    def generate_farm_plan(self, prompt: str) -> dict[str, Any]:
        """Generate one JSON farm plan while reusing Stage 1 safety behavior."""
        try:
            response = self.generate_content_response(prompt, response_schema=FarmPlan)
        except ProviderError:
            raise
        except Exception as exc:
            raise _classify_provider_exception(exc) from exc

        text = _response_text(response)
        if not isinstance(text, str) or not text.strip():
            raise ProviderMalformedResponseError("Gemini returned no text response")
        payload = _parse_json_object(text)
        if payload is None:
            raise ProviderMalformedResponseError(
                f"Gemini returned invalid JSON (response_characters={len(text)})"
            )
        return payload
