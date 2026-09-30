import json
from datetime import date
from pathlib import Path

from app.services import analytics, market_data, macro_data, regime_history
from app.ingestion.yahoo import normalize_chart
from app.data.instruments import YAHOO_TICKERS


def load_recorded(conn):
    fixtures = Path(__file__).parent / 'fixtures'
    snapshot = {'version': 1, 'fetched_at': '2026-09-29T00:00:00Z', 'series': {
        s: {'source': 'yahoo_finance', 'yahoo_ticker': t, 'bars': normalize_chart(s, json.loads((fixtures / f'{s}.json').read_text()), date(2026,9,28))}
        for s,t in YAHOO_TICKERS.items()}}
    market_data.populate_database(conn, snapshot, 'snapshot')
    return analytics.MarketHistory(conn)


def test_year_history_determinism_cache_and_previous(empty_conn, monkeypatch, tmp_path):
    history = load_recorded(empty_conn)
    monkeypatch.setattr(regime_history, 'SNAPSHOT_PATH', tmp_path / 'missing.json')
    regime_history._cache.clear()
    bundle, stats = regime_history.get_history(empty_conn, history)
    assert 245 <= len(bundle['snapshots']) <= 255
    assert stats['cache'] == 'miss'
    rebuilt, _ = regime_history.build(empty_conn, history)
    assert rebuilt == bundle
    assert all('No prior' not in row['signals']['what_changed'] for row in bundle['snapshots'])
    def forbidden(*args):
        raise AssertionError('History must not be recomputed for unchanged observations')
    monkeypatch.setattr(regime_history, 'build', forbidden)
    assert regime_history.get_history(empty_conn, history)[1]['cache'] == 'hit'
    assert empty_conn.execute('SELECT COUNT(*) FROM regime_snapshots').fetchone()[0] == 0
    selected, points, _ = regime_history.for_date(empty_conn, history, date(2026, 6, 1))
    assert selected['date'] == points[-1]['date'] == '2026-06-01'


def test_macro_publication_lags_and_revised_vintage(empty_conn):
    assert macro_data.available_on('CPI_YOY', date(2026,8,1)) == date(2026,9,15)
    assert macro_data.available_on('UNRATE', date(2026,8,1)) == date(2026,9,4)
    assert macro_data.available_on('FEDFUNDS', date(2026,9,4)) == date(2026,9,8)  # Labor Day
    assert macro_data.available_on('CPI_YOY', date(2025,12,1)) == date(2026,1,15)
    from app.data.database import insert_macro_rows
    insert_macro_rows(empty_conn, [{'id': f'CPI:{month}', 'instrument_id': 'CPI_YOY', 'date': f'2026-{month}-01', 'value': value, 'source': 'fred'} for month,value in [('07',2.4),('08',3.35)]])
    history = analytics.MarketHistory(empty_conn)
    assert analytics.latest_macro_value(history, 'CPI_YOY', date(2026,9,14), published=True)['value'] == 2.4
    assert analytics.latest_macro_value(history, 'CPI_YOY', date(2026,9,15), published=True)['value'] == 3.35
    # The observation date stays August; we do not rewrite it as a release date.
    assert analytics.latest_macro_value(history, 'CPI_YOY', date(2026,9,15), published=True)['date'] == '2026-08-01'


def test_saved_history_reused_only_for_matching_inputs(empty_conn, monkeypatch, tmp_path):
    history = load_recorded(empty_conn)
    bundle, _ = regime_history.build(empty_conn, history)
    path = tmp_path / 'regimes.json'; path.write_text(json.dumps(bundle))
    monkeypatch.setattr(regime_history, 'SNAPSHOT_PATH', path)
    regime_history._cache.clear()
    assert regime_history.get_history(empty_conn, history)[1]['cache'] == 'snapshot'
    history.prices['SPY'][-1]['adjusted_close'] += 1
    assert regime_history.fingerprint(history) != bundle['fingerprint']
