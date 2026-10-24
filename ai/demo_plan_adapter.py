"""Conservative opt-in compatibility adapter for free-form demo output."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _domain(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(term in text for term in ("fertil", "nutrient", "nitrogen", "phosphorus", "potassium")):
        return "fertilization"
    return "hydration"


def _priority(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    text = str(value or "").strip().lower()
    return {"urgent": 1, "critical": 1, "high": 1, "medium": 2, "moderate": 2, "low": 3}.get(text, 1)


def _evidence_refs(value: Any) -> list[str]:
    refs: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str) and item:
            refs.append(item)
        elif isinstance(item, dict):
            record_id = item.get("record_id") or item.get("evidence_ref")
            if isinstance(record_id, str) and record_id:
                refs.append(record_id)
    return refs


def adapt_demo_farm_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Map common Gemma aliases without inventing evidence or decisions."""
    result = deepcopy(payload)
    if not isinstance(result, dict):
        return result

    if "priorities" not in result:
        for alias in ("actions", "recommendations", "farm_actions"):
            if isinstance(result.get(alias), list):
                result["priorities"] = result[alias]
                break
    priorities = []
    for item in _as_list(result.get("priorities")):
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "zone_id" not in normalized and isinstance(normalized.get("zone_ids"), list):
            ids = normalized["zone_ids"]
            if len(ids) == 1 and isinstance(ids[0], str):
                normalized["zone_id"] = ids[0]
        if "domain" not in normalized:
            normalized["domain"] = _domain(normalized.get("category") or normalized.get("type"))
        normalized["priority"] = _priority(normalized.get("priority") or normalized.get("urgency"))
        if "evidence_refs" not in normalized:
            normalized["evidence_refs"] = _evidence_refs(
                normalized.get("evidence") or normalized.get("evidence_ids")
            )
        if "reason" not in normalized:
            normalized["reason"] = str(normalized.get("rationale") or normalized.get("finding") or "")
        if "action" not in normalized:
            normalized["action"] = str(normalized.get("recommendation") or normalized.get("description") or "")
        if "uncertainty" not in normalized:
            normalized["uncertainty"] = "Review the cited evidence before acting."
        if "requires_human_approval" not in normalized:
            normalized["requires_human_approval"] = True
        priorities.append(
            {
                key: normalized[key]
                for key in (
                    "priority",
                    "zone_id",
                    "domain",
                    "action",
                    "reason",
                    "evidence_refs",
                    "uncertainty",
                    "requires_human_approval",
                )
                if key in normalized
            }
        )
    result["priorities"] = priorities
    for key in ("summary",):
        if not isinstance(result.get(key), str):
            result[key] = str(result.get(key) or "Farm-wide recommendations synthesized from validated zone reports.")
    for key in ("farm_wide_considerations", "unresolved_questions", "limitations"):
        result[key] = [str(item) for item in _as_list(result.get(key))]
    return {
        key: result[key]
        for key in (
            "schema_version",
            "farm_id",
            "analysis_run_id",
            "summary",
            "priorities",
            "farm_wide_considerations",
            "unresolved_questions",
            "limitations",
        )
        if key in result
    }
