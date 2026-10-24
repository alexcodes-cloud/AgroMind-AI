"""Validation for the Stage 2 farm-wide action plan contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from ai.stage1_analyzer import Stage1RunResult


class FarmPriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int = Field(ge=1)
    zone_id: str = Field(min_length=1)
    domain: Literal["hydration", "fertilization"]
    action: str
    reason: str
    evidence_refs: list[str] = Field(min_length=1)
    uncertainty: str
    requires_human_approval: bool


class FarmPlan(BaseModel):
    """The exact response shape defined by farm-plan.schema.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    farm_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    summary: str
    priorities: list[FarmPriority]
    farm_wide_considerations: list[str]
    unresolved_questions: list[str]
    limitations: list[str]


class FarmPlanValidationError(ValueError):
    """Raised when a Stage 2 result is invalid or not traceable to Stage 1."""


FORBIDDEN_KEYS = {
    "evaluation_labels",
    "scenario_label",
    "expected_hydration",
    "expected_fertilization",
    "evaluation_note",
}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in FORBIDDEN_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FarmPlanValidationError("farm-plan schema is unavailable") from exc
    validator = Draft202012Validator(schema)
    return [
        f"{'.'.join(str(item) for item in error.path) or '$'}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


def validate_farm_plan(
    payload: Any,
    stage1_result: "Stage1RunResult",
    *,
    schema_path: Path,
) -> FarmPlan:
    """Validate structure and ensure every plan reference comes from Stage 1."""
    if not isinstance(payload, dict):
        raise FarmPlanValidationError("model response must be a JSON object")
    if _contains_forbidden_key(payload):
        raise FarmPlanValidationError("model response contains hidden evaluation fields")

    schema_errors = _schema_errors(payload, schema_path)
    if schema_errors:
        raise FarmPlanValidationError(
            f"model response failed the farm-plan schema: {schema_errors[0]}"
        )

    try:
        plan = FarmPlan.model_validate(payload)
    except ValidationError as exc:
        raise FarmPlanValidationError("model response failed Pydantic validation") from exc

    if plan.farm_id != stage1_result.farm_id:
        raise FarmPlanValidationError("model response has the wrong farm_id")
    if plan.analysis_run_id != stage1_result.analysis_run_id:
        raise FarmPlanValidationError("model response has the wrong analysis_run_id")

    zone_ids = {
        assessment.zone_id
        for batch in stage1_result.batches
        for assessment in batch.report.assessments
    }
    evidence_ids = {
        evidence.record_id
        for batch in stage1_result.batches
        for assessment in batch.report.assessments
        for domain in (assessment.hydration, assessment.fertilization)
        for evidence in domain.evidence
    }
    for index, priority in enumerate(plan.priorities):
        if priority.zone_id not in zone_ids:
            raise FarmPlanValidationError(
                f"priorities[{index}].zone_id is not present in Stage 1 reports"
            )
        unknown_refs = [ref for ref in priority.evidence_refs if ref not in evidence_ids]
        if unknown_refs:
            raise FarmPlanValidationError(
                f"priorities[{index}] contains evidence_refs not present in Stage 1 reports"
            )
    return plan
