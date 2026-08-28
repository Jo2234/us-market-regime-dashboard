"""Deterministic daily classifications cached by observed inputs, not ephemeral DB rows."""
import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path

from app.services import analytics, regime
from app.core.telemetry import log_event

MODEL_VERSION = 2
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / 'data/regime_history.json'
_cache = OrderedDict()
_lock = threading.Lock()


def fingerprint(history):
    records = {"version": MODEL_VERSION, "prices": {s: [(r['date'].isoformat(), r['close'], r['adjusted_close']) for r in rows] for s, rows in history.prices.items()},
               "macro": {s: [(r['date'].isoformat(), r['value'], r['source']) for r in rows] for s, rows in history.macro.items()}}
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build(conn, history):
    started = time.perf_counter()
    rows = analytics._price_frame(history, 'SPY')
    if not rows:
        raise ValueError('No daily history available')
    start = analytics.calendar_anchor(rows[-1]['date'], '1y')
    days = [r['date'] for r in rows[63:] if r['date'] >= start]
    prior = [r['date'] for r in rows[63:] if r['date'] < start]
    previous = regime.classify_regime(conn, prior[-1], history=history, previous=None) if prior else None
    snapshots = []
    for day in days:
        current = regime.classify_regime(conn, day, history=history, previous=previous)
        snapshots.append(current)
        previous = current
    elapsed = round((time.perf_counter() - started)*1000, 2)
    log_event('regime_history', compute_ms=elapsed, points=len(snapshots))
    return {'version': MODEL_VERSION, 'fingerprint': fingerprint(history), 'snapshots': snapshots}, elapsed


def get_history(conn, history):
    key = fingerprint(history)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key], {'cache': 'hit', 'compute_ms': 0, 'points': len(_cache[key]['snapshots'])}
        try:
            saved = json.loads(SNAPSHOT_PATH.read_text())
            assert saved['version'] == MODEL_VERSION and saved['fingerprint'] == key and saved['snapshots']
            assert all(p['date'] and all(isinstance(p[k], (float, int)) for k in ('risk_score', 'growth_score', 'inflation_score', 'rates_pressure_score')) for p in saved['snapshots'])
            result, elapsed, mode = saved, 0, 'snapshot'
        except (OSError, ValueError, KeyError, TypeError, AssertionError):
            result, elapsed = build(conn, history)
            mode = 'miss'
        _cache[key] = result
        while len(_cache) > 3:
            _cache.popitem(last=False)
        return result, {'cache': mode, 'compute_ms': elapsed, 'points': len(result['snapshots'])}


def for_date(conn, history, requested=None):
    bundle, stats = get_history(conn, history)
    available = [p for p in bundle['snapshots'] if requested is None or p['date'] <= requested.isoformat()]
    if available:
        selected = available[-1]
    else:
        # An explicitly selected date outside the displayed year needs only two
        # classifications, never a request-time backfill of the entire history.
        days = analytics._price_frame(history, 'SPY', end=requested)
        previous = regime.classify_regime(conn, days[-2]['date'], history=history, previous=None) if len(days) > 1 else None
        selected = regime.classify_regime(conn, requested, history=history, previous=previous)
    keys = ('date', 'regime_label', 'risk_score', 'growth_score', 'inflation_score', 'rates_pressure_score')
    points = [{**{k: p[k] for k in keys}, 'note': p['signals']['what_changed']} for p in available]
    return selected, points, stats
