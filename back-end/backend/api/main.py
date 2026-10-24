"""FastAPI application for the AgroMind Phase 1 backend foundation."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from backend.api.config import CONTRACTS_ROOT, Settings, load_settings
from backend.api.models import (
    DashboardAnalysisRequest,
    DashboardResponse,
    DashboardSummary,
    DashboardZone,
    ErrorResponse,
    FarmResponse,
    HealthResponse,
    FarmPlanAnalysisRequest,
    FarmPlanResponse,
    WeatherResponse,
    ZoneAnalysisRequest,
    ZoneAnalysisResponse,
)
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
    ProviderError,
)
from backend.services.deployment_assets import load_embedded_json, materialize_embedded_json
from ai.stage1_analyzer import Stage1AnalysisError, Stage1Analyzer
from ai.stage2_analyzer import Stage2AnalysisError, Stage2Analyzer


LOGGER = logging.getLogger("agromind.api")
_SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)(x-goog-api-key|api[-_ ]?key|authorization|bearer|token)(\s*[:=]\s*)([^\s,;]+)"
)


def _redact_log_text(value: object, settings: Settings) -> str:
    text = str(value)
    if settings.gemini_api_key:
        text = text.replace(settings.gemini_api_key, "[REDACTED]")
    return _SENSITIVE_LOG_PATTERN.sub(r"\1\2[REDACTED]", text)


def _log_provider_failure(
    exc: ProviderError,
    settings: Settings,
    *,
    stage: str = "stage1",
) -> None:
    # Keep the traceback and upstream status useful for operators while never
    # logging the configured key or the Stage 1 prompt/request body.
    LOGGER.error(
        "Gemini provider failure stage=%s type=%s status_code=%s provider_status=%s "
        "provider_message=%s\ntraceback=%s",
        stage,
        type(exc).__name__,
        exc.status_code,
        exc.provider_status or "-",
        _redact_log_text(exc.provider_message or str(exc), settings),
        _redact_log_text(traceback.format_exc(), settings),
    )


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        embedded_name = {"farm": "farm", "weather": "weather"}.get(label) if os.environ.get("VERCEL") == "1" else None
        if embedded_name:
            try:
                value = load_embedded_json(embedded_name)
            except (KeyError, OSError, json.JSONDecodeError):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"{label} data is unavailable",
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{label} data is unavailable",
            ) from exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} data is unavailable",
        )
    return value


def _farm_for_analysis(
    farm: dict[str, Any],
    zone_limit: int,
    record_limit: int = 0,
) -> dict[str, Any]:
    """Return a scoped farm copy for low-quota demo analysis runs.

    The public farm endpoint still exposes the complete fixture. This limit
    only reduces the zones and records sent to Stage 1 and Stage 2, preserving
    the source dataset while keeping live Gemini token usage predictable.
    """
    zones = farm.get("zones")
    if (
        zone_limit <= 0
        and record_limit <= 0
    ) or not isinstance(zones, list):
        return farm
    scoped_farm = deepcopy(farm)
    selected_zones = scoped_farm["zones"]
    if zone_limit > 0:
        selected_zones = selected_zones[:zone_limit]
    if record_limit > 0:
        for zone in selected_zones:
            if isinstance(zone, dict):
                for key in ("sensors", "drone_observations"):
                    records = zone.get(key)
                    if isinstance(records, list):
                        zone[key] = records[:record_limit]
    scoped_farm["zones"] = selected_zones
    LOGGER.info(
        "Limiting AI analysis to %s of %s farm zones and %s records per type",
        len(selected_zones),
        len(zones),
        record_limit if record_limit > 0 else "all",
    )
    return scoped_farm


def _build_dashboard_response(
    farm: dict[str, Any],
    analysis_run_id: str,
    stage1_result: Any,
    plan: Any,
) -> dict[str, Any]:
    zones = []
    for batch in stage1_result.batches:
        for assessment in batch.report.assessments:
            zones.append(
                DashboardZone(
                    zone_id=assessment.zone_id,
                    hydration_status=assessment.hydration.status,
                    hydration_risk=assessment.hydration.risk_level,
                    fertilization_status=assessment.fertilization.status,
                    fertilization_risk=assessment.fertilization.risk_level,
                )
            )
    attention_count = sum(
        1
        for zone in zones
        if zone.hydration_status != "normal"
        or zone.fertilization_status != "normal"
    )
    return DashboardResponse(
        schema_version="1.0",
        farm_id=farm["farm_id"],
        analysis_run_id=analysis_run_id,
        status="completed",
        summary=DashboardSummary(
            total_area_ha=sum(float(zone.get("area_ha", 0)) for zone in farm.get("zones", [])),
            zones_total=len(farm.get("zones", [])),
            zones_analyzed=len(zones),
            zones_needing_attention=attention_count,
        ),
        zones=zones,
        action_plan=plan.priorities,
    ).model_dump(mode="json")


def create_app(
    settings: Settings | None = None,
    *,
    stage1_analyzer: Stage1Analyzer | None = None,
    stage2_analyzer: Stage2Analyzer | None = None,
) -> FastAPI:
    """Create an application instance, allowing isolated test configuration."""
    resolved_settings = (settings or load_settings()).validate()
    app = FastAPI(
        title="AgroMind AI Backend",
        version="1.0.0",
        description="Backend for the AgroMind two-stage analysis pipeline.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", environment=resolved_settings.app_environment)

    @app.get(
        f"{resolved_settings.api_prefix}/farm",
        response_model=FarmResponse,
        responses={503: {"model": ErrorResponse}},
        tags=["farm"],
    )
    def get_farm() -> dict[str, Any]:
        farm = _load_json_object(resolved_settings.farm_data_path, "farm")
        # The endpoint only exposes the farm input. Hidden evaluation labels are
        # stored separately and are never loaded here.
        farm.pop("evaluation_labels", None)
        return farm

    @app.get(
        f"{resolved_settings.api_prefix}/weather",
        response_model=WeatherResponse,
        responses={503: {"model": ErrorResponse}},
        tags=["weather"],
    )
    def get_weather() -> dict[str, Any]:
        return _load_json_object(resolved_settings.weather_fixture_path, "weather")

    @app.post(
        f"{resolved_settings.api_prefix}/analysis/zones",
        response_model=ZoneAnalysisResponse,
        responses={
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
        tags=["analysis"],
    )
    def analyze_zones(request: ZoneAnalysisRequest | None = None) -> dict[str, Any]:
        farm = _load_json_object(resolved_settings.farm_data_path, "farm")
        analysis_farm = _farm_for_analysis(
            farm,
            resolved_settings.analysis_zone_limit,
            resolved_settings.analysis_record_limit,
        )
        weather = _load_json_object(resolved_settings.weather_fixture_path, "weather")
        analysis_run_id = (
            request.analysis_run_id
            if request and request.analysis_run_id
            else f"stage1_{uuid4().hex[:12]}"
        )
        batch_size = request.batch_size if request and request.batch_size else resolved_settings.batch_size

        try:
            analyzer = stage1_analyzer or Stage1Analyzer(
                GeminiProvider(resolved_settings),
                schema_path=materialize_embedded_json("zone_schema") if not (CONTRACTS_ROOT / "zone-report.schema.json").is_file() else CONTRACTS_ROOT / "zone-report.schema.json",
                batch_size=resolved_settings.batch_size,
                demo_mode=resolved_settings.demo_mode,
                demo_fallback=resolved_settings.demo_fallback,
            )
            result = analyzer.analyze(
                analysis_farm,
                weather,
                analysis_run_id=analysis_run_id,
                batch_size=batch_size,
            )
            return result.to_dict()
        except ProviderConfigurationError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini integration is not configured",
            ) from exc
        except ProviderAuthenticationError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini authentication or authorization failed",
            ) from exc
        except ProviderUnsupportedRequestError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini rejected the configured model or request",
            ) from exc
        except ProviderRateLimitError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Gemini rate limit or quota reached",
            ) from exc
        except ProviderTimeoutError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gemini request timed out",
            ) from exc
        except ProviderNetworkError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini network request failed",
            ) from exc
        except ProviderUpstreamError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini upstream service failed",
            ) from exc
        except ProviderMalformedResponseError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned malformed model output",
            ) from exc
        except ProviderError as exc:
            _log_provider_failure(exc, resolved_settings)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gemini provider request failed") from exc
        except Stage1AnalysisError as exc:
            LOGGER.error(
                "Stage 1 analysis failure type=%s message=%s\ntraceback=%s",
                type(exc).__name__,
                _redact_log_text(str(exc), resolved_settings),
                _redact_log_text(traceback.format_exc(), resolved_settings),
            )
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Stage 1 analysis failed") from exc

    @app.post(
        f"{resolved_settings.api_prefix}/analysis/plan",
        response_model=FarmPlanResponse,
        responses={
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
        tags=["analysis"],
    )
    def synthesize_plan(
        request: FarmPlanAnalysisRequest | None = None,
    ) -> dict[str, Any]:
        """Run validated Stage 1, then synthesize one validated farm plan."""
        farm = _load_json_object(resolved_settings.farm_data_path, "farm")
        analysis_farm = _farm_for_analysis(
            farm,
            resolved_settings.analysis_zone_limit,
            resolved_settings.analysis_record_limit,
        )
        weather = _load_json_object(resolved_settings.weather_fixture_path, "weather")
        analysis_run_id = (
            request.analysis_run_id
            if request and request.analysis_run_id
            else f"plan_{uuid4().hex[:12]}"
        )
        batch_size = request.batch_size if request and request.batch_size else resolved_settings.batch_size

        try:
            provider = GeminiProvider(resolved_settings)
            resolved_stage1 = stage1_analyzer or Stage1Analyzer(
                provider,
                schema_path=materialize_embedded_json("zone_schema") if not (CONTRACTS_ROOT / "zone-report.schema.json").is_file() else CONTRACTS_ROOT / "zone-report.schema.json",
                batch_size=resolved_settings.batch_size,
                demo_mode=resolved_settings.demo_mode,
                demo_fallback=resolved_settings.demo_fallback,
            )
            stage1_result = resolved_stage1.analyze(
                analysis_farm,
                weather,
                analysis_run_id=analysis_run_id,
                batch_size=batch_size,
            )
            resolved_stage2 = stage2_analyzer or Stage2Analyzer(
                provider,
                schema_path=materialize_embedded_json("plan_schema") if not (CONTRACTS_ROOT / "farm-plan.schema.json").is_file() else CONTRACTS_ROOT / "farm-plan.schema.json",
                demo_mode=resolved_settings.demo_mode,
                demo_fallback=resolved_settings.demo_fallback,
            )
            plan = resolved_stage2.synthesize(analysis_farm, weather, stage1_result)
            return plan.model_dump(mode="json")
        except ProviderConfigurationError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini integration is not configured",
            ) from exc
        except ProviderAuthenticationError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini authentication or authorization failed",
            ) from exc
        except ProviderUnsupportedRequestError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini rejected the configured model or request",
            ) from exc
        except ProviderRateLimitError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Gemini rate limit or quota reached",
            ) from exc
        except ProviderTimeoutError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gemini request timed out",
            ) from exc
        except ProviderNetworkError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini network request failed",
            ) from exc
        except ProviderUpstreamError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini upstream service failed",
            ) from exc
        except ProviderMalformedResponseError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned malformed model output",
            ) from exc
        except ProviderError as exc:
            _log_provider_failure(exc, resolved_settings, stage="stage2")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini provider request failed",
            ) from exc
        except (Stage1AnalysisError, Stage2AnalysisError) as exc:
            LOGGER.error(
                "Analysis failure type=%s message=%s\ntraceback=%s",
                type(exc).__name__,
                _redact_log_text(str(exc), resolved_settings),
                _redact_log_text(traceback.format_exc(), resolved_settings),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Farm-wide analysis failed",
            ) from exc

    @app.post(
        f"{resolved_settings.api_prefix}/dashboard",
        response_model=DashboardResponse,
        responses={
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
        tags=["dashboard"],
    )
    def build_dashboard(
        request: DashboardAnalysisRequest | None = None,
    ) -> dict[str, Any]:
        """Run both AI stages once and return the frontend dashboard contract."""
        farm = _load_json_object(resolved_settings.farm_data_path, "farm")
        analysis_farm = _farm_for_analysis(
            farm,
            resolved_settings.analysis_zone_limit,
            resolved_settings.analysis_record_limit,
        )
        weather = _load_json_object(resolved_settings.weather_fixture_path, "weather")
        analysis_run_id = (
            request.analysis_run_id
            if request and request.analysis_run_id
            else f"dashboard_{uuid4().hex[:12]}"
        )
        batch_size = request.batch_size if request and request.batch_size else resolved_settings.batch_size

        try:
            provider = GeminiProvider(resolved_settings)
            resolved_stage1 = Stage1Analyzer(
                provider,
                schema_path=materialize_embedded_json("zone_schema") if not (CONTRACTS_ROOT / "zone-report.schema.json").is_file() else CONTRACTS_ROOT / "zone-report.schema.json",
                batch_size=resolved_settings.batch_size,
                demo_mode=resolved_settings.demo_mode,
                demo_fallback=resolved_settings.demo_fallback,
            )
            stage1_result = resolved_stage1.analyze(
                analysis_farm,
                weather,
                analysis_run_id=analysis_run_id,
                batch_size=batch_size,
            )
            resolved_stage2 = Stage2Analyzer(
                provider,
                schema_path=materialize_embedded_json("plan_schema") if not (CONTRACTS_ROOT / "farm-plan.schema.json").is_file() else CONTRACTS_ROOT / "farm-plan.schema.json",
                demo_mode=resolved_settings.demo_mode,
                demo_fallback=resolved_settings.demo_fallback,
            )
            plan = resolved_stage2.synthesize(analysis_farm, weather, stage1_result)
            return _build_dashboard_response(farm, analysis_run_id, stage1_result, plan)
        except ProviderConfigurationError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini integration is not configured",
            ) from exc
        except ProviderAuthenticationError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini authentication or authorization failed") from exc
        except ProviderUnsupportedRequestError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini rejected the configured model or request") from exc
        except ProviderRateLimitError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=429, detail="Gemini rate limit or quota reached") from exc
        except ProviderTimeoutError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=504, detail="Gemini request timed out") from exc
        except ProviderNetworkError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini network request failed") from exc
        except ProviderUpstreamError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini upstream service failed") from exc
        except ProviderMalformedResponseError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini returned malformed model output") from exc
        except ProviderError as exc:
            _log_provider_failure(exc, resolved_settings, stage="dashboard")
            raise HTTPException(status_code=502, detail="Gemini provider request failed") from exc
        except (Stage1AnalysisError, Stage2AnalysisError) as exc:
            LOGGER.error(
                "Dashboard analysis failure type=%s message=%s\ntraceback=%s",
                type(exc).__name__,
                _redact_log_text(str(exc), resolved_settings),
                _redact_log_text(traceback.format_exc(), resolved_settings),
            )
            raise HTTPException(status_code=502, detail="Dashboard analysis failed") from exc

    return app


app = create_app()
