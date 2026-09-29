import asyncio
import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.ingestion.yahoo import normalize_chart, fetch_chart, YahooUnavailable
from app.services import analytics, market_data
from app.services.calendar import latest_completed_session, missed_sessions
from app.data.instruments import YAHOO_TICKERS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def yahoo_snapshot():
    return {"version": 1, "fetched_at": "2026-09-29T13:00:00+00:00", "series": {
        symbol: {"source": "yahoo_finance", "yahoo_ticker": ticker,
                 "bars": normalize_chart(symbol, json.loads((FIXTURES / f"{symbol}.json").read_text()), date(2026, 9, 28))}
        for symbol, ticker in YAHOO_TICKERS.items()
    }}


@pytest.fixture()
def clear_cache(monkeypatch):
    for name, value in [("_cached", None), ("_last_good", None), ("_expires", 0)]:
        monkeypatch.setattr(market_data, name, value)
    monkeypatch.delenv("MARKET_REGIME_SNAPSHOT_ONLY", raising=False)
    monkeypatch.delenv("MARKET_REGIME_DEMO_MODE", raising=False)


def test_recorded_bars_raw_price_adjusted_returns_and_provenance(empty_conn, yahoo_snapshot):
    market_data.validate_snapshot(yahoo_snapshot)
    market_data.populate_database(empty_conn, yahoo_snapshot, "live")
    snapshot = analytics.instrument_snapshot(empty_conn, "SPY")
    assert snapshot["price"] == pytest.approx(765.61, abs=0.0001)
    assert snapshot["date"] == "2026-09-28"
    bars = yahoo_snapshot["series"]["SPY"]["bars"]
    base = next(b for b in bars if b["date"] == "2026-08-28")
    assert snapshot["returns"]["1m"] == pytest.approx(bars[-1]["adjusted_close"] / base["adjusted_close"] - 1, abs=0.0000005)
    older = analytics.instrument_snapshot(empty_conn, "SPY", date(2025, 1, 15))
    assert older["price"] != older["adjusted_close"]
    for symbol in YAHOO_TICKERS:
        row = analytics.price_series(empty_conn, symbol)[-1]
        assert row["source"] == "yahoo_finance"
        assert row["yahoo_ticker"] == YAHOO_TICKERS[symbol]
        assert row["observation_date"] == "2026-09-28"
    curve = analytics.yield_curve(empty_conn)
    assert len(curve["maturities"]) == 5
    assert next(r for r in curve["maturities"] if r["symbol"] == "DGS10")["value"] == 5.24
    assert curve["spreads"]["10y_2y"] == 0.74
    assert curve["spread_metadata"]["10y_2y"]["is_cash_treasury_spread"] is False


def test_parser_skips_incomplete_session_nulls_and_checks_ticker():
    payload = json.loads((FIXTURES / "SPY.json").read_text())
    original = normalize_chart("SPY", payload, date(2026, 9, 28))
    assert original[-1]["date"] == "2026-09-28"
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1] = None
    assert len(normalize_chart("SPY", payload, date(2026, 9, 28))) == len(original) - 1
    with pytest.raises(YahooUnavailable):
        normalize_chart("QQQ", payload, date(2026, 9, 28))
    payload["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][0] = None
    with pytest.raises(YahooUnavailable, match="adjusted"):
        normalize_chart("SPY", payload, date(2026, 9, 28))


def test_holidays_weekends_early_closes_and_intraday():
    assert latest_completed_session(datetime(2026, 9, 7, 22, tzinfo=timezone.utc)) == date(2026, 9, 4)  # Labor Day
    assert latest_completed_session(datetime(2026, 9, 6, 22, tzinfo=timezone.utc)) == date(2026, 9, 4)
    assert latest_completed_session(datetime(2026, 9, 29, 18, tzinfo=timezone.utc)) == date(2026, 9, 28)
    assert latest_completed_session(datetime(2026, 11, 27, 18, 31, tzinfo=timezone.utc)) == date(2026, 11, 27)  # 13:00 EST close
    assert latest_completed_session(datetime(2026, 11, 27, 18, 10, tzinfo=timezone.utc)) == date(2026, 11, 25)
    assert missed_sessions(date(2026, 9, 4), date(2026, 9, 8)) == 1


@pytest.mark.parametrize("window,dates,expected", [
    ("1w", ["2026-08-21", "2026-08-28", "2026-09-04"], 0.1),
    ("1m", ["2026-02-27", "2026-03-02", "2026-03-31"], 0.21),
    ("3m", ["2026-01-30", "2026-02-02", "2026-04-30"], 0.21),
    ("1y", ["2023-02-28", "2023-03-01", "2024-02-29"], 0.21),
    ("ytd", ["2025-12-31", "2026-01-02", "2026-01-05"], 0.21),
])
def test_calendar_windows(window, dates, expected):
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "value": [100., 110., 121.]})
    assert analytics.period_return(frame, window) == pytest.approx(expected)


