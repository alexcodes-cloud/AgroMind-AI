"""Explicit deterministic fallbacks for an offline hackathon demonstration.

These functions use the supplied farm records and preserve their IDs. They are
never enabled unless ``AGROMIND_DEMO_FALLBACK=true`` is set explicitly.
"""

from __future__ import annotations

from typing import Any

from ai.farm_plan import FarmPlan
from ai.zone_report import ZoneReport


FALLBACK_LIMITATION = (
    "Gemini was unavailable; this result uses the deterministic local demo "
    "fallback and is not an AI-generated recommendation."
)


def _records(zone: dict[str, Any], collection: str, fields: set[str] | None = None) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for record in zone.get(collection, []):
        if not isinstance(record, dict) or not isinstance(record.get("record_id"), str):
            continue
        if fields is None or record.get("field") in fields:
            values.append(record)
    return values


def _domain_assessment(
    *,
    status: str,
    risk_level: str,
    confidence: str,
    finding: str,
    evidence_records: list[dict[str, Any]],
    missing_information: list[str],
    action: str | None,
) -> dict[str, Any]:
    actions = []
    if action:
        actions.append(
            {
                "action": action,
                "description": "Review this result with the farm operator before taking action.",
                "requires_human_approval": True,
            }
        )
    return {
        "status": status,
        "risk_level": risk_level,
        "confidence": confidence,
        "finding": finding,
        "evidence": [
            {
                "record_id": record["record_id"],
                "interpretation": "Record supplied in the synthetic farm input.",
            }
            for record in evidence_records
        ],
        "missing_information": missing_information,
        "recommended_actions": actions,
    }


def build_local_zone_report(batch: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative contract-valid report from input records only."""
    assessments = []
    for zone in batch["zones"]:
        moisture_records = _records(zone, "sensors", {"soil_moisture"})
        nutrient_records = _records(zone, "sensors", {"nitrogen", "phosphorus", "potassium"})
        drone_records = _records(zone, "drone_observations")
        moisture = next(
            (record for record in reversed(moisture_records) if record.get("quality") == "valid"),
            moisture_records[-1] if moisture_records else None,
        )

        if moisture is None or not isinstance(moisture.get("value"), (int, float)):
            hydration = _domain_assessment(
                status="insufficient_evidence",
                risk_level="unknown",
                confidence="low",
                finding="No usable soil-moisture reading was supplied for this zone.",
                evidence_records=drone_records[:1],
                missing_information=["A valid soil-moisture measurement is needed."],
                action="Review moisture data before irrigation decisions.",
            )
        else:
            value = float(moisture["value"])
            if value < 25:
                status, risk, action = "investigation_needed", "high", "Review irrigation priority."
            elif value < 35:
                status, risk, action = "investigation_needed", "medium", "Review irrigation timing."
            else:
                status, risk, action = "normal", "low", None
            hydration = _domain_assessment(
                status=status,
                risk_level=risk,
                confidence="moderate",
                finding=f"The supplied soil-moisture reading is {value:g} {moisture.get('unit', '')}.".strip(),
                evidence_records=[moisture],
                missing_information=[],
                action=action,
            )

        nutrient_valid = [record for record in nutrient_records if record.get("quality") == "valid"]
        if nutrient_valid:
            fertilization = _domain_assessment(
                status="normal",
                risk_level="low",
                confidence="moderate",
                finding="The supplied nutrient readings do not establish an immediate deficiency.",
                evidence_records=nutrient_valid,
                missing_information=[],
                action=None,
            )
        else:
            fertilization = _domain_assessment(
                status="insufficient_evidence",
                risk_level="unknown",
                confidence="low",
                finding="Usable nutrient readings were not supplied for this zone.",
                evidence_records=drone_records[:1],
                missing_information=["Valid nutrient measurements are needed before fertilizer decisions."],
                action="Review nutrient data before fertilization decisions.",
            )

        assessments.append(
            {
                "zone_id": zone["zone_id"],
                "hydration": hydration,
                "fertilization": fertilization,
            }
        )
    return {
        "schema_version": "1.0",
        "farm_id": batch["farm_id"],
        "batch_id": batch["batch_id"],
        "assessments": assessments,
    }


def build_local_farm_plan(stage1_result: Any) -> FarmPlan:
    """Synthesize validated reports locally, preserving only real evidence IDs."""
    priorities: list[dict[str, Any]] = []
    for batch in stage1_result.batches:
        for assessment in batch.report.assessments:
            for domain_name, domain in (
                ("hydration", assessment.hydration),
                ("fertilization", assessment.fertilization),
            ):
                if domain.status == "normal":
                    continue
                refs = [item.record_id for item in domain.evidence]
                if not refs:
                    continue
                priorities.append(
                    {
                        "priority": len(priorities) + 1,
                        "zone_id": assessment.zone_id,
                        "domain": domain_name,
                        "action": (
                            domain.recommended_actions[0].action
                            if domain.recommended_actions
                            else f"Review {domain_name} conditions."
                        ),
                        "reason": domain.finding,
                        "evidence_refs": refs,
                        "uncertainty": "; ".join(domain.missing_information)
                        or "Confirm the finding with the farm operator before acting.",
                        "requires_human_approval": True,
                    }
                )
    return FarmPlan(
        schema_version="1.0",
        farm_id=stage1_result.farm_id,
        analysis_run_id=stage1_result.analysis_run_id,
        summary=(
            "Local demo analysis identified items for human review."
            if priorities
            else "Local demo analysis found no immediate items requiring review."
        ),
        priorities=priorities,
        farm_wide_considerations=["Review all recommendations with the farm operator."],
        unresolved_questions=[],
        limitations=[FALLBACK_LIMITATION],
    )
