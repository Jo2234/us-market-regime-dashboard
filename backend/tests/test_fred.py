import asyncio
import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.data.instruments import FRED_SERIES
from app.ingestion import fred
from app.services import macro_data, market_data, analytics, regime

FIXTURES = Path(__file__).parent / "fixtures" / "fred"


@pytest.fixture
def fred_series():
    return {series_id: {"source": "fred", "fred_series_id": series_id,
            "fetched_at": "2026-09-29T14:00:00+00:00",
            "observations": fred.parse_csv(series_id, (FIXTURES / f"{series_id}.csv").read_text())}
            for series_id in FRED_SERIES.values()}


@pytest.fixture(autouse=True)
def clear_macro_cache(monkeypatch):
    for name in ("_cached", "_expires", "_modes"):
        monkeypatch.setattr(macro_data, name, {})


def test_recorded_csv_and_exact_calendar_yoy(fred_series, empty_conn):
    for series_id, series in fred_series.items():
        macro_data.validate_series(series_id, series)
    assert fred_series["CPIAUCSL"]["observations"][-1] == {"date": "2026-08-01", "value": 334.131}
    headline = macro_data.yoy_observations(fred_series["CPIAUCSL"]["observations"])
    core = macro_data.yoy_observations(fred_series["CPILFESL"]["observations"])
    assert headline[-1]["value"] == pytest.approx(3.353016322755642)
    assert core[-1]["value"] == pytest.approx(2.4461631786472537)
    missing_month = [r for r in fred_series["CPIAUCSL"]["observations"] if r["date"] != "2025-08-01"]
    assert macro_data.yoy_observations(missing_month)[-1]["date"] == "2026-07-01"
    macro_data.populate_database(empty_conn, fred_series, {})
    summary = macro_data.summary(empty_conn, analytics.MarketHistory(empty_conn), date(2026, 9, 28))
    assert summary["FEDFUNDS"]["value"] == 3.88
    assert summary["FEDFUNDS"]["fred_series_id"] == "DFF"
    assert summary["FEDFUNDS"]["frequency"] == "daily"
    assert summary["FEDFUNDS_MONTHLY"]["value"] == 3.63
    assert summary["CPI_YOY"]["observation_label"] == "Aug 2026"
    assert summary["UNRATE"]["value"] == 4.1
    assert all(r["source"] == "fred" and r["source_url"].startswith("https://fred.stlouisfed.org/series/") for r in summary.values())


def test_missing_zero_and_nonfinite_csv():
    assert fred.parse_csv("DFF", "observation_date,DFF\n2026-01-01,0\n2026-01-02,.\n2026-01-03,nan\n") == [{"date": "2026-01-01", "value": 0.0}]
    with pytest.raises(ValueError):
        fred.parse_csv("DFF", "<html>blocked</html>")


@pytest.mark.parametrize("symbol,observed,today,stale", [
    ("CPI_YOY", "2026-08-01", "2026-09-29", False),
    ("CPI_YOY", "2026-08-01", "2026-10-14", False),
    ("CPI_YOY", "2026-08-01", "2026-10-21", True),
    ("UNRATE", "2026-08-01", "2026-09-29", False),
    ("UNRATE", "2026-08-01", "2026-10-09", False),
    ("UNRATE", "2026-08-01", "2026-10-11", True),
    ("FEDFUNDS_MONTHLY", "2025-12-01", "2026-01-29", False),
])
def test_monthly_publication_windows(symbol, observed, today, stale):
    result = macro_data.freshness(symbol, date.fromisoformat(observed), date.fromisoformat(today))
    assert result["is_stale"] is stale
    assert macro_data.freshness(symbol, None)["status"] == "unavailable"


