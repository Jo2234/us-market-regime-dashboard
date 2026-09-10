"""Small visitor path: validated daily artifact, optional bounded quote refresh."""
import asyncio
import bisect
import copy
import gzip
import hashlib
import json
import threading
import time
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

from app.services.calendar import latest_completed_session, market_now, market_status, missed_sessions, next_session, session_close

VERSION = 1
PATH = Path(__file__).resolve().parents[1] / 'data/dashboard_artifact.json.gz'
MANIFEST_PATH = PATH.with_name('dashboard_artifact.meta.json')
REMOTE = 'https://raw.githubusercontent.com/Jo2234/us-market-regime-dashboard/main/backend/app/data/dashboard_artifact.json.gz'
MANIFEST_REMOTE = REMOTE.replace('dashboard_artifact.json.gz', 'dashboard_artifact.meta.json')
# Delivery window after the official close (early closes included) for the
# scheduled build, commit and deployment. It labels pending vs overdue only;
# observation rows still turn stale at the close.
GRACE = timedelta(hours=2)
RETRY_SECONDS = 900
POLICY = ('Research is current when the artifact covers the latest completed NYSE session (official close, '
          'early closes, holidays and DST respected). From that close until close + 2h it is pending: awaiting '
          'the scheduled build/delivery, not evidence that a job is running. After that deadline it is overdue. '
          'Observation dates and stale flags are never adjusted.')
_lock = threading.Lock()
_cached = None
_checked = 0.0


class Artifact:
    origin = 'bundled'

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
    try:
        payload = json.loads(gzip.decompress(content), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite artifact data')))
    except (OSError, EOFError, zlib.error, ValueError) as exc:
        raise ValueError('Corrupt daily artifact') from exc
    if not isinstance(payload, dict):
        raise ValueError('Invalid daily artifact object')
    if payload.get('version') != VERSION or not isinstance(payload.get('days'), dict) or not payload['days'] or not isinstance(payload.get('series'), dict) or not payload['series']:
        raise ValueError('Unsupported or incomplete daily artifact')
    if payload['as_of'] != max(payload['days']):
        raise ValueError('Inconsistent artifact date')
    if not all(key in payload for key in ('built_at', 'fetched_at', 'history', 'freshness')) or not isinstance(payload['freshness'], dict) or not isinstance(payload['freshness'].get('instruments'), list) or not payload['freshness']['instruments']:
        raise ValueError('Incomplete daily artifact')
    if not isinstance(payload['built_at'], str) or datetime.fromisoformat(payload['built_at']).tzinfo is None:
        raise ValueError('Artifact build timestamp needs a timezone')
    date.fromisoformat(payload['as_of'])
    for day in payload['days']:
        date.fromisoformat(day)
    if not isinstance(payload['days'][payload['as_of']], dict) or not all(key in payload['days'][payload['as_of']] for key in ('regime', 'macro_summary', 'performance_windows')):
        raise ValueError('Latest artifact day is incomplete')
    for rows in payload['series'].values():
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or r.get('source') not in ('yahoo_finance', 'fred') for r in rows):
            raise ValueError('Artifact contains unverified observations')
    return Artifact(payload)


