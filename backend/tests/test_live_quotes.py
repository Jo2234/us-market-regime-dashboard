import asyncio
import copy
import json
from datetime import datetime, timezone, date
from pathlib import Path

import httpx
import pytest
from app.services import live_quotes as live, analytics, calendar

FIXTURES = Path(__file__).parent / 'fixtures'

def recorded():
    return live.normalize_spark(json.loads((FIXTURES / 'spark_meta_0.json').read_text())) | live.normalize_spark(json.loads((FIXTURES / 'spark_meta_1.json').read_text()))


def test_spark_metadata_null_bars_old_futures_and_missing_fields():
    quotes = recorded()
    assert len(quotes) == 25
    assert quotes['SPY']['price'] == pytest.approx(764.2)
    assert quotes['SPY']['observed_at'].startswith('2026-09-29T20:00:00')
    assert quotes['2YY=F']['observation_date'] == '2026-09-22'
    payload = json.loads((FIXTURES / 'spark_meta_0.json').read_text())
    item = payload['spark']['result'][0]['response'][0]
    item['indicators']['quote'][0]['close'][-1] = None
    assert live.normalize_spark(payload)
    item['meta'].pop('regularMarketTime')
    assert len(live.normalize_spark(payload)) == 19
    assert live.normalize_spark({'spark': {'result': None}}) == {}


def test_market_calendar_and_production_clock_guard(monkeypatch):
    for clock, expected in [('2026-09-29T15:00:00Z', True), ('2026-09-29T20:00:00Z', False), ('2026-09-07T15:00:00Z', False), ('2026-11-27T17:59:00Z', True), ('2026-11-27T18:00:00Z', False)]:
        assert calendar.market_status(datetime.fromisoformat(clock))['is_open'] is expected
    monkeypatch.setenv('MARKET_REGIME_CLOCK', '2026-09-29T15:00:00Z')
    monkeypatch.delenv('VERCEL', raising=False)
    assert calendar.market_status()['is_open']
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_ENV', 'production')
    assert abs((calendar.market_now() - datetime.now(timezone.utc)).total_seconds()) < 5
    monkeypatch.setenv('VERCEL_ENV', 'preview')
    assert calendar.market_status()['is_open']


def test_quote_cache_backoff_and_closed_no_fetch(monkeypatch):
    monkeypatch.setenv('MARKET_REGIME_CLOCK', '2026-09-29T19:59:30Z')
    monkeypatch.delenv('VERCEL', raising=False)
    for key, value in [('_cached', {}), ('_expires', 0), ('_interval', 60), ('_last_stats', {})]:
        monkeypatch.setattr(live, key, value)
    calls = []
    async def fetch():
        calls.append(True)
        return recorded(), {'http_429': 0, 'http_401': 0, 'fetch_ms': 50}
    monkeypatch.setattr(live, 'fetch_quotes', fetch)
    quotes, delivery = live.get_quotes()
    assert quotes['SPY']['is_current_session']
    assert quotes['DGS2']['is_stale']
    assert delivery['cache'] == 'miss'
    assert live.get_quotes()[1]['cache'] == 'hit'
    assert len(calls) == 1
    async def blocked():
        exc = RuntimeError('rate limited'); exc.telemetry = {'http_429': 1}; raise exc
    monkeypatch.setattr(live, 'fetch_quotes', blocked)
    for interval in [120, 240, 480, 900]:
        monkeypatch.setattr(live, '_expires', 0)
        fallback, delivery = live.get_quotes()
        assert fallback['SPY']['price'] == quotes['SPY']['price']
        assert delivery['cache'] == 'stale' and delivery['refresh_seconds'] == interval
    monkeypatch.setattr(live, 'fetch_quotes', fetch)
    monkeypatch.setattr(live, '_expires', 0)
    assert live.get_quotes()[1]['refresh_seconds'] == 450
    monkeypatch.setenv('MARKET_REGIME_CLOCK', '2026-09-30T01:00:00Z')
    assert live.get_quotes() == ({}, {'cache': 'closed', 'fetch_ms': 0, 'refresh_seconds': 900})


def test_live_calendar_returns_leave_daily_model_untouched(empty_conn):
    from conftest import insert_price_path
    insert_price_path(empty_conn, 'SPY', [100 + n for n in range(60)], start=date(2026, 7, 1))
    history = analytics.MarketHistory(empty_conn)
    before = copy.deepcopy(history.prices)
    quotes = {'SPY': {**recorded()['SPY'], 'is_current_session': True}}
    result = live.with_returns(quotes, history)['SPY']
    assert result['returns']['1d'] == pytest.approx(764.2 / quotes['SPY']['previous_close'] - 1)
    baseline = next(row['adjusted_close'] for row in history.prices['SPY'] if row['date'] == date(2026, 8, 28))
    assert result['returns']['1m'] == pytest.approx(764.2 / baseline - 1)
    assert history.prices == before
