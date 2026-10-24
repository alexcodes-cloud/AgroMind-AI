import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.api.config import Settings
from backend.api.main import _farm_for_analysis, create_app
from backend.services.batch_builder import build_stage1_batches
from ai.demo_plan_adapter import adapt_demo_farm_plan
from ai.farm_plan import FarmPlanValidationError, validate_farm_plan
from ai.gemini_provider import (
    GeminiProvider,
    ProviderConfigurationError,
    ProviderUpstreamError,
)
from ai.stage1_analyzer import Stage1Analyzer
from ai.stage2_analyzer import Stage2AnalysisError, Stage2Analyzer
from ai.stage2_prompt import PromptSafetyError, build_stage2_prompt


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
FARM_PATH = REPOSITORY_ROOT / "data-set" / "synthetic_farm.json"
WEATHER_PATH = REPOSITORY_ROOT / "contracts" / "example-weather.json"
ZONE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "zone-report.schema.json"
PLAN_SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "farm-plan.schema.json"


def make_settings(**overrides):
    values = {
        "app_environment": "test",
        "api_prefix": "/api/v1",
        "gemini_api_key": "test-key",
        "gemini_model": "test-gemma",
        "gemini_timeout_seconds": 1.0,
        "gemini_structured_output": False,
        "gemini_max_output_tokens": 4096,
        "gemini_thinking_level": "minimal",
        "demo_mode": False,
        "demo_fallback": False,
        "batch_size": 4,
        "open_meteo_base_url": "https://api.open-meteo.com/v1/forecast",
        "open_meteo_timeout_seconds": 1.0,
        "farm_data_path": FARM_PATH,
        "weather_fixture_path": WEATHER_PATH,
    }
    values.update(overrides)
    return Settings(**values)


def zone_report_for_batch(batch):
    assessments = []
    for zone in batch["zones"]:
        record_id = zone["sensors"][0]["record_id"]
        assessments.append(
            {
                "zone_id": zone["zone_id"],
                "hydration": {
                    "status": "investigation_needed",
                    "risk_level": "medium",
                    "confidence": "high",
                    "finding": "Moisture requires review.",
                    "evidence": [{"record_id": record_id, "interpretation": "Sensor reading."}],
                    "missing_information": [],
                    "recommended_actions": [],
                },
                "fertilization": {
                    "status": "normal",
                    "risk_level": "low",
                    "confidence": "moderate",
                    "finding": "No clear deficiency established.",
                    "evidence": [{"record_id": record_id, "interpretation": "Sensor reading."}],
                    "missing_information": [],
                    "recommended_actions": [],
                },
            }
        )
    return {
        "schema_version": "1.0",
        "farm_id": batch["farm_id"],
        "batch_id": batch["batch_id"],
        "assessments": assessments,
    }


class FakeZoneProvider:
    def generate_zone_report(self, prompt):
        observations = json.loads(prompt.split("OBSERVATIONS\n", 1)[1].split("\nEND OBSERVATIONS", 1)[0])
        return zone_report_for_batch(observations)


def make_stage1_result():
    farm = json.loads(FARM_PATH.read_text(encoding="utf-8"))
    weather = json.loads(WEATHER_PATH.read_text(encoding="utf-8"))
    return farm, weather, Stage1Analyzer(
        FakeZoneProvider(), schema_path=ZONE_SCHEMA_PATH, batch_size=4
    ).analyze(farm, weather, analysis_run_id="stage2_test")


def plan_for_result(result):
    evidence = result.batches[0].report.assessments[0].hydration.evidence[0].record_id
    zone_id = result.batches[0].report.assessments[0].zone_id
    return {
        "schema_version": "1.0",
        "farm_id": result.farm_id,
        "analysis_run_id": result.analysis_run_id,
        "summary": "Review the highest-priority hydration finding first.",
        "priorities": [{
            "priority": 1,
            "zone_id": zone_id,
            "domain": "hydration",
            "action": "Review irrigation for the affected zone.",
            "reason": "Stage 1 identified a hydration concern.",
            "evidence_refs": [evidence],
            "uncertainty": "Confirm conditions before acting.",
            "requires_human_approval": True,
        }],
        "farm_wide_considerations": ["Compare conditions again after review."],
        "unresolved_questions": [],
        "limitations": ["Synthetic demo data is not a field measurement."],
    }


class FakePlanProvider:
    def __init__(self, payload_factory):
        self.prompts = []
        self.payload_factory = payload_factory

    def generate_farm_plan(self, prompt):
        self.prompts.append(prompt)
        return self.payload_factory(len(self.prompts))


