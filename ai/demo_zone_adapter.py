"""Conservative compatibility mapping for the hackathon demo mode."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


STATUS_ALIASES = {"optimal": "normal", "healthy": "normal", "stable": "normal", "watch": "investigation_needed", "warning": "investigation_needed"}
RISK_ALIASES = {"none": "low", "minimal": "low", "severe": "high"}
CONFIDENCE_ALIASES = {"medium": "moderate", "med": "moderate"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _record_ids(batch: dict[str, Any]) -> set[str]:
    return {
        record["record_id"]
        for zone in batch.get("zones", [])
        for collection in ("sensors", "drone_observations")
        for record in zone.get(collection, [])
        if isinstance(record, dict) and isinstance(record.get("record_id"), str)
    }


def _evidence(value: Any, allowed_ids: set[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            record_id = item.get("record_id")
            interpretation = item.get("interpretation")
            if isinstance(record_id, str) and record_id in allowed_ids and isinstance(interpretation, str):
                result.append({"record_id": record_id, "interpretation": interpretation})
        elif isinstance(item, str):
            matching = [record_id for record_id in allowed_ids if record_id in item]
            if len(matching) == 1:
                result.append({"record_id": matching[0], "interpretation": item})
    return result


def _actions(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            description = item.get("description") or item.get("action")
            if isinstance(description, str):
                result.append({
                    "action": str(item.get("action") or "review"),
                    "description": description,
                    "requires_human_approval": bool(item.get("requires_human_approval", True)),
                })
        elif isinstance(item, str):
            result.append({"action": "review", "description": item, "requires_human_approval": True})
    return result


def _domain(value: Any, allowed_ids: set[str]) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    status = str(source.get("status", "insufficient_evidence")).lower()
    risk_level = str(source.get("risk_level", source.get("risk", "unknown"))).lower()
    confidence = str(source.get("confidence", "low")).lower()
    finding = source.get("finding", "Insufficient structured detail for a confident finding.")
    return {
        "status": STATUS_ALIASES.get(status, status),
        "risk_level": RISK_ALIASES.get(risk_level, risk_level),
        "confidence": CONFIDENCE_ALIASES.get(confidence, confidence),
        "finding": finding if isinstance(finding, str) else str(finding),
        "evidence": _evidence(source.get("evidence", source.get("evidence_interpretations", [])), allowed_ids),
        "missing_information": [str(item) for item in _as_list(source.get("missing_information")) if item is not None],
        "recommended_actions": _actions(source.get("recommended_actions", source.get("actions", []))),
    }


def adapt_demo_zone_report(payload: Any, batch: dict[str, Any]) -> Any:
    """Normalize obvious free-form aliases, then let strict validation decide."""
    if not isinstance(payload, dict):
        return payload
    source = deepcopy(payload)
    assessments = source.get("assessments", source.get("zones"))
    if not isinstance(assessments, list):
        return payload

    expected_zone_ids = [zone.get("zone_id") for zone in batch.get("zones", [])]
    allowed_ids = _record_ids(batch)
    root_zone_id = source.get("zone_id")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(assessments):
        if not isinstance(item, dict):
            continue
        zone_id = item.get("zone_id") or item.get("zone")
        if not isinstance(zone_id, str):
            if len(assessments) == 1 and isinstance(root_zone_id, str):
                zone_id = root_zone_id
            elif index < len(expected_zone_ids):
                zone_id = expected_zone_ids[index]
        normalized.append({
            "zone_id": zone_id,
            "hydration": _domain(item.get("hydration", item.get("hydration_assessment")), allowed_ids),
            "fertilization": _domain(item.get("fertilization", item.get("fertilization_assessment")), allowed_ids),
        })

    return {
        "schema_version": source.get("schema_version", batch.get("schema_version", "1.0")),
        "farm_id": source.get("farm_id", batch.get("farm_id")),
        "batch_id": source.get("batch_id", batch.get("batch_id")),
        "assessments": normalized,
    }
