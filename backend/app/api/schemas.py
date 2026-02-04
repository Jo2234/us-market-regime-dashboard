from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SeriesResponse(BaseModel):
    symbol: str
    start: str | None
    end: str | None
    data: list[dict[str, Any]]


class SectorPerformanceResponse(BaseModel):
    windows: tuple[str, ...]
    sectors: list[dict[str, Any]]


class YieldCurveResponse(BaseModel):
    date: str | None
    maturities: list[dict[str, Any]]
    spreads: dict[str, float | None]


class FreshnessResponse(BaseModel):
    overall_latest_date: str | None
    stale_after_days: int
    sources: list[dict[str, Any]]
    instruments: list[dict[str, Any]]


class DashboardSummaryResponse(BaseModel):
    as_of: str
    regime: dict[str, Any]
    major_indices: list[dict[str, Any]]
    sector_leaders: list[dict[str, Any]]
    sector_laggards: list[dict[str, Any]]
    rates_summary: dict[str, Any]
    commodities_summary: list[dict[str, Any]]
    volatility_summary: dict[str, Any]
    analyst_summary: str
    data_freshness: FreshnessResponse


class RecalculateResponse(BaseModel):
    recalculated: int
    latest: dict[str, Any] | None
