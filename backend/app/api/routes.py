from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request

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
from app.services import analytics, regime, macro_data, live_quotes
from app.services.market_data import get_snapshot, populate_database, demo_enabled, delivery_metadata, DataUnavailable
from app.services.calendar import latest_completed_session, missed_sessions, market_status
from app.data.instruments import provenance

router = APIRouter()


def get_db(request: Request, cached_only: bool = False):
    # A fresh in-memory database cannot inherit synthetic rows from an old /tmp DB.
    with database.session(":memory:") as conn:
        database.init_schema(conn)
        if demo_enabled():
            from app.data.seed import seed_demo_data
            seed_demo_data(conn)
        else:
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    market_future = pool.submit(get_snapshot, cached_only=cached_only)
                    macro_future = pool.submit(macro_data.get_snapshot, cached_only=cached_only)
                    snapshot, mode = market_future.result()
                    macro, macro_delivery = macro_future.result()
            except DataUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            request.state.market_delivery = snapshot.get("_delivery", {})
            populate_database(conn, snapshot, mode)
            macro_data.populate_database(conn, macro, macro_delivery)
        yield conn


def _parse_windows(windows: str) -> tuple[str, ...]:
    allowed = {"1d", "1w", "1m", "3m", "ytd", "1y"}
    parsed = tuple(item.strip().lower() for item in windows.split(",") if item.strip())
    invalid = [item for item in parsed if item not in allowed]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unsupported windows: {', '.join(invalid)}")
    return parsed or ("1d", "1w", "1m", "3m", "ytd", "1y")


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    date_: Annotated[date | None, Query(alias="date")] = None,
    conn=Depends(get_db),
    range_: Annotated[Literal["1d", "1w", "1m", "3m", "ytd", "1y"], Query(alias="range")] = "1m",
):
    # Classify against current inputs on every request. Stored snapshots support
    # history/change notes, not an unversioned cache of potentially revised data.
    history = analytics.MarketHistory(conn)
    try:
        snapshot = regime.classify_regime(conn, date_, history=history)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    database.save_regime_snapshot(conn, snapshot)
    observed_date = date.fromisoformat(snapshot["date"])
    blocks = analytics.dashboard_market_blocks(history, observed_date)
    state = market_status()
    quotes, quote_delivery = live_quotes.get_quotes(cached_only=delivery_metadata(conn).get("refresh_pending", False)) if date_ is None else ({}, {"cache": "historical"})
    return {
        "market_status": state,
        "live_quotes": live_quotes.with_returns(quotes, history),
        "quote_delivery": quote_delivery,
        "as_of": snapshot["date"],
        "data_mode": delivery_metadata(conn)["mode"],
        "fetched_at": delivery_metadata(conn)["fetched_at"],
        "refresh_pending": delivery_metadata(conn).get("refresh_pending", False),
        "retry_after_seconds": delivery_metadata(conn).get("retry_after_seconds", 0),
        "fetch_ms": delivery_metadata(conn).get("fetch_ms", 0),
        "cache": delivery_metadata(conn).get("cache", "stale"),
        "fetch_diagnostics": {key: value for key, value in delivery_metadata(conn).items() if key not in {"mode", "fetched_at", "telemetry", "symbols"}},
        "currency_summary": analytics.instrument_snapshot(history, "DXY", observed_date),
        "regime": snapshot,
        "major_indices": blocks["indices"],
        "performance_series": analytics.indexed_performance(history, observed_date, range_),
        "historical_regimes": [dict(row) for row in conn.execute(
            "SELECT date, regime_label, risk_score, growth_score, inflation_score, rates_pressure_score "
            "FROM regime_snapshots WHERE date <= ? ORDER BY date", (snapshot["date"],)
        )],
        "sectors": blocks["sectors"],
        "sector_leaders": blocks["sector_leaders"],
        "sector_laggards": blocks["sector_laggards"],
        "rates_summary": blocks["rates"],
        "macro_summary": macro_data.summary(conn, history, observed_date),
        "macro_delivery": macro_data.delivery_metadata(conn),
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
    return {"data_mode": delivery_metadata(conn)["mode"], "fetched_at": delivery_metadata(conn)["fetched_at"], "symbol": symbol.upper(), "start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "data": rows}


@router.get("/sectors/performance", response_model=SectorPerformanceResponse)
def sectors_performance(windows: str = "1d,1w,1m,3m,ytd,1y", date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    parsed = _parse_windows(windows)
    return {"data_mode": delivery_metadata(conn)["mode"], "fetched_at": delivery_metadata(conn)["fetched_at"], "windows": parsed, "sectors": analytics.sector_performance(conn, parsed, date_)}


@router.get("/rates/yield-curve", response_model=YieldCurveResponse)
def rates_yield_curve(date_: Annotated[date | None, Query(alias="date")] = None, conn=Depends(get_db)):
    return {**analytics.yield_curve(conn, date_), "data_mode": delivery_metadata(conn)["mode"]}


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
    today = datetime.now(timezone.utc).date()
    expected = latest_completed_session()
    generated_at = datetime.now(timezone.utc).isoformat()
    instruments = []
    source_latest: dict[str, date] = {}
    for row in rows:
        latest = date.fromisoformat(row["latest_date"]) if row["latest_date"] else None
        age_days = (today - latest).days if latest else None
        missed = missed_sessions(latest, expected) if latest else None
        is_stale = missed is not None and missed > 0
        status = "stale" if is_stale else "fresh"
        macro_freshness = macro_data.freshness(row["symbol"], latest, today) if row["source"] == "fred" else {}
        instruments.append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "asset_class": row["asset_class"],
                "source": row["source"],
                "latest_date": latest.isoformat() if latest else None,
                "age_days": age_days,
                "is_stale": is_stale,
                "status": status if latest else "unavailable",
                "missing_sessions": missed,
                **provenance(row["symbol"]),
                "freshness_policy": "Stale if behind the latest completed NYSE session (official close).",
                **macro_freshness,
            }
        )
        if latest and (row["source"] not in source_latest or latest < source_latest[row["source"]]):
            source_latest[row["source"]] = latest
    return {
        "overall_latest_date": overall_latest,
        "generated_at": generated_at,
        "as_of_date": overall_latest,
        "expected_session_date": expected.isoformat(),
        "data_mode": delivery_metadata(conn)["mode"],
        "fetched_at": delivery_metadata(conn)["fetched_at"],
        "stale_after_days": settings.stale_after_days,
        "freshness_policy": "Instrument/source rows are stale when behind the latest completed NYSE session; weekends, US market holidays and early closes are respected. FRED macro uses separate daily/monthly publication grace windows, reported per instrument. Source status aggregates each instrument's cadence-aware status.",
        "sources": [
            {
                "source": source,
                "latest_date": latest.isoformat(),
                "age_days": (today - latest).days,
                "is_stale": any(r["is_stale"] for r in instruments if r["source"] == source),
                "status": "partial" if any(r["status"] == "unavailable" for r in instruments if r["source"] == source) else "stale" if any(r["is_stale"] for r in instruments if r["source"] == source) else "fresh",
            }
            for source, latest in sorted(source_latest.items())
        ],
        "instruments": instruments,
    }
