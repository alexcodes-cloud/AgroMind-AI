"""Pydantic response models for the stable Phase 1 endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ai.farm_plan import FarmPlan, FarmPriority
from ai.zone_report import ZoneReport


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str


class FarmLocation(BaseModel):
    latitude: float
    longitude: float
    timezone: str


class FarmResponse(BaseModel):
    schema_version: Literal["1.0"]
    farm_id: str
    farm_name: str
    location: FarmLocation
    zones: list[dict[str, Any]] = Field(min_length=1)
    crop_defaults: dict[str, Any] | None = None

    class Config:
        extra = "allow"


class WeatherResponse(BaseModel):
    schema_version: Literal["1.0"]
    farm_id: str
    source: str
    retrieved_at: str
    location: FarmLocation
    current: dict[str, Any] | None
    forecast: list[dict[str, Any]]

    class Config:
        extra = "allow"


class ErrorResponse(BaseModel):
    detail: str


class ZoneAnalysisRequest(BaseModel):
    analysis_run_id: str | None = Field(default=None, min_length=1, max_length=128)
    batch_size: int | None = Field(default=None, ge=1, le=32)


class Stage1BatchResponse(BaseModel):
    batch_id: str
    batch_index: int
    zone_ids: list[str]
    report: ZoneReport


class ZoneAnalysisResponse(BaseModel):
    schema_version: str
    farm_id: str
    analysis_run_id: str
    status: Literal["completed"]
    analysis_mode: Literal["gemini", "local_demo_fallback"]
    batch_size: int
    total_batches: int
    batches: list[Stage1BatchResponse]


class FarmPlanAnalysisRequest(BaseModel):
    analysis_run_id: str | None = Field(default=None, min_length=1, max_length=128)
    batch_size: int | None = Field(default=None, ge=1, le=32)


class FarmPlanResponse(FarmPlan):
    """Validated Stage 2 response returned by the plan endpoint."""


class DashboardAnalysisRequest(FarmPlanAnalysisRequest):
    """Request for one combined Stage 1 + Stage 2 dashboard run."""


class DashboardSummary(BaseModel):
    total_area_ha: float = Field(ge=0)
    zones_total: int = Field(ge=0)
    zones_analyzed: int = Field(ge=0)
    zones_needing_attention: int = Field(ge=0)


class DashboardZone(BaseModel):
    zone_id: str
    hydration_status: Literal["normal", "investigation_needed", "insufficient_evidence"]
    hydration_risk: Literal["low", "medium", "high", "unknown"]
    fertilization_status: Literal["normal", "investigation_needed", "insufficient_evidence"]
    fertilization_risk: Literal["low", "medium", "high", "unknown"]
    last_updated_at: str | None = None


class DashboardResponse(BaseModel):
    schema_version: Literal["1.0"]
    farm_id: str
    analysis_run_id: str
    status: Literal["processing", "completed", "partial", "failed"]
    summary: DashboardSummary
    zones: list[DashboardZone]
    action_plan: list[FarmPriority]
    error: str | None = None
