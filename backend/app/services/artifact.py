"""Small visitor path: validated daily artifact, optional bounded quote refresh."""
import asyncio
import bisect
import copy
import gzip
import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from app.services.calendar import latest_completed_session, market_now, market_status, missed_sessions

VERSION = 1
PATH = Path(__file__).resolve().parents[1] / 'data/dashboard_artifact.json.gz'
REMOTE = 'https://raw.githubusercontent.com/Jo2234/us-market-regime-dashboard/main/backend/app/data/dashboard_artifact.json.gz'
_lock = threading.Lock()
_cached = None
_checked = 0.0


class Artifact:
    def __init__(self, payload):
        self.payload = payload
        self.dates = sorted(payload['days'])

    def selected(self, requested=None):
        limit = requested.isoformat() if requested else self.dates[-1]
        index = bisect.bisect_right(self.dates, limit) - 1
        if index < 0:
            from fastapi import HTTPException
            raise HTTPException(404, 'No precomputed research snapshot is available for this date')
        return self.payload['days'][self.dates[index]]


def decode(content):
    payload = json.loads(gzip.decompress(content))
    if payload.get('version') != VERSION or not payload.get('days') or not payload.get('series'):
        raise ValueError('Unsupported or incomplete daily artifact')
    if payload['as_of'] != max(payload['days']):
        raise ValueError('Inconsistent artifact date')
    for rows in payload['series'].values():
        if not rows or any(r.get('source') not in ('yahoo_finance', 'fred') for r in rows):
            raise ValueError('Artifact contains unverified observations')
    return Artifact(payload)


def overdue(bundle):
    # Two hours allow the scheduled close build and delivery to finish.
    expected = latest_completed_session(market_now() - timedelta(hours=2))
    return date.fromisoformat(bundle.payload['as_of']) < expected


def _download():
    import httpx
    async def get():
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(REMOTE)
            response.raise_for_status()
            return response.content
    async def bounded():
        return await asyncio.wait_for(get(), timeout=1.5)
    return asyncio.run(bounded())


def load(*, cached_only=False):
    global _cached, _checked
    with _lock:
        first = _cached is None
        if first:
            _cached = decode(PATH.read_bytes())
        if not cached_only and overdue(_cached) and time.monotonic() >= _checked:
            _checked = time.monotonic() + 900
            try:
                # Only retrieve a newer precomputed artifact. Never run the model or
                # hundreds of provider requests inside a visitor request.
                import httpx
                candidate = decode(_download())
                if candidate.payload['as_of'] >= _cached.payload['as_of']:
                    _cached = candidate
            except (OSError, ValueError, KeyError, TimeoutError, httpx.HTTPError):
                pass  # Preserve the validated real artifact and its original dates.
        return _cached, 'miss' if first else 'stale' if overdue(_cached) else 'hit'


def freshness(bundle):
    from app.services.macro_data import freshness as fred_freshness
    value = copy.deepcopy(bundle.payload['freshness'])
    now, expected = market_now(), latest_completed_session()
    value.update(generated_at=now.isoformat(), expected_session_date=expected.isoformat())
    for row in value['instruments']:
        observed = date.fromisoformat(row['latest_date']) if row['latest_date'] else None
        if row['source'] == 'fred':
            row.update(fred_freshness(row['symbol'], observed, now.date()))
        else:
            lag = missed_sessions(observed, expected) if observed else None
            row.update(missing_sessions=lag, is_stale=bool(lag), status='unavailable' if observed is None else 'stale' if lag else 'fresh')
        row['age_days'] = (now.date() - observed).days if observed else None
    for source in value['sources']:
        rows = [r for r in value['instruments'] if r['source'] == source['source']]
        source['is_stale'] = any(r['is_stale'] for r in rows)
        source['status'] = 'partial' if any(r['status'] == 'unavailable' for r in rows) else 'stale' if source['is_stale'] else 'fresh'
    return value


def series(bundle, symbol, start=None, end=None):
    return [r for r in bundle.payload['series'].get(symbol.upper(), [])
            if (not start or r['date'] >= start.isoformat()) and (not end or r['date'] <= end.isoformat())]


def sectors(bundle, windows, requested=None):
    rows = bundle.selected(requested)['sectors']
    primary = '1m' if '1m' in windows else windows[0]
    ordered = sorted(rows, key=lambda row: row['returns'].get(primary) if row['returns'].get(primary) is not None else -999, reverse=True)
    return [{**row, 'returns': {w:row['returns'].get(w) for w in windows},
             'relative_to_spy': {w:row['relative_to_spy'].get(w) for w in windows}} for row in ordered]


def quote_returns(quotes, bundle):
    from app.services.analytics import calendar_anchor
    result = {}
    for symbol, quote in quotes.items():
        item = dict(quote)
        rows = bundle.payload['series'].get(symbol, [])
        if quote['is_current_session'] and rows:
            day = date.fromisoformat(quote['observation_date'])
            previous_rows = [r for r in rows if r['date'] < day.isoformat()]
            previous = quote['previous_close'] or (previous_rows[-1]['close'] if previous_rows else None)
            returns = {'1d': quote['price'] / previous - 1 if previous else None}
            for window in ('1w', '1m', '3m', 'ytd', '1y'):
                anchor = calendar_anchor(day, window).isoformat()
                index = bisect.bisect_right([r['date'] for r in rows], anchor) - 1
                returns[window] = quote['price'] / rows[index]['adjusted_close'] - 1 if index >= 0 else None
            item.update(returns=returns, previous_close=previous, return_basis='live_price_over_adjusted_historical_close')
        result[symbol] = item
    return result


def summary(bundle, requested=None, window='1m', *, cached_only=False):
    from app.services import live_quotes
    day = bundle.selected(requested)
    result = {k: v for k, v in day.items() if k != 'performance_windows'}
    from app.services.macro_data import freshness as fred_freshness
    result['macro_summary'] = {symbol: {**item, **fred_freshness(symbol, date.fromisoformat(item['observation_date']), requested or market_now().date(), expected_session=requested)} if item else None for symbol,item in day['macro_summary'].items()}
    result['performance_series'] = day['performance_windows'][window]
    result['historical_regimes'] = [p for p in bundle.payload['history'] if p['date'] <= day['as_of']]
    result['historical_regimes_v2'] = [p for p in bundle.payload.get('regime_v2_history', []) if p['date'] <= day['as_of']]
    state = market_status()
    quotes, delivery = live_quotes.get_quotes(cached_only=cached_only) if requested is None else ({}, {'cache': 'historical'})
    stale = overdue(bundle)
    result.update(market_status=state, live_quotes=quote_returns(quotes, bundle), quote_delivery=delivery,
                  data_mode='snapshot', fetched_at=bundle.payload['fetched_at'], fetch_ms=delivery.get('fetch_ms', 0),
                  cache='stale' if stale else getattr(bundle,'cache','hit'), refresh_pending=False, retry_after_seconds=900 if stale else 0,
                  fetch_diagnostics={'daily_provider_requests': 0, 'model_compute_ms': 0},
                  artifact_delivery={'version': VERSION, 'scheduled': True, 'fresh': not stale, 'as_of': bundle.payload['as_of'], 'built_at': bundle.payload['built_at']},
                  history_delivery={'cache': 'artifact', 'compute_ms': 0, 'points': len(result['historical_regimes'])},
                  data_freshness=freshness(bundle))
    return result
