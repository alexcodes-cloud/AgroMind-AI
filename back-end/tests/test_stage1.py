import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.api.config import Settings
from backend.api.main import create_app
from backend.services.batch_builder import build_stage1_batches
from ai.demo_zone_adapter import adapt_demo_zone_report
from ai.gemini_provider import (
    GeminiProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnsupportedRequestError,
    ProviderUpstreamError,
    _classify_provider_exception,
    _parse_json_object,
    _response_text,
)
from ai.stage1_analyzer import Stage1Analyzer
from ai.stage1_prompt import PromptSafetyError, build_stage1_prompt
from ai.zone_report import ZoneReportValidationError, validate_zone_report


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
FARM_PATH = REPOSITORY_ROOT / "data-set" / "synthetic_farm.json"
WEATHER_PATH = REPOSITORY_ROOT / "contracts" / "example-weather.json"
SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "zone-report.schema.json"


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


def report_for_batch(batch):
    assessments = []
    for zone in batch["zones"]:
        sensor_id = zone["sensors"][0]["record_id"]
        nutrient_id = zone["sensors"][1]["record_id"]
        assessments.append(
            {
                "zone_id": zone["zone_id"],
                "hydration": {
                    "status": "normal",
                    "risk_level": "low",
                    "confidence": "high",
                    "finding": "Observed moisture data does not indicate immediate stress.",
                    "evidence": [{"record_id": sensor_id, "interpretation": "Sensor reading supplied in the batch."}],
                    "missing_information": [],
                    "recommended_actions": [],
                },
                "fertilization": {
                    "status": "normal",
                    "risk_level": "low",
                    "confidence": "moderate",
                    "finding": "No actionable deficiency is established by this batch alone.",
                    "evidence": [{"record_id": nutrient_id, "interpretation": "Nitrogen reading supplied in the batch."}],
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
    def __init__(self, payload_factory=report_for_batch):
        self.prompts = []
        self.payload_factory = payload_factory

    def generate_zone_report(self, prompt):
        self.prompts.append(prompt)
        observations = json.loads(prompt.split("OBSERVATIONS\n", 1)[1].split("\nEND OBSERVATIONS", 1)[0])
        return self.payload_factory(observations)


class RaisingZoneProvider:
    def __init__(self, error):
        self.error = error

    def generate_zone_report(self, prompt):
        raise self.error


class RetryOnceZoneProvider:
    def __init__(self):
        self.prompts = []

    def generate_zone_report(self, prompt):
        self.prompts.append(prompt)
        observations = json.loads(prompt.split("OBSERVATIONS\n", 1)[1].split("\nEND OBSERVATIONS", 1)[0])
        if len(self.prompts) == 1:
            return {"schema_version": "1.0", "farm_id": observations["farm_id"], "batch_id": observations["batch_id"], "assessments": []}
        return report_for_batch(observations)


class MockSdkError(Exception):
    def __init__(self, code, status, message):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class Stage1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.farm = json.loads(FARM_PATH.read_text(encoding="utf-8"))
        cls.weather = json.loads(WEATHER_PATH.read_text(encoding="utf-8"))

    def test_prompt_contains_observations_and_excludes_hidden_labels(self):
        batch = build_stage1_batches(self.farm, self.weather, batch_size=4, analysis_run_id="prompt_test")[0]
        prompt = build_stage1_prompt(batch)
        self.assertIn("untrusted input data", prompt)
        self.assertIn(batch["zones"][0]["sensors"][0]["record_id"], prompt)
        self.assertIn("Do not use the aliases risk, actions", prompt)
        self.assertIn("must be exactly one of normal, investigation_needed", prompt)
        self.assertNotIn("scenario_label", prompt)

        unsafe_batch = copy.deepcopy(batch)
        unsafe_batch["zones"][0]["scenario_label"] = "hidden"
        with self.assertRaises(PromptSafetyError):
            build_stage1_prompt(unsafe_batch)

    def test_pipeline_returns_one_valid_report_per_batch(self):
        provider = FakeZoneProvider()
        analyzer = Stage1Analyzer(provider, schema_path=SCHEMA_PATH, batch_size=4)
        result = analyzer.analyze(self.farm, self.weather, analysis_run_id="run_test")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.total_batches, 3)
        self.assertEqual([item.batch_id for item in result.batches], [
            "run_test_batch_001", "run_test_batch_002", "run_test_batch_003"
        ])
        self.assertEqual(len(provider.prompts), 3)
        self.assertTrue(all("evaluation_labels" not in prompt for prompt in provider.prompts))

    def test_pipeline_retries_schema_invalid_report_with_feedback(self):
        provider = RetryOnceZoneProvider()
        analyzer = Stage1Analyzer(provider, schema_path=SCHEMA_PATH, batch_size=4)
        result = analyzer.analyze(self.farm, self.weather, analysis_run_id="retry_test")
        self.assertEqual(result.status, "completed")
        self.assertGreaterEqual(len(provider.prompts), 4)
        self.assertIn("previous response did not pass", provider.prompts[1])

    def test_pipeline_retries_one_transient_batch_provider_failure(self):
        class TransientThenValidProvider:
            def __init__(self):
                self.calls = 0

            def generate_zone_report(self, prompt):
                self.calls += 1
                if self.calls == 1:
                    raise ProviderUpstreamError(
                        "upstream", status_code=500, provider_status="INTERNAL"
                    )
                observations = json.loads(
                    prompt.split("OBSERVATIONS\n", 1)[1].split("\nEND OBSERVATIONS", 1)[0]
                )
                return report_for_batch(observations)

        provider = TransientThenValidProvider()
        analyzer = Stage1Analyzer(provider, schema_path=SCHEMA_PATH, batch_size=4)
        result = analyzer.analyze(self.farm, self.weather, analysis_run_id="provider_retry")
        self.assertEqual(result.status, "completed")
        self.assertEqual(provider.calls, 4)

    def test_validator_rejects_fabricated_evidence(self):
        batch = build_stage1_batches(self.farm, batch_size=4, analysis_run_id="validation_test")[0]
        payload = report_for_batch(batch)
        payload["assessments"][0]["hydration"]["evidence"][0]["record_id"] = "invented_record"
        with self.assertRaises(ZoneReportValidationError):
            validate_zone_report(payload, batch, schema_path=SCHEMA_PATH)

    def test_demo_adapter_normalizes_aliases_without_inventing_evidence(self):
        batch = build_stage1_batches(self.farm, batch_size=1, analysis_run_id="demo_adapter")[0]
        record_id = batch["zones"][0]["sensors"][0]["record_id"]
        payload = {
            "schema_version": "1.0",
            "farm_id": batch["farm_id"],
            "batch_id": batch["batch_id"],
            "assessments": [{
                "hydration": {
                    "status": "optimal",
                    "risk": "none",
                    "confidence": "medium",
                    "finding": "Looks healthy.",
                    "evidence_interpretations": [{"record_id": record_id, "interpretation": "Observed."}],
                    "missing_information": None,
                    "actions": "Continue monitoring.",
                },
                "fertilization": {
                    "status": "normal",
                    "risk": "low",
                    "confidence": "high",
                    "finding": "No clear deficiency.",
                    "evidence_interpretations": [{"record_id": "invented", "interpretation": "No."}],
                    "missing_information": [],
                    "actions": [],
                },
            }],
        }
        adapted = adapt_demo_zone_report(payload, batch)
        report = validate_zone_report(adapted, batch, schema_path=SCHEMA_PATH)
        self.assertEqual(report.assessments[0].zone_id, batch["zones"][0]["zone_id"])
        self.assertEqual(report.assessments[0].hydration.status, "normal")
        self.assertEqual(report.assessments[0].hydration.evidence[0].record_id, record_id)
        self.assertEqual(report.assessments[0].fertilization.evidence, [])

    def test_validator_rejects_duplicate_and_unexpected_zones(self):
        batch = build_stage1_batches(self.farm, batch_size=4, analysis_run_id="zone_test")[0]
        payload = report_for_batch(batch)
        payload["assessments"][1]["zone_id"] = payload["assessments"][0]["zone_id"]
        with self.assertRaises(ZoneReportValidationError):
            validate_zone_report(payload, batch, schema_path=SCHEMA_PATH)

        payload = report_for_batch(batch)
        payload["assessments"] = payload["assessments"][:-1]
        with self.assertRaises(ZoneReportValidationError):
            validate_zone_report(payload, batch, schema_path=SCHEMA_PATH)

        payload = report_for_batch(batch)
        payload["assessments"][0]["hydration"].pop("finding")
        with self.assertRaises(ZoneReportValidationError):
            validate_zone_report(payload, batch, schema_path=SCHEMA_PATH)

        payload = report_for_batch(batch)
        payload["assessments"][0]["zone_id"] = "unexpected_zone"
        with self.assertRaises(ZoneReportValidationError):
            validate_zone_report(payload, batch, schema_path=SCHEMA_PATH)

    def test_provider_requires_key_and_parses_mocked_sdk_response(self):
        with self.assertRaises(ProviderConfigurationError):
            GeminiProvider(make_settings(gemini_api_key=None))

        client = MagicMock()
        client.models.generate_content.return_value.text = '{"schema_version":"1.0"}'
        provider = GeminiProvider(make_settings(), client=client)
        payload = provider.generate_zone_report("test prompt")
        self.assertEqual(payload["schema_version"], "1.0")
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "test-gemma")
        self.assertEqual(call["contents"], "test prompt")
        self.assertEqual(call["config"].max_output_tokens, 4096)
        self.assertEqual(call["config"].thinking_config.thinking_level.value, "MINIMAL")

        client = MagicMock()
        client.models.generate_content.return_value.text = '{"schema_version":"1.0"}'
        provider = GeminiProvider(make_settings(gemini_structured_output=True), client=client)
        provider.generate_zone_report("structured prompt")
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertIsNotNone(config.response_schema)
        self.assertEqual(config.max_output_tokens, 4096)
        self.assertEqual(config.thinking_config.thinking_level.value, "MINIMAL")

    def test_provider_rejects_invalid_json_and_classifies_failures(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = "not json"
        with self.assertRaises(ProviderMalformedResponseError):
            GeminiProvider(make_settings(), client=client).generate_zone_report("prompt")

        candidate_response = SimpleNamespace(
            text="",
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[SimpleNamespace(text='{"schema_version":"1.0"}')]
                    )
                )
            ],
        )
        self.assertEqual(
            _response_text(candidate_response), '{"schema_version":"1.0"}'
        )
        client = MagicMock()
        client.models.generate_content.return_value = candidate_response
        payload = GeminiProvider(make_settings(), client=client).generate_zone_report("prompt")
        self.assertEqual(payload["schema_version"], "1.0")

        self.assertEqual(
            _parse_json_object('```json\n{"schema_version":"1.0"}\n```'),
            {"schema_version": "1.0"},
        )
        self.assertEqual(
            _parse_json_object('Here is the result:\n{"schema_version":"1.0"}\nDone.'),
            {"schema_version": "1.0"},
        )
        self.assertIsNone(_parse_json_object("The model did not return JSON."))

        for message, expected in [
            ("401 unauthorized", ProviderAuthenticationError),
            ("429 rate limit", ProviderRateLimitError),
            ("request timeout", ProviderTimeoutError),
            ("network connection failed", ProviderNetworkError),
        ]:
            client = MagicMock()
            client.models.generate_content.side_effect = RuntimeError(message)
            with self.subTest(message=message), self.assertRaises(expected):
                GeminiProvider(make_settings(), client=client).generate_zone_report("prompt")

        for error, expected in [
            (MockSdkError(400, "INVALID_ARGUMENT", "model is not supported"), ProviderUnsupportedRequestError),
            (MockSdkError(404, "NOT_FOUND", "model not found"), ProviderUnsupportedRequestError),
            (MockSdkError(504, "DEADLINE_EXCEEDED", "Deadline expired before operation could complete."), ProviderTimeoutError),
            (MockSdkError(429, "RESOURCE_EXHAUSTED", "quota exceeded"), ProviderRateLimitError),
            (MockSdkError(500, "INTERNAL", "upstream failure"), ProviderUpstreamError),
        ]:
            with self.subTest(error=error):
                classified = _classify_provider_exception(error)
                self.assertIsInstance(classified, expected)
                self.assertEqual(classified.status_code, error.code)
                self.assertEqual(classified.provider_status, error.status)

        socket_error = OSError("[WinError 10013] socket access forbidden by permissions")
        self.assertIsInstance(_classify_provider_exception(socket_error), ProviderNetworkError)

    def test_provider_retries_only_transient_upstream_failures(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            MockSdkError(500, "INTERNAL", "Internal error encountered."),
            SimpleNamespace(text='{"schema_version":"1.0"}'),
        ]
        provider = GeminiProvider(make_settings(), client=client)
        with patch("ai.gemini_provider.time.sleep") as sleep:
            response = provider.generate_content_response("prompt")
        self.assertEqual(response.text, '{"schema_version":"1.0"}')
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once_with(0.5)

        client = MagicMock()
        client.models.generate_content.side_effect = [
            MockSdkError(504, "DEADLINE_EXCEEDED", "Deadline expired before operation could complete."),
            SimpleNamespace(text='{"schema_version":"1.0"}'),
        ]
        provider = GeminiProvider(make_settings(), client=client)
        with patch("ai.gemini_provider.time.sleep") as sleep:
            response = provider.generate_content_response("prompt")
        self.assertEqual(response.text, '{"schema_version":"1.0"}')
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once_with(0.5)

        client = MagicMock()
        client.models.generate_content.side_effect = MockSdkError(
            400, "INVALID_ARGUMENT", "invalid request"
        )
        provider = GeminiProvider(make_settings(), client=client)
        with patch("ai.gemini_provider.time.sleep") as sleep:
            with self.assertRaises(ProviderUnsupportedRequestError):
                provider.generate_content_response("prompt")
        client.models.generate_content.assert_called_once()
        sleep.assert_not_called()

        with self.assertRaises(ProviderMalformedResponseError):
            provider.generate_content_response("  ")

    def test_api_maps_provider_failures_and_redacts_logs(self):
        cases = [
            (ProviderAuthenticationError("auth", status_code=401), 502, "Gemini authentication or authorization failed"),
            (ProviderUnsupportedRequestError("unsupported", status_code=404), 502, "Gemini rejected the configured model or request"),
            (ProviderRateLimitError("quota", status_code=429), 429, "Gemini rate limit or quota reached"),
            (ProviderTimeoutError("timeout"), 504, "Gemini request timed out"),
            (ProviderNetworkError("network"), 502, "Gemini network request failed"),
            (ProviderUpstreamError("upstream", status_code=503), 502, "Gemini upstream service failed"),
            (ProviderMalformedResponseError("bad JSON"), 502, "Gemini returned malformed model output"),
        ]
        for error, expected_status, expected_detail in cases:
            analyzer = Stage1Analyzer(
                RaisingZoneProvider(error), schema_path=SCHEMA_PATH, batch_size=4
            )
            client = TestClient(create_app(make_settings(), stage1_analyzer=analyzer))
            with self.subTest(error=type(error).__name__):
                with self.assertLogs("agromind.api", level="ERROR") as captured:
                    response = client.post(
                        "/api/v1/analysis/zones",
                        json={"analysis_run_id": "error_mapping"},
                    )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.json(), {"detail": expected_detail})
                self.assertNotIn("test-key", "\n".join(captured.output))

    def test_api_endpoint_uses_pipeline_and_returns_traceability(self):
        provider = FakeZoneProvider()
        analyzer = Stage1Analyzer(provider, schema_path=SCHEMA_PATH, batch_size=4)
        client = TestClient(create_app(make_settings(), stage1_analyzer=analyzer))
        response = client.post(
            "/api/v1/analysis/zones",
            json={"analysis_run_id": "api_run", "batch_size": 5},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis_run_id"], "api_run")
        self.assertEqual(payload["total_batches"], 3)
        self.assertEqual(payload["batches"][0]["zone_ids"], ["Z01", "Z02", "Z03", "Z04", "Z05"])
        self.assertNotIn("scenario_label", response.text)

    def test_api_endpoint_reports_missing_key_safely(self):
        client = TestClient(create_app(make_settings(gemini_api_key=None)))
        response = client.post("/api/v1/analysis/zones", json={"analysis_run_id": "missing_key"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Gemini integration is not configured"})


if __name__ == "__main__":
    unittest.main()
