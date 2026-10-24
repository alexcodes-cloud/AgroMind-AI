"""Build deterministic, self-contained zone batches for AgroMind Stage 1.

This module intentionally uses only the Python standard library. It prepares
payloads; it does not call the Gemini/Gemma API and never loads evaluation labels.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable


class BatchBuildError(ValueError):
    """Raised when farm/weather input cannot be converted into Stage 1 batches."""


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchBuildError(f"{name} must be a JSON object")
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _infer_survey_time(zones: Iterable[dict[str, Any]]) -> str | None:
    """Return the latest sensor/drone timestamp, if any are parseable."""
    latest: tuple[datetime, str] | None = None
    for zone in zones:
        for record in zone.get("sensors", []):
            if isinstance(record, dict):
                value = record.get("measured_at")
                parsed = _parse_timestamp(value)
                if parsed and (latest is None or parsed > latest[0]):
                    latest = (parsed, value)
        for record in zone.get("drone_observations", []):
            if isinstance(record, dict):
                value = record.get("observed_at")
                parsed = _parse_timestamp(value)
                if parsed and (latest is None or parsed > latest[0]):
                    latest = (parsed, value)
    return latest[1] if latest else None


def build_stage1_batches(
    farm: dict[str, Any],
    weather: dict[str, Any] | None = None,
    *,
    batch_size: int = 4,
    analysis_run_id: str = "demo_run_001",
    survey_time: str | None = None,
) -> list[dict[str, Any]]:
    """Build batches for Stage 1 from a farm object and optional weather object.

    Each batch includes the common farm context and weather snapshot, plus a
    slice of the original zone objects. Zone/sensor/drone IDs are preserved.
    Evaluation labels are not accepted as an argument and must never be added
    to these payloads.
    """
    farm = _require_mapping(farm, "farm")
    if weather is not None:
        weather = _require_mapping(weather, "weather")
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise BatchBuildError("batch_size must be a positive integer")
    if not isinstance(analysis_run_id, str) or not analysis_run_id.strip():
        raise BatchBuildError("analysis_run_id must be a non-empty string")
    if survey_time is not None and _parse_timestamp(survey_time) is None:
        raise BatchBuildError("survey_time must be an RFC 3339 timestamp")

    farm_id = farm.get("farm_id")
    zones = farm.get("zones")
    if not isinstance(farm_id, str) or not farm_id.strip():
        raise BatchBuildError("farm.farm_id must be a non-empty string")
    if not isinstance(zones, list) or not zones:
        raise BatchBuildError("farm.zones must be a non-empty array")

    seen_zone_ids: set[str] = set()
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise BatchBuildError(f"farm.zones[{index}] must be an object")
        zone_id = zone.get("zone_id")
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise BatchBuildError(f"farm.zones[{index}].zone_id must be a non-empty string")
        if zone_id in seen_zone_ids:
            raise BatchBuildError(f"duplicate zone_id: {zone_id}")
        seen_zone_ids.add(zone_id)

    resolved_survey_time = survey_time or _infer_survey_time(zones)
    farm_context = {
        "farm_name": farm.get("farm_name"),
        "location": deepcopy(farm.get("location", {})),
        "crop_defaults": deepcopy(farm.get("crop_defaults", {})),
    }
    # Omit missing optional values instead of sending nulls for them.
    farm_context = {key: value for key, value in farm_context.items() if value not in (None, {})}

    chunks = [zones[i : i + batch_size] for i in range(0, len(zones), batch_size)]
    total_batches = len(chunks)
    batches: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "farm_id": farm_id,
            "analysis_run_id": analysis_run_id,
            "batch_id": f"{analysis_run_id}_batch_{index:03d}",
            "batch_index": index,
            "total_batches": total_batches,
            "farm_context": deepcopy(farm_context),
            "zones": deepcopy(chunk),
        }
        if resolved_survey_time:
            payload["survey_time"] = resolved_survey_time
        if weather is not None:
            payload["weather"] = deepcopy(weather)
        batches.append(payload)
    return batches


def load_json_object(path: str) -> dict[str, Any]:
    """Load a JSON object from disk with a useful error message."""
    import json
    from pathlib import Path

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchBuildError(f"could not load JSON from {path}: {exc}") from exc
    return _require_mapping(value, path)
