from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import get_db, router


def build_app() -> FastAPI:
    local_app = FastAPI()
    local_app.include_router(router)
    return local_app


def test_summary_endpoint_returns_required_sections(seeded_conn):
    def override_db():
        yield seeded_conn

    app = build_app()
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/dashboard/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert {"regime", "major_indices", "sector_leaders", "rates_summary", "data_freshness"} <= payload.keys()
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
