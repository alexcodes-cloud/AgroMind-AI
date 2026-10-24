import json
import unittest
from unittest.mock import patch

from backend.services.weather_service import WeatherServiceError, fetch_weather_snapshot


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class WeatherServiceTests(unittest.TestCase):
    def test_normalizes_current_and_forecast_timestamps(self):
        response = {
            "latitude": 33.97,
            "longitude": -6.87,
            "current": {
                "time": "2026-10-24T10:00",
                "temperature_2m": 29,
                "relative_humidity_2m": 48,
                "wind_speed_10m": 12,
                "precipitation": 0,
            },
            "hourly": {
                "time": ["2026-10-24T10:00", "2026-10-24T11:00"],
                "temperature_2m": [29, 30],
                "relative_humidity_2m": [48, 47],
                "wind_speed_10m": [12, 13],
                "precipitation": [0, 0.2],
                "et0_fao_evapotranspiration": [None, 0.1],
            },
        }
        with patch("backend.services.weather_service.urlopen", return_value=FakeResponse(response)):
            snapshot = fetch_weather_snapshot("farm_001", 33.97, -6.87, forecast_hours=1)

        self.assertEqual(snapshot["current"]["valid_at"], "2026-10-24T10:00Z")
        self.assertEqual(snapshot["forecast"][0]["time"], "2026-10-24T11:00Z")
        self.assertEqual(snapshot["location"]["timezone"], "Africa/Casablanca")

    def test_rejects_invalid_coordinates_and_farm_id(self):
        with self.assertRaises(ValueError):
            fetch_weather_snapshot("", 33.97, -6.87)
        with self.assertRaises(ValueError):
            fetch_weather_snapshot("farm_001", 91, -6.87)
        with self.assertRaises(ValueError):
            fetch_weather_snapshot("farm_001", 33.97, "-6.87")

    def test_rejects_non_object_api_response(self):
        with patch("backend.services.weather_service.urlopen", return_value=FakeResponse([])):
            with self.assertRaises(WeatherServiceError):
                fetch_weather_snapshot("farm_001", 33.97, -6.87)


if __name__ == "__main__":
    unittest.main()
