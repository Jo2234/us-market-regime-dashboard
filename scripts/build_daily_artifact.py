#!/usr/bin/env python3
"""All daily analytics run here on the scheduler, never on a visitor request."""
import gzip
import json
import sys
import time
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.data import database
from app.services import artifact, analytics, regime_history, market_data, macro_data, regime_v2


def build():
    from app.api.routes import data_freshness
    yahoo = market_data.validate_snapshot(json.loads(market_data.SNAPSHOT_PATH.read_text()))
    fred = macro_data.read_snapshot()
    with database.session(':memory:') as conn:
        database.init_schema(conn)
        market_data.populate_database(conn, yahoo, 'snapshot')
        deliveries = {'series': {symbol: {'mode': 'snapshot', 'scheduled': True, 'fetched_at': fred[series_id]['fetched_at']} for symbol, series_id in macro_data.FRED_SERIES.items() if series_id in fred}}
        macro_data.populate_database(conn, fred, deliveries)
        history = analytics.MarketHistory(conn)
        regimes, stats = regime_history.get_history(conn, history)
        tick = time.perf_counter()
        model = regime_v2.build(history)
        model_ms = round((time.perf_counter()-tick)*1000,2)
        print(f"V2 daily model: {model_ms} ms, {model['official_changes']} official changes", flush=True)
        if model["snapshots"][-1]["date"] != regimes["snapshots"][-1]["date"]:
            raise ValueError("Latest model inputs incomplete; retain the previous complete daily artifact")
        v2_by_date = {r["date"]:r for r in model["snapshots"]}
        days = {}
        keys = ('date', 'regime_label', 'risk_score', 'growth_score', 'inflation_score', 'rates_pressure_score', 'raw_label', 'official_label', 'days_in_regime', 'emerging_label', 'emerging_days')
        points = [{**{k:p[k] for k in keys}, 'note':p['signals']['what_changed']} for p in regimes['snapshots']]
        for snapshot in regimes['snapshots']:
            day = date.fromisoformat(snapshot['date'])
            blocks = analytics.dashboard_market_blocks(history, day)
            days[day.isoformat()] = {'as_of':day.isoformat(), 'regime':snapshot, 'regime_v2':v2_by_date.get(day.isoformat()),
                'currency_summary':analytics.instrument_snapshot(history,'DXY',day),
                'major_indices':blocks['indices'], 'sectors':blocks['sectors'],
                'sector_leaders':blocks['sector_leaders'], 'sector_laggards':blocks['sector_laggards'],
                'rates_summary':blocks['rates'], 'commodities_summary':blocks['commodities'],
                'volatility_summary':blocks['volatility'], 'macro_summary':macro_data.summary(conn,history,day,freshness_as_of=day),
                'macro_delivery':deliveries, 'analyst_summary':snapshot['summary'],
                'performance_windows':{w:analytics.indexed_performance(history,day,w) for w in ('1d','1w','1m','3m','ytd','1y')}}
        sources = {s:analytics.price_series(history,s) for s in {*history.prices,*history.macro}}
        # Timestamp derives from inputs, keeping rebuilds byte-identical if data is unchanged.
        stamp = max([yahoo['fetched_at'], *[s['fetched_at'] for s in fred.values()]])
        fresh = data_freshness(conn)
        fresh['generated_at'] = stamp
        reference = date.fromisoformat(max(days))
        fresh['expected_session_date'] = reference.isoformat()
        from app.services.calendar import missed_sessions
        for r in fresh['instruments']:
            observed = date.fromisoformat(r['latest_date']) if r['latest_date'] else None
            r['age_days'] = (reference-observed).days if observed else None
            if r['source']=='fred': r.update(macro_data.freshness(r['symbol'],observed,reference,expected_session=reference))
            else:
                lag=missed_sessions(observed,reference) if observed else None
                r.update(missing_sessions=lag,is_stale=bool(lag),status='unavailable' if observed is None else 'stale' if lag else 'fresh')
        for r in fresh['sources']:
            r['age_days']=(reference-date.fromisoformat(r['latest_date'])).days
            members=[v for v in fresh['instruments'] if v['source']==r['source']]
            r['is_stale']=any(v['is_stale'] for v in members)
            r['status']='partial' if any(v['status']=='unavailable' for v in members) else 'stale' if r['is_stale'] else 'fresh'
        payload = {'version':artifact.VERSION, 'built_at':stamp, 'fetched_at':stamp, 'as_of':max(days),
                   'days':days, 'history':points, 'series':sources, 'freshness':fresh,
                   'stability_sensitivity':regimes['stability_sensitivity'],
                   'regime_v2_baselines':model['baselines'], 'regime_v2_history':[{k:r[k] for k in ('date','quadrant','raw_quadrant','stress_label','axis_scores','days_in_regime','emerging_label','emerging_days')} for r in model['snapshots']]}
    encoded = gzip.compress(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),mtime=0)
    artifact.PATH.write_bytes(encoded)
    print(f'Daily artifact: {len(days)} dates, {len(encoded):,} compressed bytes')

if __name__ == '__main__':
    build()
