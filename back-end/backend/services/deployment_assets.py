"""Small serverless-only asset fallback for deployments that omit JSON files."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


def _build_farm() -> dict[str, Any]:
    zones = []
    moisture_values = [37.0, 11.8, 31.1, 18.4]
    for index, moisture in enumerate(moisture_values, start=1):
        zone_id = f"Z{index:02d}"
        zones.append(
            {
                "zone_id": zone_id,
                "area_ha": 3.0 + index / 10,
                "polygon_geojson": None,
                "crop": {
                    "type": "tomato",
                    "variety": "demo_variety",
                    "growth_stage": "fruit_development",
                    "soil_type": "loam",
                },
                "sensors": [
                    {
                        "record_id": f"sensor_{zone_id}_soil_moisture_001",
                        "sensor_id": f"sensor_{zone_id}_soil_moisture",
                        "field": "soil_moisture",
                        "value": moisture,
                        "unit": "percent_vwc",
                        "depth_cm": 20,
                        "measured_at": "2026-10-24T09:55:00Z",
                        "quality": "valid",
                        "notes": "Synthetic deployment example.",
                    },
                    {
                        "record_id": f"sensor_{zone_id}_nitrogen_001",
                        "field": "nitrogen",
                        "value": 20.0 + index * 4,
                        "unit": "mg/kg",
                        "depth_cm": None,
                        "measured_at": "2026-10-24T09:55:00Z",
                        "quality": "valid",
                        "notes": "Synthetic deployment example.",
                    },
                ],
                "management_history": {
                    "last_irrigation_at": None,
                    "last_fertilization_at": None,
                    "notes": "Synthetic deployment example.",
                },
            }
        )
    return {
        "schema_version": "1.0",
        "farm_id": "farm_001",
        "farm_name": "AgroMind Synthetic Demo Farm",
        "location": {"latitude": 33.97, "longitude": -6.87, "timezone": "Africa/Casablanca"},
        "crop_defaults": {"type": "tomato", "variety": "demo_variety", "growth_stage": "fruit_development", "soil_type": "loam"},
        "zones": zones,
    }


def load_embedded_json(name: str) -> dict[str, Any]:
    if name == "farm":
        return _build_farm()
    if name == "weather":
        return {
            "schema_version": "1.0",
            "farm_id": "farm_001",
            "source": "Open-Meteo",
            "retrieved_at": "2026-10-24T10:00:00Z",
            "location": {"latitude": 33.97, "longitude": -6.87, "timezone": "Africa/Casablanca"},
            "current": {"temperature_c": 29, "relative_humidity_pct": 48, "wind_speed_kmh": 12, "precipitation_mm": 0, "et0_mm": None, "valid_at": "2026-10-24T10:00:00Z"},
            "forecast": [{"time": "2026-10-24T14:00:00Z", "temperature_c": 32, "relative_humidity_pct": None, "wind_speed_kmh": None, "precipitation_mm": 0.5, "et0_mm": None}],
        }
    if name == "zone_schema":
        return {"type": "object", "required": ["schema_version", "farm_id", "batch_id", "assessments"], "properties": {"schema_version": {"const": "1.0"}, "farm_id": {"type": "string"}, "batch_id": {"type": "string"}, "assessments": {"type": "array"}}}
    if name == "plan_schema":
        return {"type": "object", "required": ["schema_version", "farm_id", "analysis_run_id", "summary", "priorities", "farm_wide_considerations", "unresolved_questions", "limitations"], "properties": {"schema_version": {"const": "1.0"}, "farm_id": {"type": "string"}, "analysis_run_id": {"type": "string"}, "summary": {"type": "string"}, "priorities": {"type": "array"}, "farm_wide_considerations": {"type": "array"}, "unresolved_questions": {"type": "array"}, "limitations": {"type": "array"}}}
    raise KeyError(f"unknown embedded asset: {name}")


def materialize_embedded_json(name: str) -> Path:
    target = Path(tempfile.gettempdir()) / f"agromind-{name}.json"
    if not target.is_file():
        target.write_text(json.dumps(load_embedded_json(name)), encoding="utf-8")
    return target
