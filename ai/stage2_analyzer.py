"""Stage 2 orchestration for farm-wide action-plan synthesis."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ai.demo_plan_adapter import adapt_demo_farm_plan
from ai.farm_plan import FarmPlan, FarmPlanValidationError, validate_farm_plan
from ai.gemini_provider import ProviderError
from ai.local_demo_fallback import FALLBACK_LIMITATION, build_local_farm_plan
from ai.stage1_analyzer import Stage1RunResult
from ai.stage2_prompt import PromptSafetyError, build_stage2_prompt


MAX_VALIDATION_RETRIES = 2


class FarmPlanProvider(Protocol):
    def generate_farm_plan(self, prompt: str) -> dict[str, Any]: ...


class Stage2AnalysisError(RuntimeError):
    """Raised when Stage 2 cannot safely produce a validated plan."""


class Stage2Analyzer:
    def __init__(
        self,
        provider: FarmPlanProvider,
        *,
        schema_path: Path,
        demo_mode: bool = False,
        demo_fallback: bool = False,
    ):
        self.provider = provider
        self.schema_path = schema_path
        self.demo_mode = demo_mode
        self.demo_fallback = demo_fallback

    def synthesize(
        self,
        farm: dict[str, Any],
        weather: dict[str, Any] | None,
        stage1_result: Stage1RunResult,
    ) -> FarmPlan:
        if stage1_result.status != "completed":
            raise Stage2AnalysisError("Stage 2 requires completed Stage 1 reports")
        if stage1_result.farm_id != farm.get("farm_id"):
            raise Stage2AnalysisError("Stage 1 reports belong to a different farm")
        if self.demo_fallback:
            return build_local_farm_plan(stage1_result)

        validation_feedback: str | None = None
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            try:
                prompt = build_stage2_prompt(
                    farm,
                    weather,
                    stage1_result,
                    validation_feedback=validation_feedback,
                )
                raw_plan = self.provider.generate_farm_plan(prompt)
                if self.demo_mode:
                    raw_plan = adapt_demo_farm_plan(raw_plan)
                plan = validate_farm_plan(
                    raw_plan,
                    stage1_result,
                    schema_path=self.schema_path,
                )
                if stage1_result.fallback_used and FALLBACK_LIMITATION not in plan.limitations:
                    plan.limitations.append(FALLBACK_LIMITATION)
                return plan
            except FarmPlanValidationError as exc:
                if attempt >= MAX_VALIDATION_RETRIES:
                    if self.demo_fallback:
                        return build_local_farm_plan(stage1_result)
                    raise Stage2AnalysisError(
                        f"Stage 2 output rejected for {stage1_result.analysis_run_id}: {exc}"
                    ) from exc
                validation_feedback = str(exc)
            except ProviderError:
                if self.demo_fallback:
                    return build_local_farm_plan(stage1_result)
                raise
            except PromptSafetyError:
                raise
            except Exception as exc:
                raise Stage2AnalysisError("Stage 2 provider failed") from exc

        raise Stage2AnalysisError("Stage 2 did not produce a validated plan")
