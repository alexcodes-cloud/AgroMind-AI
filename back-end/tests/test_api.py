import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.config import ConfigurationError, Settings, load_settings
from backend.api.main import create_app


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
FARM_PATH = REPOSITORY_ROOT / "data-set" / "synthetic_farm.json"
WEATHER_PATH = REPOSITORY_ROOT / "contracts" / "example-weather.json"


def make_settings(**overrides):
    values = {
        "app_environment": "test",
        "api_prefix": "/api/v1",
        "gemini_api_key": None,
        "gemini_model": "test-model",
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


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(make_settings()))

    def test_health_does_not_require_external_services(self):
        with patch("backend.api.main._load_json_object", side_effect=AssertionError("not called")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "environment": "test"})

    def test_sample_farm_endpoint_returns_data_without_labels(self):
        response = self.client.get("/api/v1/farm")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["farm_id"], "farm_001")
        self.assertGreater(len(payload["zones"]), 0)
        self.assertNotIn("evaluation_labels", response.text)
        self.assertNotIn("scenario_label", response.text)

    def test_weather_endpoint_returns_fixture(self):
        response = self.client.get("/api/v1/weather")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "Open-Meteo")

    def test_vercel_frontend_origin_is_allowed_by_cors(self):
        response = self.client.options(
            "/api/v1/farm",
            headers={
                "Origin": "https://agromind-ai-dashboard.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://agromind-ai-dashboard.vercel.app",
        )

    def test_weather_endpoint_returns_safe_unavailable_error(self):
        missing = REPOSITORY_ROOT / "does-not-exist-weather.json"
        client = TestClient(create_app(make_settings(weather_fixture_path=missing)))
        response = client.get("/api/v1/weather")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "weather data is unavailable"})

    def test_invalid_environment_configuration_is_rejected(self):
        environment = dict(os.environ)
        environment["AGROMIND_API_PREFIX"] = "api/v1"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)

    def test_invalid_analysis_zone_limit_is_rejected(self):
        environment = dict(os.environ)
        environment["AGROMIND_ANALYSIS_ZONE_LIMIT"] = "-1"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)

    def test_invalid_analysis_record_limit_is_rejected(self):
        environment = dict(os.environ)
        environment["AGROMIND_ANALYSIS_RECORD_LIMIT"] = "-1"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)

    def test_dotenv_precedence_is_deterministic_and_does_not_mutate_process_env(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            root_env = temporary_path / "root.env"
            package_env = temporary_path / "package.env"
            root_env.write_text(
                "GEMINI_API_KEY=root-file-key\nGEMINI_MODEL=root-file-model\n",
                encoding="utf-8",
            )
            package_env.write_text(
                "GEMINI_API_KEY=package-file-key\nGEMINI_MODEL=package-file-model\n",
                encoding="utf-8",
            )

            with patch("backend.api.config.ENV_FILE_CANDIDATES", (root_env, package_env)):
                with patch.dict(os.environ, {}, clear=True):
                    settings = load_settings()
                    self.assertEqual(settings.gemini_api_key, "root-file-key")
                    self.assertEqual(settings.gemini_model, "root-file-model")
                    self.assertNotIn("GEMINI_API_KEY", os.environ)

                with patch.dict(os.environ, {"GEMINI_API_KEY": "process-key"}, clear=True):
                    settings = load_settings()
                    self.assertEqual(settings.gemini_api_key, "process-key")
                    self.assertEqual(settings.gemini_model, "root-file-model")

            with patch("backend.api.config.ENV_FILE_CANDIDATES", (temporary_path / "missing.env", package_env)):
                with patch.dict(os.environ, {}, clear=True):
                    settings = load_settings()
                    self.assertEqual(settings.gemini_api_key, "package-file-key")

        environment = dict(os.environ)
        environment["GEMINI_TIMEOUT_SECONDS"] = "not-a-number"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)

        environment = dict(os.environ)
        environment["AGROMIND_BATCH_SIZE"] = "0"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)

        environment = dict(os.environ)
        environment["GEMINI_THINKING_LEVEL"] = "invalid"
        with self.assertRaises(ConfigurationError):
            load_settings(environment)


if __name__ == "__main__":
    unittest.main()
