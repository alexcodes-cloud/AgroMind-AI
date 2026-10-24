import importlib.util
import unittest
from pathlib import Path


GENERATOR_PATH = Path(__file__).resolve().parents[2] / "data-set" / "generate_dataset.py"
SPEC = importlib.util.spec_from_file_location("agromind_dataset_generator", GENERATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Could not load dataset generator from {GENERATOR_PATH}")
DATASET_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATASET_MODULE)
generate_dataset = DATASET_MODULE.generate_dataset

class DatasetTests(unittest.TestCase):
    def test_repeatable_zone_ids_and_labels(self):
        a, labels_a = generate_dataset(seed=42, zones_count=12)
        b, labels_b = generate_dataset(seed=42, zones_count=12)
        self.assertEqual([z["zone_id"] for z in a["zones"]], [z["zone_id"] for z in b["zones"]])
        self.assertEqual([x["scenario_label"] for x in labels_a["zones"]], [x["scenario_label"] for x in labels_b["zones"]])
        self.assertEqual(len(a["zones"]), 12)

    def test_record_ids_unique(self):
        farm, _ = generate_dataset(seed=42, zones_count=12)
        ids = []
        for zone in farm["zones"]:
            ids += [x["record_id"] for x in zone["sensors"]]
            ids += [x["record_id"] for x in zone.get("drone_observations", [])]
        self.assertEqual(len(ids), len(set(ids)))

    def test_missing_values_are_explicit(self):
        farm, _ = generate_dataset(seed=42, zones_count=12)
        zone = next(z for z in farm["zones"] if z["zone_id"] == "Z05")
        moisture = next(s for s in zone["sensors"] if s["field"] == "soil_moisture")
        self.assertIsNone(moisture["value"])
        self.assertEqual(moisture["quality"], "missing")

if __name__ == "__main__":
    unittest.main()
