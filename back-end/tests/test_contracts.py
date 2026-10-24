"""Regression tests for the shared JSON contracts and their example payloads."""
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


class ContractTests(unittest.TestCase):
    def load_json(self, path: Path):
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_all_schema_files_are_valid_json_schema(self):
        schemas = sorted(CONTRACTS.glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 5, "Expected the five shared schemas")
        for path in schemas:
            with self.subTest(schema=path.name):
                schema = self.load_json(path)
                Draft202012Validator.check_schema(schema)

    def test_example_farm_matches_schema(self):
        schema = self.load_json(CONTRACTS / "farm.schema.json")
        example = self.load_json(CONTRACTS / "example-farm.json")
        errors = sorted(
            Draft202012Validator(schema).iter_errors(example),
            key=lambda error: list(map(str, error.absolute_path)),
        )
        self.assertEqual(
            [],
            [f"{list(error.absolute_path)}: {error.message}" for error in errors],
        )

    def test_example_weather_matches_schema(self):
        schema = self.load_json(CONTRACTS / "weather.schema.json")
        example = self.load_json(CONTRACTS / "example-weather.json")
        errors = sorted(
            Draft202012Validator(schema).iter_errors(example),
            key=lambda error: list(map(str, error.absolute_path)),
        )
        self.assertEqual(
            [],
            [f"{list(error.absolute_path)}: {error.message}" for error in errors],
        )


if __name__ == "__main__":
    unittest.main()
