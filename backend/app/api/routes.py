from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.config import get_settings
from app.api.schemas import (
    DashboardSummaryResponse,
    FreshnessResponse,
    RecalculateResponse,
    SectorPerformanceResponse,
    SeriesResponse,
    YieldCurveResponse,
)
from app.data import database
from app.services import analytics, regime

router = APIRouter()


def get_db():
    with database.session() as conn:
        yield conn


def _parse_windows(windows: str) -> tuple[str, ...]:
    allowed = {"1d", "1w", "1m", "3m", "ytd", "1y"}
    parsed = tuple(item.strip().lower() for item in windows.split(",") if item.strip())
    invalid = [item for item in parsed if item not in allowed]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported windows: {', '.join(invalid)}")
    return parsed or ("1d", "1w", "1m", "3m", "ytd", "1y")


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    snapshot = database.load_latest_regime(conn, date_)
    if snapshot is None:
        snapshot = regime.classify_regime(conn, date_)
        database.save_regime_snapshot(conn, snapshot)
    blocks = analytics.dashboard_market_blocks(conn, date_)
    return {
        "as_of": snapshot["date"],
        "regime": snapshot,
        "major_indices": blocks["indices"],
        "sector_leaders": blocks["sector_leaders"],
        "sector_laggards": blocks["sector_laggards"],
        "rates_summary": blocks["rates"],
        "commodities_summary": blocks["commodities"],
        "volatility_summary": blocks["volatility"],
        "analyst_summary": snapshot["summary"],
        "data_freshness": data_freshness(conn),
    }


@router.get("/series/{symbol}", response_model=SeriesResponse)
def series(symbol: str, start: date | None = None, end: date | None = None, conn=Depends(get_db)):
    rows = analytics.price_series(conn, symbol.upper(), start, end)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No series data found for {symbol.upper()}")
    return {"symbol": symbol.upper(), "start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "data": rows}


@router.get("/sectors/performance", response_model=SectorPerformanceResponse)
def sectors_performance(windows: str = "1d,1w,1m,3m,ytd,1y", date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    parsed = _parse_windows(windows)
    return {"windows": parsed, "sectors": analytics.sector_performance(conn, parsed, date_)}


@router.get("/rates/yield-curve", response_model=YieldCurveResponse)
def rates_yield_curve(date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    return analytics.yield_curve(conn, date_)


@router.post("/regime/recalculate", response_model=RecalculateResponse)
def regime_recalculate(date_: Annotated[date | None, Query(alias="date")] = None, trailing_days: int = Query(260, ge=1, le=1500), conn=Depends(get_db)):
    try:
        return regime.recalculate_regimes(conn, date_, trailing_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/data/freshness", response_model=FreshnessResponse)
def data_freshness_endpoint(conn=Depends(get_db)):
    return data_freshness(conn)


@router.get("/export/sectors.csv")
def export_sectors_csv(windows: str = "1d,1w,1m,3m,ytd,1y", date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    parsed = _parse_windows(windows)
    rows = analytics.sector_performance(conn, parsed, date_)
    fieldnames = ["symbol"] + [f"return_{window}" for window in parsed] + [f"relative_to_spy_{window}" for window in parsed]
    flat_rows = [
        {
            "symbol": row["symbol"],
            **{f"return_{window}": row["returns"].get(window) for window in parsed},
            **{f"relative_to_spy_{window}": row["relative_to_spy"].get(window) for window in parsed},
        }
        for row in rows
    ]
    return _csv_response("sector_performance.csv", fieldnames, flat_rows)


@router.get("/export/series/{symbol}.csv")
def export_series_csv(symbol: str, start: date | None = None, end: date | None = None, conn=Depends(get_db)):
    rows = analytics.price_series(conn, symbol.upper(), start, end)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No series data found for {symbol.upper()}")
    preferred = ["date", "open", "high", "low", "close", "adjusted_close", "value", "daily_return", "volume", "source"]
    fieldnames = [field for field in preferred if any(field in row for row in rows)]
    return _csv_response(f"{symbol.upper()}_series.csv", fieldnames, rows)


def _csv_response(filename: str, fieldnames: list[str], rows: list[dict]) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def data_freshness(conn) -> dict:
    settings = get_settings()
    rows = conn.execute(
        """
        SELECT i.symbol, i.name, i.asset_class, i.source,
               MAX(COALESCE(p.date, m.date)) AS latest_date
        FROM instruments i
        LEFT JOIN market_prices p ON p.instrument_id = i.id
        LEFT JOIN macro_observations m ON m.instrument_id = i.id
        GROUP BY i.symbol, i.name, i.asset_class, i.source
        ORDER BY i.symbol
        """
    ).fetchall()
    latest_dates = [date.fromisoformat(row["latest_date"]) for row in rows if row["latest_date"]]
    overall_latest = max(latest_dates).isoformat() if latest_dates else None
    today = date.today()
    instruments = []
    source_latest: dict[str, date] = {}
    for row in rows:
        latest = date.fromisoformat(row["latest_date"]) if row["latest_date"] else None
        age_days = (today - latest).days if latest else None
        is_stale = age_days is None or age_days > settings.stale_after_days
        instruments.append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "asset_class": row["asset_class"],
                "source": row["source"],
                "latest_date": latest.isoformat() if latest else None,
                "age_days": age_days,
                "is_stale": is_stale,
            }
        )
        if latest and (row["source"] not in source_latest or latest > source_latest[row["source"]]):
            source_latest[row["source"]] = latest
    return {
        "overall_latest_date": overall_latest,
        "stale_after_days": settings.stale_after_days,
        "sources": [
            {"source": source, "latest_date": latest.isoformat(), "age_days": (today - latest).days}
            for source, latest in sorted(source_latest.items())
        ],
        "instruments": instruments,
    }
