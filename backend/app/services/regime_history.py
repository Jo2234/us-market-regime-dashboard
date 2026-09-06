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
from app.services.stability import stabilize, changes

MODEL_VERSION = 4
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
    days = [r['date'] for r in rows[63:]]
    previous = None
    raw = []
    for day in days:
        current = regime.classify_regime(conn, day, history=history, previous=previous)
        values = {signal['name']: signal['value'] for signal in current['signals']['all']}
        one_month = analytics.period_return(analytics._price_frame(history, 'SPY', end=day), '1m')
        current['strong_evidence'] = bool(
            (current['regime_label'] == 'risk_off_defensive' and current['risk_score'] <= -4 and one_month is not None and one_month <= -.10)
            or (current['regime_label'] == 'commodity_shock' and (values['oil_up_more_than_5pct_1m'] or 0) > .20 and (values['copper_up_more_than_5pct_1m'] or 0) > .16))
        raw.append(current)
        previous = current
    stable = stabilize(raw, strong=lambda row: row['strong_evidence'])
    for i, current in enumerate(stable):
        current['regime_label'] = current['official_label']
        current['display_label'] = regime._LABELS['regimes'][current['official_label']]
        emerging = f" Emerging: {regime._LABELS['regimes'][current['emerging_label']]} ({current['emerging_days']} of 5 days)." if current['emerging_label'] else ""
        prior = stable[i-1] if i else None
        change = f"Official regime changed from {prior['display_label']} to {current['display_label']}." if prior and prior['official_label'] != current['official_label'] else f"Official regime unchanged; day {current['days_in_regime']}."
        current['signals'] = {**current['signals'], 'what_changed': change + emerging}
        current['summary'] = f"As of {current['date']}, the official regime is {current['display_label']}, day {current['days_in_regime']}." + emerging + " Scores reflect current daily evidence; the label requires five consecutive trading days, except documented strong shocks. Research software, not investment advice."
    snapshots = stable[-252:]
    sensitivity = {str(n): changes(stabilize(raw, persistence=n, strong=lambda row: row['strong_evidence'])[-252:]) for n in (3,5,10)}
    elapsed = round((time.perf_counter() - started)*1000, 2)
    log_event('regime_history', compute_ms=elapsed, points=len(snapshots))
    return {'version': MODEL_VERSION, 'fingerprint': fingerprint(history), 'snapshots': snapshots, 'stability_sensitivity': sensitivity, 'raw_changes': changes(raw[-252:], 'regime_label')}, elapsed


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
    keys = ('date', 'regime_label', 'risk_score', 'growth_score', 'inflation_score', 'rates_pressure_score', 'raw_label', 'official_label', 'days_in_regime', 'emerging_label', 'emerging_days')
    points = [{**{k: p[k] for k in keys}, 'note': p['signals']['what_changed']} for p in available]
    return selected, points, stats
