from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import get_db, router


def build_app() -> FastAPI:
    local_app = FastAPI()
    local_app.include_router(router)
    return local_app


def test_summary_endpoint_returns_required_sections(seeded_conn):
    from app.main import app

    def override_db():
        yield seeded_conn

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/dashboard/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert {"regime", "major_indices", "sector_leaders", "rates_summary", "data_freshness"} <= payload.keys()
    assert payload["major_indices"]
    assert payload["data_freshness"]
    assert payload["regime"]["summary"] == payload["analyst_summary"]


def test_series_endpoint_respects_date_filters(seeded_conn):
    def override_db():
        yield seeded_conn

    app = build_app()
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/series/SPY?start=2026-01-05&end=2026-01-09")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    dates = [row["date"] for row in response.json()["data"]]
    assert dates[0] >= "2026-01-05"
    assert dates[-1] <= "2026-01-09"


def test_freshness_endpoint_identifies_stale_sources(seeded_conn):
    def override_db():
        yield seeded_conn

    app = build_app()
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/data/freshness")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_latest_date"] is not None
    assert payload["freshness_policy"].startswith("Instrument/source rows are stale")
    assert any(item["source"] == "demo_seed" and item["status"] in {"fresh", "stale"} for item in payload["sources"])


def test_sector_csv_export_returns_flat_download(seeded_conn):
    def override_db():
        yield seeded_conn

    app = build_app()
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/export/sectors.csv?windows=1d,1m")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "sector_performance.csv" in response.headers["content-disposition"]
    assert response.text.splitlines()[0] == "symbol,return_1d,return_1m,relative_to_spy_1d,relative_to_spy_1m"
    assert "XLK" in response.text


def test_series_csv_export_respects_filters(seeded_conn):
    def override_db():
        yield seeded_conn

    app = build_app()
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/export/series/SPY.csv?start=2026-01-05&end=2026-01-09")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0].startswith("date,open,high,low,close,adjusted_close")
    assert "2026-01-05" in response.text


def test_summary_uses_requested_observation_date_and_revised_inputs(seeded_conn):
    from datetime import date
    from app.api.routes import dashboard_summary
    from app.services.regime import classify_regime

    early = dashboard_summary(date(2026, 6, 1), seeded_conn)
    later = dashboard_summary(date(2026, 6, 28), seeded_conn)
    assert early["as_of"] == "2026-06-01"
    assert later["as_of"] == "2026-06-25"
    assert later["major_indices"][0]["date"] == later["as_of"]
    assert max(row["date"] for row in later["performance_series"]) == later["as_of"]
    assert all(row["date"] <= later["as_of"] for row in later["historical_regimes"])

    seeded_conn.execute(
        "UPDATE market_prices SET adjusted_close = adjusted_close / 2 WHERE instrument_id = 'SPY' AND date = '2026-06-25'"
    )
    revised = dashboard_summary(date(2026, 6, 25), seeded_conn)
    expected = classify_regime(seeded_conn, date(2026, 6, 25))
    assert revised["regime"] == expected
    assert revised["regime"]["risk_score"] != later["regime"]["risk_score"]


def test_summary_supplies_full_sectors_macros_and_selected_performance_window(seeded_conn):
    from datetime import date
    from app.api.routes import dashboard_summary
    from app.services import analytics

    result = dashboard_summary(date(2026, 6, 1), seeded_conn, range_="1w")
    assert len(result["sectors"]) == 11
    assert len(result["performance_series"]) == 6
    assert result["performance_series"][0]["SPY"] == 100
    assert result["performance_series"][-1]["date"] == "2026-06-01"
    assert result["macro_summary"]["CPI_YOY"] == analytics.latest_macro_value(seeded_conn, "CPI_YOY", date(2026, 6, 1))
    assert result["sectors"] == analytics.sector_performance(seeded_conn, ("1d", "1w", "1m", "3m", "ytd", "1y"), date(2026, 6, 1))


def test_summary_before_any_observation_returns_not_found(seeded_conn):
    app = build_app()
    app.dependency_overrides[get_db] = lambda: seeded_conn
    response = TestClient(app).get("/dashboard/summary?date=2000-01-01")
    assert response.status_code == 404
