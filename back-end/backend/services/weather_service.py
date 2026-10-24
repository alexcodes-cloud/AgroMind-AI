"""Open-Meteo adapter. Uses only the Python standard library.

Raises WeatherServiceError on network/API failure; it never fabricates live data.
"""
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_URL = "https://api.open-meteo.com/v1/forecast"

class WeatherServiceError(RuntimeError):
    pass

def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_api_timestamp(value):
    """Normalize Open-Meteo's UTC timestamps to RFC 3339 form."""
    if not isinstance(value, str) or not value:
        return None
    if len(value) == 16 and value[10:11] == "T":
        return value + "Z"
    return value

def _number(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

def fetch_weather_snapshot(farm_id, latitude, longitude,
                           timezone_name="Africa/Casablanca",
                           timeout_seconds=10, forecast_hours=24):
    """Return a JSON-serializable object matching weather.schema.json."""
    if not isinstance(farm_id, str) or not farm_id.strip():
        raise ValueError("farm_id must be a non-empty string")
    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)) or not math.isfinite(latitude):
        raise ValueError("latitude must be a finite number")
    if isinstance(longitude, bool) or not isinstance(longitude, (int, float)) or not math.isfinite(longitude):
        raise ValueError("longitude must be a finite number")
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    if isinstance(forecast_hours, bool) or not isinstance(forecast_hours, int) or forecast_hours < 1:
        raise ValueError("forecast_hours must be >= 1")

    params = {
        "latitude": latitude, "longitude": longitude,
        "timezone": "UTC", "forecast_days": 3,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,et0_fao_evapotranspiration"
    }
    req = Request(BASE_URL + "?" + urlencode(params),
                  headers={"Accept": "application/json", "User-Agent": "AgroMindAI/1.0"})
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WeatherServiceError(f"Open-Meteo request failed: {exc}") from exc

    if not isinstance(raw, dict):
        raise WeatherServiceError("Open-Meteo returned a non-object JSON response")

    cur = raw.get("current") or {}
    hourly = raw.get("hourly") or {}
    if not isinstance(cur, dict) or not isinstance(hourly, dict):
        raise WeatherServiceError("Open-Meteo response has invalid current/hourly data")
    current = {
        "temperature_c": _number(cur.get("temperature_2m")),
        "relative_humidity_pct": _number(cur.get("relative_humidity_2m")),
        "wind_speed_kmh": _number(cur.get("wind_speed_10m")),
        "precipitation_mm": _number(cur.get("precipitation")),
        "et0_mm": None,
        "valid_at": _normalize_api_timestamp(cur.get("time"))
    }
    times = hourly.get("time") or []
    if not isinstance(times, list):
        raise WeatherServiceError("Open-Meteo response has invalid hourly time data")
    names = {
        "temperature_c": "temperature_2m",
        "relative_humidity_pct": "relative_humidity_2m",
        "wind_speed_kmh": "wind_speed_10m",
        "precipitation_mm": "precipitation",
        "et0_mm": "et0_fao_evapotranspiration"
    }
    start = times.index(cur["time"]) + 1 if cur.get("time") in times else 0
    forecast = []
    for i in range(start, min(start + forecast_hours, len(times))):
        item = {"time": _normalize_api_timestamp(times[i])}
        for out_name, source_name in names.items():
            values = hourly.get(source_name) or []
            item[out_name] = _number(values[i]) if i < len(values) else None
        forecast.append(item)

    return {
        "schema_version": "1.0", "farm_id": farm_id,
        "source": "Open-Meteo", "retrieved_at": _utc_now(),
        "location": {
            "latitude": float(raw.get("latitude", latitude)),
            "longitude": float(raw.get("longitude", longitude)),
            "timezone": timezone_name
        },
        "current": current, "forecast": forecast
    }
