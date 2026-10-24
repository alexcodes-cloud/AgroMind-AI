"""Environment-backed configuration for the Phase 1 API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent


def _first_existing_directory(candidates: tuple[Path, ...], fallback: Path) -> Path:
    return next((candidate for candidate in candidates if candidate.is_dir()), fallback)


def _first_existing_file(candidates: tuple[Path, ...], fallback: Path) -> Path:
    return next((candidate for candidate in candidates if candidate.is_file()), fallback)


CONTRACTS_ROOT = _first_existing_directory(
    (
        REPOSITORY_ROOT / "contracts",
        PACKAGE_ROOT / "contracts",
        Path.cwd() / "contracts",
    ),
    REPOSITORY_ROOT / "contracts",
)
FARM_DATA_DEFAULT = _first_existing_file(
    (
        REPOSITORY_ROOT / "data-set" / "synthetic_farm.json",
        PACKAGE_ROOT / "data" / "synthetic_farm.json",
        REPOSITORY_ROOT / "data" / "synthetic_farm.json",
        Path.cwd() / "data" / "synthetic_farm.json",
    ),
    REPOSITORY_ROOT / "data-set" / "synthetic_farm.json",
)
WEATHER_FIXTURE_DEFAULT = _first_existing_file(
    (
        CONTRACTS_ROOT / "example-weather.json",
        REPOSITORY_ROOT / "contracts" / "example-weather.json",
        Path.cwd() / "contracts" / "example-weather.json",
    ),
    CONTRACTS_ROOT / "example-weather.json",
)
ENV_FILE_CANDIDATES = (
    REPOSITORY_ROOT / ".env",
    PACKAGE_ROOT / ".env",
    PACKAGE_ROOT / "backend" / ".env",
)


class ConfigurationError(ValueError):
    """Raised when an environment value cannot safely configure the API."""


def _path_from_env(value: str, default: Path) -> Path:
    path = Path(value) if value else default
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _environment_values() -> dict[str, str]:
    """Read local env files with explicit precedence and no global mutation.

    The repository-root file is canonical. Package and legacy backend files are
    fallback locations so existing local setups continue to work. Process
    environment variables always win over every file.
    """
    values: dict[str, str] = {}
    for path in reversed(ENV_FILE_CANDIDATES):
        if path.is_file():
            for key, value in dotenv_values(path).items():
                if key and value is not None:
                    values[key] = value
    values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


@dataclass(frozen=True)
class Settings:
    app_environment: str
    api_prefix: str
    gemini_api_key: str | None
    gemini_model: str
    gemini_timeout_seconds: float
    gemini_structured_output: bool
    gemini_max_output_tokens: int
    gemini_thinking_level: str
    demo_mode: bool
    demo_fallback: bool
    batch_size: int
    open_meteo_base_url: str
    open_meteo_timeout_seconds: float
    farm_data_path: Path
    weather_fixture_path: Path
    analysis_zone_limit: int = 0
    analysis_record_limit: int = 0
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "https://agromind-ai-dashboard.vercel.app",
    )

    def validate(self) -> "Settings":
        if not self.app_environment.strip():
            raise ConfigurationError("AGROMIND_ENV must not be empty")
        if not self.api_prefix.startswith("/"):
            raise ConfigurationError("AGROMIND_API_PREFIX must start with '/'")
        if self.api_prefix != "/" and self.api_prefix.endswith("/"):
            raise ConfigurationError("AGROMIND_API_PREFIX must not end with '/'")
        if not self.gemini_model.strip():
            raise ConfigurationError("GEMINI_MODEL must not be empty")
        if self.gemini_timeout_seconds <= 0:
            raise ConfigurationError("GEMINI_TIMEOUT_SECONDS must be greater than zero")
        if self.gemini_max_output_tokens < 256:
            raise ConfigurationError("GEMINI_MAX_OUTPUT_TOKENS must be at least 256")
        if self.gemini_thinking_level.lower() not in {"minimal", "high"}:
            raise ConfigurationError("GEMINI_THINKING_LEVEL must be 'minimal' or 'high'")
        if self.batch_size < 1:
            raise ConfigurationError("AGROMIND_BATCH_SIZE must be greater than zero")
        if self.analysis_zone_limit < 0:
            raise ConfigurationError("AGROMIND_ANALYSIS_ZONE_LIMIT must be zero or greater")
        if self.analysis_record_limit < 0:
            raise ConfigurationError("AGROMIND_ANALYSIS_RECORD_LIMIT must be zero or greater")
        if not self.open_meteo_base_url.startswith(("http://", "https://")):
            raise ConfigurationError("OPEN_METEO_BASE_URL must be an HTTP(S) URL")
        if self.open_meteo_timeout_seconds <= 0:
            raise ConfigurationError("OPEN_METEO_TIMEOUT_SECONDS must be greater than zero")
        return self


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load and validate settings without exposing secrets in returned responses."""
    values = dict(environ) if environ is not None else _environment_values()

    def parse_float(name: str, default: str) -> float:
        try:
            return float(values.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{name} must be a number") from exc

    def parse_int(name: str, default: str) -> int:
        try:
            return int(values.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"{name} must be an integer") from exc

    def parse_bool(name: str, default: str) -> bool:
        raw = str(values.get(name, default)).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(f"{name} must be true or false")

    try:
        gemini_timeout_seconds = parse_float("GEMINI_TIMEOUT_SECONDS", "30")
        gemini_max_output_tokens = parse_int("GEMINI_MAX_OUTPUT_TOKENS", "4096")
        gemini_thinking_level = str(values.get("GEMINI_THINKING_LEVEL", "minimal")).strip().lower()
        open_meteo_timeout_seconds = parse_float("OPEN_METEO_TIMEOUT_SECONDS", "10")
        batch_size = parse_int("AGROMIND_BATCH_SIZE", "4")
        analysis_zone_limit = parse_int("AGROMIND_ANALYSIS_ZONE_LIMIT", "0")
        analysis_record_limit = parse_int("AGROMIND_ANALYSIS_RECORD_LIMIT", "0")
        structured_output = parse_bool("GEMINI_STRUCTURED_OUTPUT", "false")
        demo_mode = parse_bool("AGROMIND_DEMO_MODE", "false")
        demo_fallback = parse_bool("AGROMIND_DEMO_FALLBACK", "false")
    except ConfigurationError:
        raise

    settings = Settings(
        app_environment=values.get("AGROMIND_ENV", "local"),
        api_prefix=values.get("AGROMIND_API_PREFIX", "/api/v1").rstrip("/") or "/",
        gemini_api_key=values.get("GEMINI_API_KEY") or None,
        gemini_model=values.get("GEMINI_MODEL", "gemma-4-26b-a4b-it"),
        gemini_timeout_seconds=gemini_timeout_seconds,
        gemini_structured_output=structured_output,
        gemini_max_output_tokens=gemini_max_output_tokens,
        gemini_thinking_level=gemini_thinking_level,
        demo_mode=demo_mode,
        demo_fallback=demo_fallback,
        batch_size=batch_size,
        open_meteo_base_url=values.get(
            "OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast"
        ),
        open_meteo_timeout_seconds=open_meteo_timeout_seconds,
        farm_data_path=_path_from_env(
            values.get("AGROMIND_FARM_DATA_PATH", ""),
            FARM_DATA_DEFAULT,
        ),
        weather_fixture_path=_path_from_env(
            values.get("AGROMIND_WEATHER_FIXTURE_PATH", ""),
            WEATHER_FIXTURE_DEFAULT,
        ),
        analysis_zone_limit=analysis_zone_limit,
        analysis_record_limit=analysis_record_limit,
        cors_origins=tuple(
            origin.strip()
            for origin in values.get(
                "AGROMIND_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,https://agromind-ai-dashboard.vercel.app",
            ).split(",")
            if origin.strip()
        ),
    )
    return settings.validate()
