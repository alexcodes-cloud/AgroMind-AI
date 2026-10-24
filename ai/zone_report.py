"""Pydantic and semantic validation for Stage 1 zone reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1)
    interpretation: str


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    description: str
    requires_human_approval: bool


class DomainAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["normal", "investigation_needed", "insufficient_evidence"]
    risk_level: Literal["low", "medium", "high", "unknown"]
    confidence: Literal["low", "moderate", "high"]
    finding: str
    evidence: list[Evidence]
    missing_information: list[str]
    recommended_actions: list[RecommendedAction]


class ZoneAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    hydration: DomainAssessment
    fertilization: DomainAssessment


class ZoneReport(BaseModel):
    """The exact response shape defined by zone-report.schema.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    farm_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    assessments: list[ZoneAssessment]


class ZoneReportValidationError(ValueError):
    """Raised when a model report is invalid or not traceable to its batch."""


FORBIDDEN_KEYS = {
    "evaluation_labels",
    "scenario_label",
    "expected_hydration",
    "expected_fertilization",
    "evaluation_note",
}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in FORBIDDEN_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ZoneReportValidationError("zone-report schema is unavailable") from exc
    validator = Draft202012Validator(schema)
    return [
        f"{'.'.join(str(item) for item in error.path) or '$'}: {error.message}"
        for error in validator.iter_errors(payload)
    ]


def _batch_record_ids(batch: dict[str, Any]) -> dict[str, set[str]]:
    records_by_zone: dict[str, set[str]] = {}
    for zone in batch.get("zones", []):
        zone_id = zone.get("zone_id")
        records: set[str] = set()
        for collection_name in ("sensors", "drone_observations"):
            for record in zone.get(collection_name, []):
                if isinstance(record, dict) and isinstance(record.get("record_id"), str):
                    records.add(record["record_id"])
        if isinstance(zone_id, str):
            records_by_zone[zone_id] = records
    return records_by_zone


def validate_zone_report(
    payload: Any,
    batch: dict[str, Any],
    *,
    schema_path: Path,
) -> ZoneReport:
    """Validate structure, exact zone coverage, and evidence provenance."""
    if not isinstance(payload, dict):
        raise ZoneReportValidationError("model response must be a JSON object")
    if _contains_forbidden_key(payload):
        raise ZoneReportValidationError("model response contains hidden evaluation fields")

    schema_errors = _schema_errors(payload, schema_path)
    if schema_errors:
        raise ZoneReportValidationError(
            f"model response failed the zone-report schema: {schema_errors[0]}"
        )

    try:
        report = ZoneReport.model_validate(payload)
    except ValidationError as exc:
        raise ZoneReportValidationError("model response failed Pydantic validation") from exc

    expected_farm_id = batch.get("farm_id")
    expected_batch_id = batch.get("batch_id")
    if report.farm_id != expected_farm_id:
        raise ZoneReportValidationError("model response has the wrong farm_id")
    if report.batch_id != expected_batch_id:
        raise ZoneReportValidationError("model response has the wrong batch_id")

    expected_zone_ids = [zone.get("zone_id") for zone in batch.get("zones", [])]
    actual_zone_ids = [assessment.zone_id for assessment in report.assessments]
    if len(actual_zone_ids) != len(set(actual_zone_ids)):
        raise ZoneReportValidationError("model response contains duplicate zone_id values")
    if set(actual_zone_ids) != set(expected_zone_ids) or len(actual_zone_ids) != len(expected_zone_ids):
        raise ZoneReportValidationError("model response does not cover exactly the input zones")

    records_by_zone = _batch_record_ids(batch)
    for assessment in report.assessments:
        allowed_record_ids = records_by_zone.get(assessment.zone_id, set())
        for domain in (assessment.hydration, assessment.fertilization):
            for evidence in domain.evidence:
                if evidence.record_id not in allowed_record_ids:
                    raise ZoneReportValidationError(
                        f"evidence record_id is not present in zone {assessment.zone_id}"
                    )
    return report