def test_daily_publication_grace_includes_weekend_and_holiday(monkeypatch):
    monkeypatch.setattr(macro_data, "latest_completed_session", lambda: date(2026, 9, 28))
    assert not macro_data.freshness("FEDFUNDS", date(2026, 9, 25))["is_stale"]
    assert macro_data.freshness("FEDFUNDS", date(2026, 9, 22))["is_stale"]
    monkeypatch.setattr(macro_data, "latest_completed_session", lambda: date(2026, 9, 8))
    assert not macro_data.freshness("FEDFUNDS", date(2026, 9, 4))["is_stale"]


def test_key_path_and_csv_retry_without_network():
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(200, text=(FIXTURES / "UNRATE.csv").read_text())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            stats = {}
            result = await fred.fetch_series(client, "UNRATE", stats=stats)
            assert result["observations"][-1]["value"] == 4.1
            assert stats["http_429"] == stats["retries"] == 1
        def key_handler(request):
            assert request.url.params["api_key"] == "test-key"
            assert request.url.host == "api.stlouisfed.org"
            return httpx.Response(200, json={"observations": [{"date": "2026-08-01", "value": "4.1"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(key_handler)) as client:
            return await fred.fetch_series(client, "UNRATE", api_key="test-key")
    assert asyncio.run(run())["observations"][0]["value"] == 4.1


def test_cache_single_flight_partial_failure_and_cooldown(monkeypatch, fred_series, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(macro_data, "SNAPSHOT_PATH", tmp_path / "absent.json")
    calls = []
    async def fetch(ids):
        calls.append(ids)
        return copy.deepcopy(fred_series), {"fetch_ms": 42}
    monkeypatch.setattr(macro_data, "fetch_batch", fetch)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: macro_data.get_snapshot(), range(5)))
    assert len(calls) == 1
    assert all(item[1]["series"]["FEDFUNDS"]["mode"] == "live" for item in results)
    assert len(macro_data._expires) == len(FRED_SERIES)
    async def fail(ids):
        calls.append(ids)
        return {}, {"fetch_ms": 6}
    monkeypatch.setattr(macro_data, "fetch_batch", fail)
    macro_data._expires["DFF"] = 0
    result, delivery = macro_data.get_snapshot()
    assert calls[-1] == ["DFF"]
    assert delivery["series"]["FEDFUNDS"]["mode"] == "snapshot"
    assert delivery["series"]["UNRATE"]["mode"] == "live"
    for _ in range(3):
        macro_data.get_snapshot()
    assert len(calls) == 2
    assert result["DFF"]["observations"][-1]["date"] == "2026-09-25"


def test_bootstrap_snapshot_and_corrupt_card(monkeypatch, fred_series, tmp_path):
    fred_series["DFF"]["source"] = "demo_seed"
    path = tmp_path / "fred.json"
    path.write_text(json.dumps({"version": 1, "series": fred_series}))
    monkeypatch.setattr(macro_data, "SNAPSHOT_PATH", path)
    macro_data._lock.acquire()
    try:
        result, delivery = macro_data.get_snapshot(cached_only=True)
    finally:
        macro_data._lock.release()
    assert "DFF" not in result
    assert delivery["series"]["FEDFUNDS"]["mode"] == "unavailable"
    assert delivery["series"]["CPI_YOY"]["mode"] == "snapshot"


def test_kill_test_macro_only_and_regime_impact(monkeypatch, tmp_path, empty_conn, fred_series):
    from app.data.instruments import YAHOO_TICKERS
    from app.ingestion.yahoo import normalize_chart
    yahoo = {"version": 1, "fetched_at": "2026-09-29T14:00:00+00:00", "series": {
        symbol: {"source": "yahoo_finance", "yahoo_ticker": ticker,
                 "bars": normalize_chart(symbol, json.loads((FIXTURES.parent / f"{symbol}.json").read_text()), date(2026, 9, 28))}
        for symbol, ticker in YAHOO_TICKERS.items()}}
    market_data.validate_snapshot(yahoo)
    market_data.populate_database(empty_conn, yahoo, "live")
    before = regime.classify_regime(empty_conn)
    macro_data.populate_database(empty_conn, fred_series, {})
    after = regime.classify_regime(empty_conn)
    assert after["regime_label"] in {"rates_pressure", "inflation_pressure"}
    assert after["inflation_score"] == before["inflation_score"] + 1 == 2
    assert after["risk_score"] == before["risk_score"]
    assert after["growth_score"] == before["growth_score"]
    assert after["rates_pressure_score"] >= before["rates_pressure_score"]
    monkeypatch.setenv("MARKET_REGIME_FORCE_FRED_FAILURE", "1")
    from app.api import routes
    monkeypatch.setattr(routes, "get_snapshot", lambda **kwargs: (yahoo, "live"))
    from app.main import create_app
    with TestClient(create_app()) as client:
        result = client.get("/api/dashboard/summary").json()
        assert result["data_mode"] == "snapshot"
        assert result["macro_summary"]["FEDFUNDS"]["mode"] == "snapshot"
        assert "demo_seed" not in json.dumps(result)
        monkeypatch.setattr(macro_data, "_cached", {})
        monkeypatch.setattr(macro_data, "SNAPSHOT_PATH", tmp_path / "missing.json")
        result = client.get("/api/dashboard/summary").json()
        assert result["macro_summary"]["FEDFUNDS"]["source"] == "fred"  # Bundled artifact survives provider/file failure.
        assert result["major_indices"][0]["source"] == "yahoo_finance"


def test_overall_deadline_cancels_slow_requests(monkeypatch):
    cancelled = []
    async def slow(client, series_id, **kwargs):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(series_id)
    monkeypatch.delenv("MARKET_REGIME_FORCE_FRED_FAILURE", raising=False)
    monkeypatch.setattr(fred, "fetch_series", slow)
    monkeypatch.setattr(fred, "BUDGET_SECONDS", .01)
    results, stats = asyncio.run(fred.fetch_batch(["DFF", "UNRATE"]))
    assert results == {}
    assert set(cancelled) == {"DFF", "UNRATE"}
    assert all(s["error"] == "Timeout" for s in stats["symbols"].values())


def test_malformed_snapshot_and_incomplete_latest_yoy(monkeypatch, tmp_path, fred_series):
    path = tmp_path / "fred.json"
    path.write_text("[]")
    monkeypatch.setattr(macro_data, "SNAPSHOT_PATH", path)
    assert macro_data.read_snapshot() == {}
    series = fred_series["CPIAUCSL"]
    series["observations"] = [r for r in series["observations"] if r["date"] != "2025-08-01"]
    with pytest.raises(ValueError, match="Latest CPI"):
        macro_data.validate_series("CPIAUCSL", series)


def test_official_curve_uses_common_date_and_daily_publication_lag(empty_conn, fred_series, monkeypatch):
    macro_data.populate_database(empty_conn, fred_series, {})
    curve = analytics.yield_curve(empty_conn, date(2026, 9, 30))
    assert curve['date'] == '2026-09-29'
    assert {r['date'] for r in curve['maturities']} == {'2026-09-29'}
    values = {r['symbol']: r['value'] for r in curve['maturities']}
    assert values['DGS2'] == 4.89 and values['DGS10'] == 5.26
    assert curve['spreads']['10y_2y'] == .37
    assert curve['spread_metadata']['10y_2y']['fred_series_id'] == 'T10Y2Y'
    assert all(r['source'] == 'fred' and r['yahoo_ticker'] is None for r in curve['maturities'])
    prior = analytics.yield_curve(empty_conn, date(2026,9,29))
    assert prior['date'] == '2026-09-28' and prior['spreads']['10y_2y'] == .32
    monkeypatch.setattr(macro_data, 'latest_completed_session', lambda: date(2026,9,30))
    assert not macro_data.freshness('DGS2', date(2026,9,29))['is_stale']
    assert macro_data.freshness('DGS2', date(2026,9,28))['is_stale']
