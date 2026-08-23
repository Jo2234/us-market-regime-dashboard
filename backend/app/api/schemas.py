from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SeriesResponse(BaseModel):
    data_mode: str | None = None
    fetched_at: str | None = None
    symbol: str
    start: str | None
    end: str | None
    data: list[dict[str, Any]]


class SectorPerformanceResponse(BaseModel):
    data_mode: str | None = None
    fetched_at: str | None = None
    windows: tuple[str, ...]
    sectors: list[dict[str, Any]]


class YieldCurveResponse(BaseModel):
    data_mode: str | None = None
    spread_metadata: dict[str, Any] = {}
    units: str = "percent"
    date: str | None
    maturities: list[dict[str, Any]]
    spreads: dict[str, float | None]


class FreshnessResponse(BaseModel):
    expected_session_date: str | None = None
    data_mode: str | None = None
    fetched_at: str | None = None
    overall_latest_date: str | None
    generated_at: str | None = None
    as_of_date: str | None = None
    stale_after_days: int
    freshness_policy: str | None = None
    sources: list[dict[str, Any]]
    instruments: list[dict[str, Any]]


class DashboardSummaryResponse(BaseModel):
    fetch_ms: float = 0
    cache: str = "stale"
    fetch_diagnostics: dict[str, Any] = {}
    data_mode: str | None = None
    fetched_at: str | None = None
    currency_summary: dict[str, Any] = {}
    as_of: str
    regime: dict[str, Any]
    major_indices: list[dict[str, Any]]
    performance_series: list[dict[str, Any]]
    historical_regimes: list[dict[str, Any]]
    sectors: list[dict[str, Any]]
    sector_leaders: list[dict[str, Any]]
    sector_laggards: list[dict[str, Any]]
    rates_summary: dict[str, Any]
    macro_summary: dict[str, Any]
    commodities_summary: list[dict[str, Any]]
    volatility_summary: dict[str, Any]
    analyst_summary: str
    data_freshness: FreshnessResponse


class RecalculateResponse(BaseModel):
    recalculated: int
    latest: dict[str, Any] | None