def test_live_cache_fallback_and_production_demo_guard(monkeypatch, tmp_path, clear_cache, yahoo_snapshot):
    monkeypatch.setattr(market_data, "SNAPSHOT_PATH", tmp_path / "absent.json")
    calls = []
    async def fetch():
        calls.append(True)
        return copy.deepcopy(yahoo_snapshot)
    monkeypatch.setattr(market_data, "fetch_snapshot", fetch)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("MARKET_REGIME_DEMO_MODE", "1")
    from app.main import create_app
    with TestClient(create_app()) as client:
        for _ in range(2):
            response = client.get("/api/dashboard/summary")
            assert response.status_code == 200
            assert response.json()["data_mode"] == "live"
            assert "demo_seed" not in response.text
            assert "s-maxage=900" in response.headers["cache-control"]
        assert len(calls) == 1
        async def fail():
            raise YahooUnavailable("simulated")
        monkeypatch.setattr(market_data, "fetch_snapshot", fail)
        monkeypatch.setattr(market_data, "_expires", 0)
        response = client.get("/api/dashboard/summary")
        assert response.json()["data_mode"] == "snapshot"
        assert response.json()["as_of"] == "2026-09-28"
        assert "demo_seed" not in response.text


def test_kill_flag_uses_file_then_503_without_snapshot(monkeypatch, tmp_path, clear_cache):
    monkeypatch.setenv("MARKET_REGIME_FORCE_YAHOO_FAILURE", "1")
    from app.main import create_app
    with TestClient(create_app()) as client:
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 200
        assert response.json()["data_mode"] == "snapshot"
        assert "demo_seed" not in response.text
        monkeypatch.setattr(market_data, "_cached", None)
        monkeypatch.setattr(market_data, "_expires", 0)
        monkeypatch.setattr(market_data, "SNAPSHOT_PATH", tmp_path / "missing.json")
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 503
        assert "Live data unavailable" in response.text
        assert response.headers["cache-control"] == "no-store"