class Stage2Tests(unittest.TestCase):
    def test_prompt_contains_reports_and_excludes_hidden_labels(self):
        farm, weather, result = make_stage1_result()
        prompt = build_stage2_prompt(farm, weather, result)
        self.assertIn("zone_reports", prompt)
        self.assertIn(result.batches[0].report.assessments[0].zone_id, prompt)
        self.assertNotIn("evaluation_labels", prompt)

        unsafe_farm = copy.deepcopy(farm)
        unsafe_farm["scenario_label"] = "hidden"
        with self.assertRaises(PromptSafetyError):
            build_stage2_prompt(unsafe_farm, weather, result)

    def test_validator_enforces_stage1_evidence_traceability(self):
        farm, _, result = make_stage1_result()
        plan = plan_for_result(result)
        validated = validate_farm_plan(plan, result, schema_path=PLAN_SCHEMA_PATH)
        self.assertEqual(validated.farm_id, farm["farm_id"])

        invalid = copy.deepcopy(plan)
        invalid["priorities"][0]["evidence_refs"] = ["invented_record"]
        with self.assertRaises(FarmPlanValidationError):
            validate_farm_plan(invalid, result, schema_path=PLAN_SCHEMA_PATH)

    def test_stage2_retries_schema_invalid_output_with_feedback(self):
        farm, weather, result = make_stage1_result()

        def payload(attempt):
            if attempt == 1:
                return {"schema_version": "1.0"}
            return plan_for_result(result)

        provider = FakePlanProvider(payload)
        plan = Stage2Analyzer(provider, schema_path=PLAN_SCHEMA_PATH).synthesize(
            farm, weather, result
        )
        self.assertEqual(plan.analysis_run_id, result.analysis_run_id)
        self.assertEqual(len(provider.prompts), 2)
        self.assertIn("failed contract validation", provider.prompts[1])

    def test_demo_adapter_removes_aliases_and_preserves_refs(self):
        _, _, result = make_stage1_result()
        valid = plan_for_result(result)
        raw = {
            "schema_version": valid["schema_version"],
            "farm_id": valid["farm_id"],
            "analysis_run_id": valid["analysis_run_id"],
            "summary": valid["summary"],
            "actions": [{
                "priority": "high",
                "zone_id": valid["priorities"][0]["zone_id"],
                "category": "irrigation",
                "recommendation": "Review irrigation.",
                "rationale": "Moisture concern.",
                "evidence": [{"record_id": valid["priorities"][0]["evidence_refs"][0]}],
            }],
        }
        adapted = adapt_demo_farm_plan(raw)
        self.assertNotIn("actions", adapted)
        self.assertEqual(adapted["priorities"][0]["domain"], "hydration")
        self.assertEqual(adapted["priorities"][0]["priority"], 1)
        validate_farm_plan(adapted, result, schema_path=PLAN_SCHEMA_PATH)

    def test_provider_uses_farm_plan_schema_when_structured_output_enabled(self):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            text='{"schema_version":"1.0"}'
        )
        provider = GeminiProvider(make_settings(gemini_structured_output=True), client=client)
        provider.generate_farm_plan("plan prompt")
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertIs(config.response_schema, __import__(
            "ai.farm_plan", fromlist=["FarmPlan"]
        ).FarmPlan)

    def test_plan_endpoint_runs_both_stages_and_returns_valid_plan(self):
        farm, weather, _ = make_stage1_result()
        stage1_analyzer = Stage1Analyzer(
            FakeZoneProvider(), schema_path=ZONE_SCHEMA_PATH, batch_size=4
        )

        class EndpointPlanProvider:
            def generate_farm_plan(self, prompt):
                observations = json.loads(
                    prompt.split("OBSERVATIONS\n", 1)[1].split("\nEND OBSERVATIONS", 1)[0]
                )
                stage1 = observations["stage1"] if "stage1" in observations else None
                # Stage 2's production prompt intentionally contains the
                # compact zone_reports view, so use it to return a traceable
                # mocked plan for this API test.
                first_report = observations["zone_reports"][0]["report"]
                first_assessment = first_report["assessments"][0]
                evidence_ref = first_assessment["hydration"]["evidence"][0]["record_id"]
                return {
                    "schema_version": "1.0",
                    "farm_id": observations["farm_id"],
                    "analysis_run_id": observations["analysis_run_id"],
                    "summary": "Review the first hydration finding.",
                    "priorities": [{
                        "priority": 1,
                        "zone_id": first_assessment["zone_id"],
                        "domain": "hydration",
                        "action": "Review irrigation.",
                        "reason": "Stage 1 finding requires review.",
                        "evidence_refs": [evidence_ref],
                        "uncertainty": "Confirm before acting.",
                        "requires_human_approval": True,
                    }],
                    "farm_wide_considerations": [],
                    "unresolved_questions": [],
                    "limitations": [],
                }

        stage2_analyzer = Stage2Analyzer(
            EndpointPlanProvider(), schema_path=PLAN_SCHEMA_PATH
        )
        client = TestClient(
            create_app(
                make_settings(gemini_api_key="test-key"),
                stage1_analyzer=stage1_analyzer,
                stage2_analyzer=stage2_analyzer,
            )
        )
        response = client.post(
            "/api/v1/analysis/plan",
            json={"analysis_run_id": "api_stage2", "batch_size": 4},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysis_run_id"], "api_stage2")
        self.assertEqual(response.json()["priorities"][0]["zone_id"], "Z01")

    def test_explicit_fallback_completes_stage1_without_gemini(self):
        farm = json.loads(FARM_PATH.read_text(encoding="utf-8"))
        weather = json.loads(WEATHER_PATH.read_text(encoding="utf-8"))

        class UnconfiguredProvider:
            def generate_zone_report(self, prompt):
                raise ProviderConfigurationError("GEMINI_API_KEY is not configured")

        result = Stage1Analyzer(
            UnconfiguredProvider(),
            schema_path=ZONE_SCHEMA_PATH,
            batch_size=4,
            demo_fallback=True,
        ).analyze(farm, weather, analysis_run_id="fallback_stage1")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.to_dict()["analysis_mode"], "local_demo_fallback")
        self.assertEqual(result.total_batches, 3)

    def test_explicit_fallback_completes_plan_when_gemini_fails(self):
        farm, weather, result = make_stage1_result()

        class FailingProvider:
            def generate_farm_plan(self, prompt):
                raise ProviderUpstreamError("upstream", status_code=500, provider_status="INTERNAL")

        plan = Stage2Analyzer(
            FailingProvider(), schema_path=PLAN_SCHEMA_PATH, demo_fallback=True
        ).synthesize(farm, weather, result)
        self.assertIn("local demo fallback", plan.limitations[0])
        validate_farm_plan(plan.model_dump(mode="json"), result, schema_path=PLAN_SCHEMA_PATH)

    def test_plan_endpoint_explicit_fallback_is_visible_and_needs_no_key(self):
        client = TestClient(
            create_app(
                make_settings(
                    gemini_api_key=None,
                    demo_mode=True,
                    demo_fallback=True,
                )
            )
        )
        response = client.post(
            "/api/v1/analysis/plan",
            json={"analysis_run_id": "fallback_api", "batch_size": 4},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("local demo fallback", payload["limitations"][0])

    def test_dashboard_endpoint_returns_shared_frontend_contract_in_fallback(self):
        client = TestClient(
            create_app(
                make_settings(
                    gemini_api_key=None,
                    demo_fallback=True,
                )
            )
        )
        response = client.post(
            "/api/v1/dashboard",
            json={"analysis_run_id": "dashboard_test", "batch_size": 4},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis_run_id"], "dashboard_test")
        self.assertEqual(payload["summary"]["zones_total"], 12)
        self.assertEqual(payload["summary"]["zones_analyzed"], 12)
        self.assertEqual(len(payload["zones"]), 12)
        self.assertIn("action_plan", payload)

    def test_dashboard_zone_limit_reduces_ai_scope_but_keeps_farm_total(self):
        client = TestClient(
            create_app(
                make_settings(
                    gemini_api_key=None,
                    demo_fallback=True,
                    analysis_zone_limit=4,
                )
            )
        )
        response = client.post(
            "/api/v1/dashboard",
            json={"analysis_run_id": "limited_dashboard", "batch_size": 4},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["zones_total"], 12)
        self.assertEqual(payload["summary"]["zones_analyzed"], 4)
        self.assertEqual(len(payload["zones"]), 4)

    def test_analysis_scope_can_keep_only_example_records(self):
        farm = json.loads(FARM_PATH.read_text(encoding="utf-8"))
        scoped = _farm_for_analysis(farm, zone_limit=2, record_limit=2)
        self.assertEqual(len(scoped["zones"]), 2)
        self.assertTrue(all(len(zone["sensors"]) == 2 for zone in scoped["zones"]))
        self.assertTrue(all("drone_observations" not in zone for zone in scoped["zones"]))
        self.assertEqual(len(farm["zones"]), 12)
        self.assertEqual(len(farm["zones"][0]["sensors"]), 2)
        self.assertEqual(
            [sensor["field"] for sensor in farm["zones"][0]["sensors"]],
            ["soil_moisture", "nitrogen"],
        )


if __name__ == "__main__":
    unittest.main()