def manifest(content):
    """Small sidecar so pollers learn as_of/built_at without the multi-MB artifact."""
    payload = decode(content).payload
    return {'version': VERSION, 'as_of': payload['as_of'], 'built_at': payload['built_at'],
            'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}


def _key(item):
    return date.fromisoformat(item['as_of']), datetime.fromisoformat(item['built_at'])


def delivery_status(bundle, now=None):
    """Classify research delivery against the official NYSE close and delivery deadline."""
    now = now or market_now()
    as_of = date.fromisoformat(bundle.payload['as_of'])
    expected = latest_completed_session(now)
    required = latest_completed_session(now - GRACE)
    status = 'current' if as_of >= expected else 'pending' if as_of >= required else 'overdue'
    following = next_session(expected)
    late = next_session(as_of) if status == 'overdue' else None
    return {
        'status': status, 'fresh': status != 'overdue', 'pending': status == 'pending', 'overdue': status == 'overdue',
        'as_of': bundle.payload['as_of'], 'built_at': bundle.payload['built_at'], 'evaluated_at': now.isoformat(),
        'expected_session': expected.isoformat(), 'expected_session_close': session_close(expected).isoformat(),
        'delivery_deadline': (session_close(expected) + GRACE).isoformat(),
        'grace_seconds': int(GRACE.total_seconds()), 'missing_sessions': missed_sessions(as_of, expected),
        'overdue_since': (session_close(late) + GRACE).isoformat() if late else None,
        'next_session': following.isoformat() if following else None,
        'next_delivery_deadline': (session_close(following) + GRACE).isoformat() if following else None,
        'policy': POLICY,
    }


def overdue(bundle):
    return delivery_status(bundle)['status'] == 'overdue'


def _download(url=REMOTE, timeout=1.5):
    import httpx
    async def get():
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    async def bounded():
        return await asyncio.wait_for(get(), timeout=timeout)
    return asyncio.run(bounded())


def _newer_remote(current):
    """Validated newer artifact from GitHub main, or None. Manifest first: no 6 MB poll."""
    listed = json.loads(_download(MANIFEST_REMOTE, 1.0))
    if listed.get('version') != VERSION or _key(listed) <= _key(current.payload):
        return None
    content = _download(REMOTE, 1.5)
    if hashlib.sha256(content).hexdigest() != listed.get('sha256'):
        raise ValueError('Remote artifact does not match its manifest')
    candidate = decode(content)
    if _key(candidate.payload) != _key(listed) or not set(current.payload['series']) <= set(candidate.payload['series']):
        raise ValueError('Remote artifact is inconsistent or drops instruments')
    if date.fromisoformat(candidate.payload['as_of']) > latest_completed_session():
        raise ValueError('Remote artifact claims a future completed session')
    old_day = current.payload['days'][current.payload['as_of']]
    new_day = candidate.payload['days'][candidate.payload['as_of']]
    if not set(old_day) <= set(new_day):
        raise ValueError('Remote artifact drops research blocks')
    for key in ('regime', 'rates_summary', 'performance_windows'):
        if not isinstance(new_day.get(key), dict) or not set(old_day.get(key, {})) <= set(new_day[key]):
            raise ValueError(f'Remote artifact drops {key} fields')
    old_symbols = {r['symbol'] for r in current.payload['freshness']['instruments']}
    new_symbols = {r['symbol'] for r in candidate.payload['freshness']['instruments']}
    if not old_symbols <= new_symbols:
        raise ValueError('Remote artifact drops source freshness rows')
    candidate.origin = 'github_main'
    return candidate


def load(*, cached_only=False):
    global _cached, _checked
    with _lock:
        first = _cached is None
        if first:
            _cached = decode(PATH.read_bytes())
        # Pending and overdue both look for a newer published artifact, at most once
        # per 15 minutes per instance.
        if not cached_only and delivery_status(_cached)['status'] != 'current' and time.monotonic() >= _checked:
            _checked = time.monotonic() + RETRY_SECONDS
            try:
                # Only retrieve a newer precomputed artifact. Never run the model or
                # hundreds of provider requests inside a visitor request.
                import httpx
                candidate = _newer_remote(_cached)
                if candidate is not None:
                    _cached = candidate
            except (OSError, ValueError, KeyError, TypeError, AttributeError, TimeoutError, httpx.HTTPError):
                pass  # Preserve the validated real artifact and its original dates.
        return _cached, 'miss' if first else 'stale' if overdue(_cached) else 'hit'


def _row_state(observed, stale_now, stale_at_deadline):
    if observed is None:
        return 'unavailable'
    return 'current' if not stale_now else 'overdue' if stale_at_deadline else 'pending'


def _fred_state(symbol, observed, now):
    """FRED cadence evaluated now and one delivery window earlier."""
    from app.services.macro_data import freshness as fred_freshness
    current = fred_freshness(symbol, observed, now.date(), expected_session=latest_completed_session(now))
    earlier = now - GRACE
    previous = fred_freshness(symbol, observed, earlier.date(), expected_session=latest_completed_session(earlier))
    state = _row_state(observed, current['is_stale'], previous['is_stale'])
    return {**current, 'delivery_state': state, 'is_overdue': state == 'overdue'}


def freshness(bundle, now=None):
    value = copy.deepcopy(bundle.payload['freshness'])
    now = now or market_now()
    expected, required = latest_completed_session(now), latest_completed_session(now - GRACE)
    delivery = delivery_status(bundle, now)
    value.update(generated_at=now.isoformat(), expected_session_date=expected.isoformat(),
                 required_session_date=required.isoformat(), delivery_deadline=delivery['delivery_deadline'],
                 artifact_status=delivery['status'], grace_seconds=delivery['grace_seconds'])
    for row in value['instruments']:
        observed = date.fromisoformat(row['latest_date']) if row['latest_date'] else None
        if row['source'] == 'fred':
            row.update(_fred_state(row['symbol'], observed, now))
        else:
            lag = missed_sessions(observed, expected) if observed else None
            late = missed_sessions(observed, required) if observed else None
            state = _row_state(observed, bool(lag), bool(late))
            row.update(missing_sessions=lag, is_stale=bool(lag), status='unavailable' if observed is None else 'stale' if lag else 'fresh',
                       delivery_state=state, is_overdue=state == 'overdue')
        row['age_days'] = (now.date() - observed).days if observed else None
    for source in value['sources']:
        rows = [r for r in value['instruments'] if r['source'] == source['source'] and r.get('affects_group_freshness', True)]
        source['is_stale'] = any(r['is_stale'] for r in rows)
        source['status'] = 'partial' if any(r['status'] == 'unavailable' for r in rows) else 'stale' if source['is_stale'] else 'fresh'
        states = {r['delivery_state'] for r in rows}
        source['delivery_state'] = next((s for s in ('overdue', 'pending', 'unavailable') if s in states), 'current')
        source['is_overdue'] = source['delivery_state'] == 'overdue'
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
    now = market_now()
    day = bundle.selected(requested)
    result = {k: v for k, v in day.items() if k != 'performance_windows'}
    from app.services.macro_data import freshness as fred_freshness
    result['macro_summary'] = {symbol: ({**item, **fred_freshness(symbol, date.fromisoformat(item['observation_date']), requested, expected_session=requested)} if requested
                                        else {**item, **_fred_state(symbol, date.fromisoformat(item['observation_date']), now)}) if item else None
                               for symbol, item in day['macro_summary'].items()}
    result['performance_series'] = day['performance_windows'][window]
    result['historical_regimes'] = [p for p in bundle.payload['history'] if p['date'] <= day['as_of']]
    result['historical_regimes_v2'] = [p for p in bundle.payload.get('regime_v2_history', []) if p['date'] <= day['as_of']]
    state = market_status(now)
    quotes, delivery = live_quotes.get_quotes(cached_only=cached_only) if requested is None else ({}, {'cache': 'historical'})
    research = delivery_status(bundle, now)
    stale = research['overdue']
    # Legacy booleans keep their meaning (scheduled artifact; fresh = not overdue).
    # refresh_pending stays False: no request-time refresh is ever running.
    research.update(version=VERSION, scheduled=True, origin=getattr(bundle, 'origin', 'bundled'),
                    view='historical' if requested else 'latest', requested_date=requested.isoformat() if requested else None)
    result.update(market_status=state, live_quotes=quote_returns(quotes, bundle), quote_delivery=delivery,
                  data_mode='snapshot', fetched_at=bundle.payload['fetched_at'], fetch_ms=delivery.get('fetch_ms', 0),
                  cache='stale' if stale else getattr(bundle,'cache','hit'), refresh_pending=False, retry_after_seconds=RETRY_SECONDS if stale else 0,
                  fetch_diagnostics={'daily_provider_requests': 0, 'model_compute_ms': 0},
                  artifact_delivery=research,
                  history_delivery={'cache': 'artifact', 'compute_ms': 0, 'points': len(result['historical_regimes'])},
                  data_freshness=freshness(bundle, now))
    return result
