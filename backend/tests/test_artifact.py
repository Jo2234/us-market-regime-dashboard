import gzip
import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.services import artifact, market_data, macro_data, regime_history


def test_artifact_rejects_wrong_version_and_unverified_sources():
    payload = {'version':999, 'days':{'2026-09-30':{}}, 'as_of':'2026-09-30', 'series':{'SPY':[{'source':'yahoo_finance'}]}}
    with pytest.raises(ValueError):
        artifact.decode(gzip.compress(json.dumps(payload).encode()))
    payload['version'] = artifact.VERSION
    payload['series']['SPY'][0]['source'] = 'unverified'
    with pytest.raises(ValueError):
        artifact.decode(gzip.compress(json.dumps(payload).encode()))


def test_cold_request_only_loads_recorded_artifact(monkeypatch):
    from app.main import app
    def forbidden(*args, **kwargs):
        raise AssertionError('Daily work must never run in a visitor request')
    monkeypatch.setattr(market_data, 'get_snapshot', forbidden)
    monkeypatch.setattr(macro_data, 'get_snapshot', forbidden)
    monkeypatch.setattr(regime_history, 'build', forbidden)
    monkeypatch.setattr(artifact, '_cached', None)
    monkeypatch.setattr(artifact, 'overdue', lambda b: False)
    from app.services import live_quotes
    monkeypatch.setattr(live_quotes, 'get_quotes', lambda **kw: ({}, {'cache':'closed'}))
    response = TestClient(app).get('/api/dashboard/summary')
    assert response.status_code == 200
    result = response.json()
    assert result['artifact_delivery']['fresh']
    assert result['fetch_diagnostics']['daily_provider_requests'] == 0
    assert result['history_delivery']['compute_ms'] == 0
    assert len(result['historical_regimes']) == 252
    assert 'demo_seed' not in response.text
    assert result['rates_summary']['spreads']['10y_2y'] is not None


def test_expired_artifact_survives_remote_failure(monkeypatch):
    import httpx
    monkeypatch.setattr(artifact, '_cached', None)
    monkeypatch.setattr(artifact, '_checked', 0)
    monkeypatch.setattr(artifact, 'overdue', lambda b: True)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(artifact, '_download', fail)
    first, _ = artifact.load()
    second, mode = artifact.load()
    assert first.payload == second.payload and mode == 'stale'
    assert len(calls) == 1
