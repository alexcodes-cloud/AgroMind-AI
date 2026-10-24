"""Generate repeatable synthetic AgroMind farm data.
Never send evaluation_labels.json to the AI; it is ground truth for tests only.
Run: python data-set/generate_dataset.py --seed 42 --zones 12
"""
import argparse, json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIOS = [
    "healthy", "water_stress", "possible_nutrient_deficiency",
    "mixed_water_and_nutrient_risk", "uncertain_missing_data",
    "sensor_quality_issue", "healthy", "water_stress",
    "possible_nutrient_deficiency", "healthy",
    "mixed_water_and_nutrient_risk", "uncertain_missing_data"
]

def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def generate_dataset(seed=42, zones_count=12, farm_id="farm_001",
                     latitude=33.97, longitude=-6.87,
                     timezone_name="Africa/Casablanca"):
    if zones_count < 1:
        raise ValueError("zones_count must be >= 1")
    rng = random.Random(seed)
    now = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    scenarios = (SCENARIOS * ((zones_count // len(SCENARIOS)) + 1))[:zones_count]
    zones, labels = [], []
    for i, scenario in enumerate(scenarios, start=1):
        zid = f"Z{i:02d}"
        moisture = rng.uniform(28, 42)
        temp = rng.uniform(21, 29)
        ph = rng.uniform(6.0, 7.0)
        n, p, k = rng.uniform(35, 65), rng.uniform(15, 30), rng.uniform(80, 150)
        leaf = "no_obvious_stress_observed"
        quality_override = {}
        if scenario == "water_stress":
            moisture, temp, leaf = rng.uniform(10, 19), rng.uniform(28, 35), "possible_wilting"
        elif scenario == "possible_nutrient_deficiency":
            n, leaf = rng.uniform(8, 20), "possible_leaf_yellowing"
        elif scenario == "mixed_water_and_nutrient_risk":
            moisture, n, temp = rng.uniform(11, 19), rng.uniform(8, 20), rng.uniform(28, 34)
            leaf = "possible_wilting_and_yellowing"
        elif scenario == "uncertain_missing_data":
            moisture, n, leaf = None, None, "yellowing_unclear_cause"
        elif scenario == "sensor_quality_issue":
            moisture, leaf = rng.uniform(8, 15), "no_obvious_stress_observed"
            quality_override["soil_moisture"] = "suspect"

        # Keep the fixture compact for live Gemini demos. These are the two
        # signals used by the demo scope: hydration and fertilization. The
        # scenario variation still gives the model healthy, stressed,
        # nutrient-deficient, and uncertain examples across the farm.
        specs = [
            ("soil_moisture", moisture, "percent_vwc", 20),
            ("nitrogen", n, "mg/kg", None),
        ]
        sensors = []
        for field, value, unit, depth in specs:
            value = None if value is None else round(value, 2 if field == "soil_ph" else 1)
            quality = quality_override.get(field, "valid")
            if value is None:
                quality = "missing"
            sensor = {
                "record_id": f"sensor_{zid}_{field}_001",
                "field": field, "value": value, "unit": unit,
                "measured_at": stamp(now - timedelta(minutes=5)),
                "quality": quality,
            }
            # Keep the compact demo shape: moisture only needs its value and
            # unit, while nitrogen retains an explicit null depth like the
            # agreed farm/zone example.
            if field == "nitrogen":
                sensor["depth_cm"] = depth
            sensors.append(sensor)
        zones.append({
            "zone_id": zid, "area_ha": round(rng.uniform(2, 5.5), 2),
            "crop": {"type": "tomato", "variety": "demo_variety",
                     "growth_stage": "fruit_development", "soil_type": "loam"},
            "sensors": sensors,
        })
        labels.append({
            "zone_id": zid, "scenario_label": scenario,
            "expected_hydration": (
                "investigation_needed" if scenario in ("water_stress", "mixed_water_and_nutrient_risk")
                else "insufficient_evidence" if scenario in ("uncertain_missing_data", "sensor_quality_issue")
                else "normal"
            ),
            "expected_fertilization": (
                "investigation_needed" if scenario in ("possible_nutrient_deficiency", "mixed_water_and_nutrient_risk")
                else "insufficient_evidence" if scenario == "uncertain_missing_data"
                else "normal"
            ),
            "evaluation_note": "Hidden synthetic label for offline testing only; never send to AI."
        })
    farm = {
        "schema_version": "1.0", "farm_id": farm_id,
        "farm_name": "AgroMind Synthetic Demo Farm",
        "location": {"latitude": latitude, "longitude": longitude, "timezone": timezone_name},
        "crop_defaults": {"type": "tomato", "variety": "demo_variety",
                          "growth_stage": "fruit_development", "soil_type": "loam"},
        "zones": zones
    }
    evaluation = {
        "schema_version": "1.0", "farm_id": farm_id, "seed": seed,
        "warning": "Ground-truth labels only. Do not include this file in model prompts.",
        "zones": labels
    }
    return farm, evaluation

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--zones", type=int, default=12)
    parser.add_argument("--farm-id", default="farm_001")
    parser.add_argument("--latitude", type=float, default=33.97)
    parser.add_argument("--longitude", type=float, default=-6.87)
    parser.add_argument("--timezone", default="Africa/Casablanca")
    args = parser.parse_args()
    farm, evaluation = generate_dataset(args.seed, args.zones, args.farm_id,
                                        args.latitude, args.longitude, args.timezone)
    (ROOT / "synthetic_farm.json").write_text(json.dumps(farm, indent=2) + "\n", encoding="utf-8")
    (ROOT / "evaluation_labels.json").write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(farm['zones'])} zones.")
    print("Keep data-set/evaluation_labels.json out of AI prompts.")

if __name__ == "__main__":
    main()
