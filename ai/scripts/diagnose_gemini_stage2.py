"""Safely isolate Stage 1 versus Stage 2 Gemini failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

AI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AI_ROOT.parent
BACKEND_ROOT = REPOSITORY_ROOT / "back-end"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.api.config import load_settings  # noqa: E402
from ai.farm_plan import FarmPlanValidationError, validate_farm_plan  # noqa: E402
from ai.gemini_provider import GeminiProvider, ProviderError  # noqa: E402
from ai.stage1_analyzer import Stage1Analyzer, Stage1AnalysisError  # noqa: E402
from ai.stage2_analyzer import Stage2Analyzer, Stage2AnalysisError  # noqa: E402
from ai.stage2_prompt import build_stage2_prompt  # noqa: E402
from ai.demo_plan_adapter import adapt_demo_farm_plan  # noqa: E402


def load_object(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def provider_error(exc: ProviderError) -> dict[str, Any]:
    return {
        "success": False,
        "error_type": type(exc).__name__,
        "http_status": exc.status_code,
        "provider_status": exc.provider_status or None,
        "provider_error": exc.provider_message or str(exc),
    }


def main() -> int:
    settings = load_settings()
    farm = load_object(settings.farm_data_path)
    weather = load_object(settings.weather_fixture_path)
    provider = GeminiProvider(settings)
    stage1 = Stage1Analyzer(
        provider,
        schema_path=REPOSITORY_ROOT / "contracts" / "zone-report.schema.json",
        batch_size=settings.batch_size,
        demo_mode=settings.demo_mode,
    )
    stage2 = Stage2Analyzer(
        provider,
        schema_path=REPOSITORY_ROOT / "contracts" / "farm-plan.schema.json",
        demo_mode=settings.demo_mode,
    )

    result: dict[str, Any] = {
        "model": settings.gemini_model,
        "key_configured": bool(settings.gemini_api_key),
        "demo_mode": settings.demo_mode,
        "request_options": provider.request_summary(),
    }
    try:
        stage1_result = stage1.analyze(
            farm,
            weather,
            analysis_run_id="stage2_diagnostic",
            batch_size=settings.batch_size,
        )
    except ProviderError as exc:
        result["failed_stage"] = "stage1"
        result["stage1"] = provider_error(exc)
        print(json.dumps(result, indent=2))
        return 1
    except Stage1AnalysisError as exc:
        result["failed_stage"] = "stage1_validation_or_orchestration"
        result["stage1"] = {"success": False, "error_type": type(exc).__name__, "error": str(exc)}
        print(json.dumps(result, indent=2))
        return 1

    prompt = build_stage2_prompt(farm, weather, stage1_result)
    result["stage1"] = {
        "success": True,
        "batches": stage1_result.total_batches,
        "assessments": sum(len(batch.report.assessments) for batch in stage1_result.batches),
    }
    result["stage2"] = {
        "prompt_characters": len(prompt),
        "request_options": provider.request_summary(),
    }
    try:
        raw_plan = provider.generate_farm_plan(prompt)
        if settings.demo_mode:
            raw_plan = adapt_demo_farm_plan(raw_plan)
        plan = validate_farm_plan(
            raw_plan,
            stage1_result,
            schema_path=REPOSITORY_ROOT / "contracts" / "farm-plan.schema.json",
        )
        result["stage2"].update(
            {
                "success": True,
                "response_keys": sorted(plan.model_dump(mode="json")),
                "priority_count": len(plan.priorities),
            }
        )
    except ProviderError as exc:
        result["failed_stage"] = "stage2_provider"
        result["stage2"].update(provider_error(exc))
        print(json.dumps(result, indent=2))
        return 1
    except FarmPlanValidationError as exc:
        result["failed_stage"] = "stage2_validation"
        result["stage2"].update(
            {"success": False, "error_type": type(exc).__name__, "validation_error": str(exc)}
        )
        print(json.dumps(result, indent=2))
        return 1
    except Stage2AnalysisError as exc:
        result["failed_stage"] = "stage2_orchestration"
        result["stage2"].update(
            {"success": False, "error_type": type(exc).__name__, "error": str(exc)}
        )
        print(json.dumps(result, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
