"""Compact Gemini output and deterministic merging for Stage 1.

Gemini is useful for interpreting the signals, but it should not be asked to
recreate the complete traceability contract.  This module defines the small
response Gemini is allowed to produce and merges it into a report built from
the source records by the backend.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai.zone_report import ZoneReportValidationError


HealthStatus = Literal["normal", "investigation_needed", "insufficient_evidence"]
RiskLevel = Literal["low", "medium", "high", "unknown"]


class CompactZoneInsight(BaseModel):
    """The only per-zone interpretation Gemini needs to return."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    hydration_status: HealthStatus
    hydration_risk: RiskLevel
    fertilization_status: HealthStatus
    fertilization_risk: RiskLevel
    hydration_summary: str = Field(min_length=1, max_length=240)
    fertilization_summary: str = Field(min_length=1, max_length=240)


class CompactZoneInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insights: list[CompactZoneInsight]


def validate_compact_zone_insights(
    payload: Any,
    batch: dict[str, Any],
) -> CompactZoneInsights:
    """Validate compact model output and exact zone coverage."""
    if not isinstance(payload, dict):
        raise ZoneReportValidationError("Gemini insights must be a JSON object")
    try:
        result = CompactZoneInsights.model_validate(payload)
    except ValidationError as exc:
        raise ZoneReportValidationError("Gemini insights failed compact validation") from exc

    expected = [zone.get("zone_id") for zone in batch.get("zones", [])]
    actual = [item.zone_id for item in result.insights]
    if len(actual) != len(set(actual)):
        raise ZoneReportValidationError("Gemini insights contain duplicate zone_id values")
    if actual != expected and set(actual) != set(expected):
        raise ZoneReportValidationError("Gemini insights do not cover exactly the input zones")
    return result


def _action(domain: str, status: str) -> list[dict[str, Any]]:
    if status == "normal":
        return []
    if status == "insufficient_evidence":
        return [
            {
                "action": f"Review {domain} data before taking action.",
                "description": "Confirm the missing evidence with the farm operator.",
                "requires_human_approval": True,
            }
        ]
    action = "Review irrigation priority." if domain == "hydration" else "Review nutrient management."
    return [
        {
            "action": action,
            "description": "Review this finding with the farm operator before taking action.",
            "requires_human_approval": True,
        }
    ]


def merge_compact_zone_insights(
    deterministic_report: dict[str, Any],
    payload: Any,
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Apply only bounded Gemini fields to a deterministic full report.

    Evidence IDs, missing-information fields, and report envelope fields are
    never taken from Gemini.  They remain derived from the input batch.
    """
    insights = validate_compact_zone_insights(payload, batch)
    by_zone = {item.zone_id: item for item in insights.insights}
    report = {
        **deterministic_report,
        "assessments": [dict(item) for item in deterministic_report["assessments"]],
    }
    for assessment in report["assessments"]:
        insight = by_zone[assessment["zone_id"]]
        for domain, status, risk, summary in (
            ("hydration", insight.hydration_status, insight.hydration_risk, insight.hydration_summary),
            (
                "fertilization",
                insight.fertilization_status,
                insight.fertilization_risk,
                insight.fertilization_summary,
            ),
        ):
            current = dict(assessment[domain])
            current["status"] = status
            current["risk_level"] = risk
            current["finding"] = summary
            current["recommended_actions"] = _action(domain, status)
            assessment[domain] = current
    return report