def test_retries_rate_limit_with_mock_transport():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json={"chart": {}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await fetch_chart(client, "SPY")
    assert asyncio.run(run()) == {"chart": {}}
    assert len(calls) == 3


def test_snapshot_rejects_synthetic_and_short_history(yahoo_snapshot):
    yahoo_snapshot["series"]["SPY"]["source"] = "demo_seed"
    with pytest.raises(ValueError, match="provenance"):
        market_data.validate_snapshot(yahoo_snapshot)


def test_standard_library_analytics_match_recorded_regression(empty_conn, yahoo_snapshot):
    from app.services import regime
    market_data.populate_database(empty_conn, yahoo_snapshot, "live")
    history = analytics.MarketHistory(empty_conn)
    expected = json.loads((FIXTURES / "analytics_regression.json").read_text())
    for day, reference in expected.items():
        observed = date.fromisoformat(day)
        actual = {"blocks": analytics.dashboard_market_blocks(history, observed),
                  "regime": regime.classify_regime(empty_conn, observed, history=history),
                  "charts": {w: analytics.indexed_performance(history, observed, w) for w in ("1d", "1w", "1m", "3m", "ytd", "1y")}}
        assert actual == reference


def test_bootstrap_never_fetches_or_waits_for_refresh(monkeypatch, clear_cache):
    def forbidden():
        raise AssertionError("Bootstrap must not contact Yahoo")
    monkeypatch.setattr(market_data, "fetch_snapshot", forbidden)
    market_data._lock.acquire()
    try:
        snapshot, mode = market_data.get_snapshot(cached_only=True)
    finally:
        market_data._lock.release()
    assert mode == "snapshot"
    assert snapshot["_delivery"]["refresh_pending"]
    assert all(row["source"] == "yahoo_finance" for row in snapshot["series"].values())


def test_concurrent_visitors_share_one_refresh(monkeypatch, clear_cache, yahoo_snapshot):
    from concurrent.futures import ThreadPoolExecutor
    calls = []
    async def fetch():
        calls.append(1)
        await asyncio.sleep(.02)
        return copy.deepcopy(yahoo_snapshot)
    monkeypatch.setattr(market_data, "fetch_snapshot", fetch)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: market_data.get_snapshot(), range(8)))
    assert len(calls) == 1
    assert [item[0]["_delivery"]["cache"] for item in results].count("miss") == 1


def test_rate_limit_cooldown_and_failure_telemetry(monkeypatch, clear_cache):
    import time
    calls = []
    async def fail():
        calls.append(1)
        raise YahooUnavailable("Rate limited", {"fetch_ms": 42, "http_429": 3, "http_401": 0, "retries": 2})
    monkeypatch.setattr(market_data, "fetch_snapshot", fail)
    first, mode = market_data.get_snapshot()
    assert mode == "snapshot"
    assert first["_delivery"]["fetch_ms"] == 42
    assert first["_telemetry"]["http_429"] == 3
    for _ in range(5):
        subsequent, mode = market_data.get_snapshot()
        assert subsequent["_delivery"]["cache"] == "stale"
        assert subsequent["_delivery"]["fetch_ms"] == 0
    assert len(calls) == 1
    assert market_data._expires - time.monotonic() > 890


def test_failed_refresh_without_fallback_also_has_cooldown(monkeypatch, clear_cache, tmp_path):
    calls = []
    async def fail():
        calls.append(1)
        raise YahooUnavailable("Unavailable")
    monkeypatch.setattr(market_data, "fetch_snapshot", fail)
    monkeypatch.setattr(market_data, "SNAPSHOT_PATH", tmp_path / "missing.json")
    for _ in range(3):
        with pytest.raises(market_data.DataUnavailable):
            market_data.get_snapshot()
    assert len(calls) == 1


def test_401_fails_without_retry_and_reports_status():
    stats = {}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            await fetch_chart(client, "SPY", stats=stats)
    with pytest.raises(YahooUnavailable):
        asyncio.run(run())
    assert stats["attempts"] == 1
    assert stats["http_401"] == 1
    assert stats["retries"] == 0


def test_parallel_batch_uses_one_client_and_eight_connections(monkeypatch):
    from app.ingestion import yahoo
    active, peak, clients, seen = 0, 0, [], []
    async def handle(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append(request)
        await asyncio.sleep(.005)
        ticker = request.url.path.rsplit("/", 1)[-1]
        symbol = next(s for s, t in YAHOO_TICKERS.items() if t == ticker)
        active -= 1
        return httpx.Response(200, json=json.loads((FIXTURES / f"{symbol}.json").read_text()))
    original = httpx.AsyncClient
    def client(**kwargs):
        clients.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(yahoo.httpx, "AsyncClient", client)
    result = asyncio.run(yahoo.fetch_snapshot())
    assert len(clients) == 1
    assert peak == 8
    assert len(seen) == len(YAHOO_TICKERS)
    assert all(r.url.params["range"] == "2y" for r in seen)
    assert result["_telemetry"]["responses"] == 25
    assert result["_telemetry"]["http_429"] == 0
    assert set(result["_telemetry"]["symbols"]) == set(YAHOO_TICKERS)
