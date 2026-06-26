from fastapi.testclient import TestClient

from backend.main import app, return_window, regime_snapshot

client = TestClient(app)


def test_return_formula_available():
    assert isinstance(return_window("SPY", 21), float)


def test_regime_has_signals():
    snap = regime_snapshot()
    assert snap["regime_label"]
    assert "signals" in snap


def test_summary_endpoint_shape():
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["major_indices"]
    assert payload["data_freshness"]
