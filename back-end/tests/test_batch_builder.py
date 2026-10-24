import copy
import json
import unittest
from pathlib import Path

from backend.services.batch_builder import BatchBuildError, build_stage1_batches

ROOT = Path(__file__).resolve().parents[1]


class BatchBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.farm = json.loads((ROOT.parent / "data-set/synthetic_farm.json").read_text(encoding="utf-8"))

    def test_splits_zones_and_preserves_ids(self):
        batches = build_stage1_batches(self.farm, batch_size=4, analysis_run_id="test_run")
        self.assertEqual(len(batches), 3)
        self.assertEqual([len(batch["zones"]) for batch in batches], [4, 4, 4])
        self.assertEqual(batches[0]["batch_id"], "test_run_batch_001")
        self.assertEqual(batches[0]["zones"][0]["zone_id"], "Z01")
        self.assertEqual(
            batches[0]["zones"][0]["sensors"][0]["record_id"],
            self.farm["zones"][0]["sensors"][0]["record_id"],
        )

    def test_attaches_weather_and_shared_context(self):
        weather = {"snapshot_id": "weather_demo", "temperature_c": 25}
        batches = build_stage1_batches(self.farm, weather, batch_size=5)
        self.assertEqual([len(batch["zones"]) for batch in batches], [5, 5, 2])
        self.assertEqual(batches[0]["weather"], weather)
        self.assertEqual(batches[0]["farm_context"]["crop_defaults"]["type"], "tomato")
        self.assertIn("survey_time", batches[0])

    def test_does_not_mutate_inputs_or_include_evaluation_labels(self):
        farm = copy.deepcopy(self.farm)
        original = copy.deepcopy(farm)
        batches = build_stage1_batches(farm, batch_size=6)
        self.assertEqual(farm, original)
        self.assertTrue(all("evaluation_labels" not in batch for batch in batches))
        self.assertTrue(all("scenario_label" not in json.dumps(batch) for batch in batches))

    def test_rejects_duplicate_zone_ids(self):
        farm = copy.deepcopy(self.farm)
        farm["zones"][1]["zone_id"] = farm["zones"][0]["zone_id"]
        with self.assertRaises(BatchBuildError):
            build_stage1_batches(farm)

    def test_rejects_invalid_batch_size(self):
        with self.assertRaises(BatchBuildError):
            build_stage1_batches(self.farm, batch_size=0)

    def test_rejects_invalid_run_metadata(self):
        with self.assertRaises(BatchBuildError):
            build_stage1_batches(self.farm, analysis_run_id="")
        with self.assertRaises(BatchBuildError):
            build_stage1_batches(self.farm, survey_time="not-a-timestamp")


if __name__ == "__main__":
    unittest.main()
