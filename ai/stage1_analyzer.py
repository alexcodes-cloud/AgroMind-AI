"""Stage 1 batch orchestration, kept independent from HTTP routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from backend.services.batch_builder import BatchBuildError, build_stage1_batches
from ai.demo_zone_adapter import adapt_demo_zone_report
from ai.local_demo_fallback import build_local_zone_report
from ai.gemini_provider import (
    ProviderError,
    ProviderUpstreamError,
)
from ai.stage1_prompt import PromptSafetyError, build_stage1_prompt
from ai.zone_report import ZoneReport, ZoneReportValidationError, validate_zone_report


MAX_VALIDATION_RETRIES = 2
MAX_BATCH_PROVIDER_RETRIES = 1
LOGGER = logging.getLogger("agromind.stage1")


class ZoneReportProvider(Protocol):
    def generate_zone_report(self, prompt: str) -> dict[str, Any]: ...


class Stage1AnalysisError(RuntimeError):
    """Raised when a Stage 1 run cannot complete safely."""


class Stage1BatchError(Stage1AnalysisError):
    def __init__(self, batch_id: str, message: str):
        super().__init__(message)
        self.batch_id = batch_id


@dataclass(frozen=True)
class Stage1BatchResult:
    batch_id: str
    batch_index: int
    zone_ids: list[str]
    report: ZoneReport


@dataclass(frozen=True)
class Stage1RunResult:
    schema_version: str
    farm_id: str
    analysis_run_id: str
    status: str
    batch_size: int
    total_batches: int
    batches: list[Stage1BatchResult]
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "farm_id": self.farm_id,
            "analysis_run_id": self.analysis_run_id,
            "status": self.status,
            "analysis_mode": "local_demo_fallback" if self.fallback_used else "gemini",
            "batch_size": self.batch_size,
            "total_batches": self.total_batches,
            "batches": [
                {
                    "batch_id": item.batch_id,
                    "batch_index": item.batch_index,
                    "zone_ids": item.zone_ids,
                    "report": item.report.model_dump(mode="json"),
                }
                for item in self.batches
            ],
        }


class Stage1Analyzer:
    def __init__(
        self,
        provider: ZoneReportProvider,
        *,
        schema_path: Path,
        batch_size: int = 4,
        demo_mode: bool = False,
        demo_fallback: bool = False,
    ):
        self.provider = provider
        self.schema_path = schema_path
        self.batch_size = batch_size
        self.demo_mode = demo_mode
        self.demo_fallback = demo_fallback

    def _generate_zone_report(
        self,
        batch: dict[str, Any],
        prompt: str,
        batch_id: str,
    ) -> tuple[dict[str, Any], bool]:
        if self.demo_fallback:
            LOGGER.warning(
                "Using explicit local demo fallback for Stage 1 batch batch_id=%s",
                batch_id,
            )
            return build_local_zone_report(batch), True

        for provider_attempt in range(MAX_BATCH_PROVIDER_RETRIES + 1):
            try:
                return self.provider.generate_zone_report(prompt), False
            except ProviderUpstreamError as exc:
                # The provider already retries deadline errors. A second
                # orchestration-level deadline retry would multiply a
                # 120-second wait, so only retry a completed 5xx response.
                if (
                    exc.status_code == 504
                    or exc.provider_status == "DEADLINE_EXCEEDED"
                ):
                    raise
                if provider_attempt >= MAX_BATCH_PROVIDER_RETRIES:
                    raise
                LOGGER.warning(
                    "Retrying Stage 1 batch after transient provider failure "
                    "batch_id=%s attempt=%s/%s status_code=%s provider_status=%s",
                    batch_id,
                    provider_attempt + 1,
                    MAX_BATCH_PROVIDER_RETRIES,
                    exc.status_code,
                    exc.provider_status or "-",
                )
            except ProviderError:
                raise
        raise Stage1AnalysisError(f"could not generate {batch_id}")

    def analyze(
        self,
        farm: dict[str, Any],
        weather: dict[str, Any] | None,
        *,
        analysis_run_id: str,
        batch_size: int | None = None,
    ) -> Stage1RunResult:
        resolved_batch_size = self.batch_size if batch_size is None else batch_size
        try:
            batches = build_stage1_batches(
                farm,
                weather,
                batch_size=resolved_batch_size,
                analysis_run_id=analysis_run_id,
            )
        except BatchBuildError as exc:
            raise Stage1AnalysisError(f"could not build Stage 1 batches: {exc}") from exc

        results: list[Stage1BatchResult] = []
        fallback_used = False
        for batch in batches:
            batch_id = str(batch["batch_id"])
            validation_feedback: str | None = None
            try:
                for attempt in range(MAX_VALIDATION_RETRIES + 1):
                    prompt = build_stage1_prompt(
                        batch,
                        validation_feedback=validation_feedback,
                    )
                    raw_report, used_fallback = self._generate_zone_report(
                        batch, prompt, batch_id
                    )
                    fallback_used = fallback_used or used_fallback
                    if self.demo_mode:
                        raw_report = adapt_demo_zone_report(raw_report, batch)
                    try:
                        report = validate_zone_report(
                            raw_report,
                            batch,
                            schema_path=self.schema_path,
                        )
                    except ZoneReportValidationError as exc:
                        if attempt >= MAX_VALIDATION_RETRIES:
                            raise
                        validation_feedback = str(exc)
                    else:
                        break
                else:  # pragma: no cover - loop always returns or raises
                    raise Stage1AnalysisError(f"could not validate {batch_id}")
            except (PromptSafetyError, ZoneReportValidationError) as exc:
                raise Stage1BatchError(
                    batch_id,
                    f"Stage 1 output rejected for {batch_id}: {exc}",
                ) from exc
            except ProviderError:
                raise
            except Exception as exc:
                # Provider-specific errors remain available as the cause for
                # endpoint classification, but are never returned verbatim.
                if isinstance(exc, Stage1AnalysisError):
                    raise
                raise Stage1BatchError(batch_id, f"Stage 1 provider failed for {batch_id}") from exc

            results.append(
                Stage1BatchResult(
                    batch_id=batch_id,
                    batch_index=batch["batch_index"],
                    zone_ids=[zone["zone_id"] for zone in batch["zones"]],
                    report=report,
                )
            )

        return Stage1RunResult(
            schema_version="1.0",
            farm_id=farm["farm_id"],
            analysis_run_id=analysis_run_id,
            status="completed",
            batch_size=resolved_batch_size,
            total_batches=len(results),
            batches=results,
            fallback_used=fallback_used,
        )
