"""Safely compare Gemini responses for minimal and Stage 1 prompts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

AI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AI_ROOT.parent
BACKEND_ROOT = REPOSITORY_ROOT / "back-end"
sys.path.insert(0, str(BACKEND_ROOT))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.api.config import load_settings  # noqa: E402
from backend.services.batch_builder import build_stage1_batches  # noqa: E402
from ai.demo_zone_adapter import adapt_demo_zone_report  # noqa: E402
from ai.gemini_provider import (  # noqa: E402
    GeminiProvider,
    ProviderError,
    _parse_json_object,
    _response_text,
)
from ai.stage1_prompt import build_stage1_prompt  # noqa: E402
from ai.zone_report import ZoneReportValidationError, validate_zone_report  # noqa: E402


def _json_object(text: str | None) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        return isinstance(json.loads(text), dict)
    except json.JSONDecodeError:
        return False


def _response_shape(text: str | None) -> str:
    if not isinstance(text, str) or not text.strip():
        return "empty"
    stripped = text.strip()
    if _json_object(stripped):
        return "json_object"
    if stripped.startswith("```") and stripped.endswith("```"):
        return "markdown_code_fence"
    if "{" in stripped and "}" in stripped:
        return "text_with_object_candidate"
    return "plain_text"


def _response_metadata(response: Any) -> dict[str, Any]:
    candidates = getattr(response, "candidates", None) or []
    finish_reasons = [
        str(reason)
        for candidate in candidates
        if (reason := getattr(candidate, "finish_reason", None)) is not None
    ]
    part_count = sum(
        len(getattr(getattr(candidate, "content", None), "parts", None) or [])
        for candidate in candidates
    )
    return {
        "candidate_count": len(candidates),
        "part_count": part_count,
        "finish_reasons": finish_reasons,
    }


def _redact(value: object, api_key: str | None) -> str:
    text = str(value)
    return text.replace(api_key, "[REDACTED]") if api_key else text


def _run_case(
    provider: GeminiProvider,
    label: str,
    prompt: str,
    api_key: str | None,
    batch: dict[str, Any] | None = None,
    schema_path: Path | None = None,
    demo_mode: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "case": label,
        "prompt_characters": len(prompt),
        "request_options": provider.request_summary(),
    }
    try:
        response = provider.generate_content_response(prompt)
        text = _response_text(response)
        result.update(
            {
                "success": True,
                "http_status": None,
                "provider_status": None,
                "response_characters": len(text) if isinstance(text, str) else 0,
                "response_is_json_object": _json_object(text),
                "response_shape": _response_shape(text),
            }
        )
        result.update(_response_metadata(response))
        if batch is not None and schema_path is not None:
            payload = _parse_json_object(text or "")
            if demo_mode:
                payload = adapt_demo_zone_report(payload, batch)
            try:
                validate_zone_report(payload, batch, schema_path=schema_path)
            except ZoneReportValidationError as exc:
                result.update(
                    {
                        "validation_success": False,
                        "validation_error_type": type(exc).__name__,
                        "validation_error": str(exc),
                    }
                )
            else:
                result["validation_success"] = True
    except ProviderError as exc:
        result.update(
            {
                "success": False,
                "http_status": exc.status_code,
                "provider_status": exc.provider_status or None,
                "provider_error_type": type(exc).__name__,
                "provider_error": _redact(
                    exc.provider_message or str(exc), api_key
                ),
            }
        )
    except Exception as exc:  # Keep diagnostics useful without exposing prompt/key data.
        result.update(
            {
                "success": False,
                "http_status": None,
                "provider_status": None,
                "provider_error_type": type(exc).__name__,
                "provider_error": _redact(str(exc), api_key),
            }
        )
    return result


def main() -> int:
    settings = load_settings()
    if not settings.gemini_api_key:
        print(json.dumps({"error": "GEMINI_API_KEY is not configured"}, indent=2))
        return 1

    farm = json.loads(settings.farm_data_path.read_text(encoding="utf-8"))
    weather = json.loads(settings.weather_fixture_path.read_text(encoding="utf-8"))
    batches = build_stage1_batches(
        farm, weather, batch_size=settings.batch_size, analysis_run_id="diagnostic_run"
    )
    actual_prompt = build_stage1_prompt(batches[0])
    small_batch = dict(batches[0])
    small_batch["zones"] = batches[0]["zones"][:1]
    small_prompt = build_stage1_prompt(small_batch)

    provider = GeminiProvider(settings)
    cases = [
        ("minimal", "Reply with exactly: OK"),
        (
            "small_representative_stage1",
            "Return one JSON object with an assessments array for one agricultural zone. "
            "Use insufficient_evidence when the provided evidence is incomplete. "
            '{"schema_version":"1.0","assessments":[]}',
        ),
        ("actual_first_batch_stage1", actual_prompt),
    ]
    # Build the small prompt through the real prompt builder, while keeping the
    # representative case deliberately short for isolating request size effects.
    cases[1] = ("small_representative_stage1", small_prompt)
    schema_path = REPOSITORY_ROOT / "contracts" / "zone-report.schema.json"

    print(
        json.dumps(
            {
                "model": settings.gemini_model,
                "key_configured": True,
                "structured_output": settings.gemini_structured_output,
                "cases": [
                    _run_case(
                        provider,
                        label,
                        prompt,
                        settings.gemini_api_key,
                        batch=(small_batch if label == "small_representative_stage1" else batches[0])
                        if label != "minimal"
                        else None,
                        schema_path=schema_path,
                        demo_mode=settings.demo_mode,
                    )
                    for label, prompt in cases
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
