import copy
import gzip
import hashlib
import json
from datetime import datetime, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from app.services import artifact, market_data, macro_data, regime_history
from app.services.calendar import next_session, session_close
from datetime import date, timedelta


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def bundle(as_of, built_at='2026-10-01T21:00:00+00:00'):
    return artifact.Artifact({'as_of': as_of, 'built_at': built_at, 'days': {as_of: {}}})


def small_payload(as_of='2026-10-01', built_at='2026-10-01T21:00:00+00:00', symbols=('SPY', 'DGS10')):
    day = {'regime': {}, 'macro_summary': {}, 'rates_summary': {}, 'performance_windows': {}}
    return {'version': artifact.VERSION, 'as_of': as_of, 'built_at': built_at, 'fetched_at': built_at,
            'days': {'2026-09-30': day, as_of: day}, 'history': [],
            'series': {s: [{'date': as_of, 'source': 'fred' if s.startswith('DGS') else 'yahoo_finance'}] for s in symbols},
            'freshness': {'instruments': [{'symbol': 'SPY', 'source': 'yahoo_finance', 'latest_date': as_of}], 'sources': []}}


def encode(payload):
    return gzip.compress(json.dumps(payload).encode(), mtime=0)


def remote(monkeypatch, payload=None, *, listed=None, content=None, fail=False):
    """Fake GitHub main: records each URL fetched instead of opening a socket."""
    calls = []
    content = content if content is not None else encode(payload) if payload else None
    if listed is None and payload:
        listed = {'version': 1, 'as_of': payload['as_of'], 'built_at': payload['built_at'], 'sha256': hashlib.sha256(content).hexdigest()}
    def download(url=artifact.REMOTE, timeout=1.5):
        calls.append(url)
        if fail:
            raise httpx.ConnectError('offline')
        return json.dumps(listed).encode() if url == artifact.MANIFEST_REMOTE else content
    monkeypatch.setattr(artifact, '_download', download)
    return calls


@pytest.fixture()
def local_artifact(monkeypatch, tmp_path):
    path = tmp_path / 'dashboard_artifact.json.gz'
    path.write_bytes(encode(small_payload()))
    monkeypatch.setattr(artifact, 'PATH', path)
    monkeypatch.setattr(artifact, '_cached', None)
    monkeypatch.setattr(artifact, '_checked', 0)
    return path


def at(monkeypatch, clock):
    monkeypatch.setenv('MARKET_REGIME_CLOCK', clock)


# --- research delivery boundaries -----------------------------------------------------------

@pytest.mark.parametrize('clock,as_of,status,expected', [
    ('2026-10-02T19:59:59', '2026-10-01', 'current', '2026-10-01'),   # Friday, one second before 16:00 EDT
    ('2026-10-02T20:00:00', '2026-10-01', 'pending', '2026-10-02'),   # at the official close
    ('2026-10-02T21:59:59', '2026-10-01', 'pending', '2026-10-02'),   # last second of the delivery window
    ('2026-10-02T22:00:00', '2026-10-01', 'overdue', '2026-10-02'),   # deadline reached
    ('2026-10-02T22:00:00', '2026-10-02', 'current', '2026-10-02'),   # after delivery
    ('2026-10-03T12:00:00', '2026-10-02', 'current', '2026-10-02'),   # Saturday
    ('2026-10-04T23:00:00', '2026-10-01', 'overdue', '2026-10-02'),   # Sunday, Friday never arrived
    ('2026-11-26T19:00:00', '2026-11-25', 'current', '2026-11-25'),   # Thanksgiving holiday
    ('2026-11-27T17:59:59', '2026-11-25', 'current', '2026-11-25'),   # 13:00 EST early close pending
    ('2026-11-27T18:00:00', '2026-11-25', 'pending', '2026-11-27'),
    ('2026-11-27T20:00:00', '2026-11-25', 'overdue', '2026-11-27'),   # early-close deadline 20:00 UTC
    ('2026-11-02T20:30:00', '2026-10-30', 'current', '2026-10-30'),   # EST: 20:30 UTC precedes the close
    ('2026-11-02T21:00:00', '2026-10-30', 'pending', '2026-11-02'),
    ('2026-11-02T22:59:59', '2026-10-30', 'pending', '2026-11-02'),
    ('2026-11-02T23:00:00', '2026-10-30', 'overdue', '2026-11-02'),
    ('2026-03-09T20:00:00', '2026-03-06', 'pending', '2026-03-09'),   # first EDT session after DST
])
def test_delivery_status_uses_official_close_and_deadline(clock, as_of, status, expected):
    result = artifact.delivery_status(bundle(as_of), utc(clock))
    assert result['status'] == status and result['expected_session'] == expected
    assert result['fresh'] is (status != 'overdue')
    assert result['pending'] is (status == 'pending') and result['overdue'] is (status == 'overdue')
    assert result['as_of'] == as_of and result['evaluated_at'] == utc(clock).isoformat()


def test_delivery_deadlines_are_auditable():
    pending = artifact.delivery_status(bundle('2026-11-25'), utc('2026-11-27T18:30:00'))
    assert pending['expected_session_close'] == '2026-11-27T18:00:00+00:00'
    assert pending['delivery_deadline'] == '2026-11-27T20:00:00+00:00'
    assert pending['overdue_since'] is None and pending['missing_sessions'] == 1
    late = artifact.delivery_status(bundle('2026-09-30'), utc('2026-10-02T21:00:00'))
    # Thursday's deadline already passed while Friday's window is still open: overdue, not pending.
    assert late['status'] == 'overdue' and late['missing_sessions'] == 2
    assert late['overdue_since'] == '2026-10-01T22:00:00+00:00'
    current = artifact.delivery_status(bundle('2026-10-02'), utc('2026-10-03T12:00:00'))
    assert current['next_session'] == '2026-10-05' and current['next_delivery_deadline'] == '2026-10-05T22:00:00+00:00'
    assert current['grace_seconds'] == 7200


def test_rows_distinguish_pending_from_overdue_without_hiding_dates():
    real = artifact.decode(artifact.PATH.read_bytes())
    as_of = real.payload['as_of']
    expected = next_session(date.fromisoformat(as_of)).isoformat()
    close = session_close(date.fromisoformat(expected))
    pending = artifact.freshness(real, close + timedelta(minutes=30))
    overdue = artifact.freshness(real, close + timedelta(hours=2))
    assert pending['artifact_status'] == 'pending' and overdue['artifact_status'] == 'overdue'
    assert pending['expected_session_date'] == expected and pending['required_session_date'] == as_of
    for p, o in zip(pending['instruments'], overdue['instruments']):
        assert p['latest_date'] == o['latest_date']           # true observation dates retained
        if p['source'] == 'yahoo_finance' and p['latest_date'] == as_of:
            assert p['is_stale'] and p['status'] == 'stale' and p['missing_sessions'] == 1
            assert p['delivery_state'] == 'pending' and not p['is_overdue']
            assert o['delivery_state'] == 'overdue' and o['is_overdue']
    yahoo = {s['source']: s for s in pending['sources']}['yahoo_finance']
    assert yahoo['is_stale'] and yahoo['status'] == 'stale' and yahoo['delivery_state'] == 'pending'
    assert {s['source']: s for s in overdue['sources']}['yahoo_finance']['delivery_state'] == 'overdue'
    current = artifact.freshness(real)
    assert all(r['delivery_state'] in ('current', 'unavailable') or r['source'] == 'fred' for r in current['instruments'])


# --- bounded visitor retrieval --------------------------------------------------------------

def test_artifact_rejects_wrong_version_and_unverified_sources():
    payload = small_payload()
    payload['version'] = 999
    with pytest.raises(ValueError):
        artifact.decode(encode(payload))
    payload['version'] = artifact.VERSION
    payload['series']['SPY'][0]['source'] = 'unverified'
    with pytest.raises(ValueError):
        artifact.decode(encode(payload))


@pytest.mark.parametrize('mutate', [
    lambda p: p.pop('freshness'),
    lambda p: p['days'].update({p['as_of']: {'regime': {}}}),
    lambda p: p.update(built_at='not a time'),
])
def test_artifact_rejects_incomplete_payloads(mutate):
    payload = small_payload()
    mutate(payload)
    with pytest.raises((ValueError, KeyError)):
        artifact.decode(encode(payload))


def test_manifest_matches_committed_artifact():
    content = artifact.PATH.read_bytes()
    assert json.loads(artifact.MANIFEST_PATH.read_text()) == artifact.manifest(content)


def test_cold_request_only_loads_recorded_artifact(monkeypatch):
    from app.main import app
    def forbidden(*args, **kwargs):
        raise AssertionError('Daily work must never run in a visitor request')
    monkeypatch.setattr(market_data, 'get_snapshot', forbidden)
    monkeypatch.setattr(macro_data, 'get_snapshot', forbidden)
    monkeypatch.setattr(regime_history, 'build', forbidden)
    monkeypatch.setattr(artifact, '_download', forbidden)
    monkeypatch.setattr(artifact, '_cached', None)
    from app.services import live_quotes
    monkeypatch.setattr(live_quotes, 'get_quotes', lambda **kw: ({}, {'cache':'closed'}))
    client = TestClient(app)
    response = client.get('/api/dashboard/summary')
    assert response.status_code == 200
    result = response.json()
    assert result['cache'] == 'miss' and client.get('/api/dashboard/summary').json()['cache'] == 'hit'
    assert result['artifact_delivery']['fresh'] and result['artifact_delivery']['status'] == 'current'
    assert result['artifact_delivery']['origin'] == 'bundled' and result['artifact_delivery']['view'] == 'latest'
    assert result['data_freshness']['artifact_status'] == 'current'
    assert result['fetch_diagnostics']['daily_provider_requests'] == 0
    assert result['history_delivery']['compute_ms'] == 0
    assert len(result['historical_regimes']) == 252
    assert 'demo_seed' not in response.text
    assert result['rates_summary']['spreads']['10y_2y'] is not None


def test_expired_artifact_survives_remote_failure(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-03T12:00:00Z')   # Friday's session overdue
    calls = remote(monkeypatch, fail=True)
    first, _ = artifact.load()
    second, mode = artifact.load()
    assert first.payload == second.payload and mode == 'stale'
    assert first.payload['as_of'] == '2026-10-01' and first.origin == 'bundled'
    assert calls == [artifact.MANIFEST_REMOTE]   # throttled: one attempt per 15 minutes


def test_pending_artifact_checks_manifest_and_adopts_newer_validated_remote(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-02T20:30:00Z')
    newer = small_payload('2026-10-02', '2026-10-02T20:20:00+00:00')
    calls = remote(monkeypatch, newer)
    bundle_, mode = artifact.load()
    assert bundle_.payload['as_of'] == '2026-10-02' and bundle_.origin == 'github_main'
    assert calls == [artifact.MANIFEST_REMOTE, artifact.REMOTE]
    assert artifact.delivery_status(bundle_)['status'] == 'current' and mode == 'miss'


def test_current_artifact_never_contacts_remote(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-02T19:00:00Z')
    calls = remote(monkeypatch, small_payload('2026-10-02', '2026-10-02T20:20:00+00:00'))
    artifact.load()
    assert calls == []


def test_unchanged_or_older_manifest_skips_artifact_download(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-03T12:00:00Z')
    for listed in ({'version': 1, 'as_of': '2026-10-01', 'built_at': '2026-10-01T21:00:00+00:00', 'sha256': 'x'},
                   {'version': 1, 'as_of': '2026-09-30', 'built_at': '2026-10-02T21:00:00+00:00', 'sha256': 'x'}):
        monkeypatch.setattr(artifact, '_checked', 0)
        calls = remote(monkeypatch, listed=listed, content=b'')
        assert artifact.load()[0].payload['as_of'] == '2026-10-01'
        assert calls == [artifact.MANIFEST_REMOTE]


@pytest.mark.parametrize('case', ['sha_mismatch', 'drops_instrument', 'incomplete', 'not_gzip', 'truncated_gzip', 'manifest_lies', 'drops_freshness', 'future_session'])
def test_bad_remote_artifacts_are_rejected(monkeypatch, local_artifact, case):
    at(monkeypatch, '2026-10-03T12:00:00Z')
    newer = small_payload('2026-10-02', '2026-10-02T21:00:00+00:00')
    if case == 'drops_instrument':
        newer = small_payload('2026-10-02', '2026-10-02T21:00:00+00:00', symbols=('SPY',))
    if case == 'incomplete':
        del newer['days']['2026-10-02']['regime']
    if case == 'drops_freshness':
        newer['freshness']['instruments'][0]['symbol'] = 'FAKE'
    if case == 'future_session':
        newer = small_payload('2026-10-05', '2026-10-05T21:00:00+00:00')
    content = b'not gzip' if case == 'not_gzip' else encode(newer)
    if case == 'truncated_gzip':
        content = content[:20]
    listed = {'version': 1, 'as_of': newer['as_of'], 'built_at': newer['built_at'], 'sha256': hashlib.sha256(content).hexdigest()}
    if case == 'sha_mismatch':
        listed['sha256'] = '0' * 64
    if case == 'manifest_lies':
        listed['built_at'] = '2026-10-02T23:00:00+00:00'
    remote(monkeypatch, listed=listed, content=content)
    result, _ = artifact.load()
    assert result.payload['as_of'] == '2026-10-01' and result.origin == 'bundled'
    assert artifact.load()[1] == 'stale'


def test_cached_only_bootstrap_never_downloads(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-03T12:00:00Z')
    calls = remote(monkeypatch, fail=True)
    artifact.load(cached_only=True)
    assert calls == []


def test_retry_resumes_after_throttle(monkeypatch, local_artifact):
    at(monkeypatch, '2026-10-03T12:00:00Z')
    calls = remote(monkeypatch, fail=True)
    clock = [1000.0]
    monkeypatch.setattr(artifact.time, 'monotonic', lambda: clock[0])
    artifact.load()
    clock[0] += artifact.RETRY_SECONDS - 1
    artifact.load()
    clock[0] += 1
    artifact.load()
    assert len(calls) == 2


# --- API --------------------------------------------------------------------------------------

def api(monkeypatch, clock, quotes=({}, {'cache': 'closed'})):
    from app.main import app
    from app.services import live_quotes
    at(monkeypatch, clock)
    monkeypatch.setattr(artifact, '_cached', None)
    monkeypatch.setattr(artifact, '_checked', 0)
    remote(monkeypatch, fail=True)
    monkeypatch.setattr(live_quotes, 'get_quotes', lambda **kw: quotes)
    return TestClient(app)


def test_api_reports_pending_consistently(monkeypatch):
    as_of = artifact.decode(artifact.PATH.read_bytes()).payload['as_of']
    expected = next_session(date.fromisoformat(as_of))
    close = session_close(expected)
    result = api(monkeypatch, (close + timedelta(minutes=30)).isoformat()).get('/api/dashboard/summary').json()
    delivery = result['artifact_delivery']
    assert delivery['status'] == 'pending' and delivery['pending'] and delivery['fresh'] and delivery['scheduled']
    assert delivery['as_of'] == as_of == result['as_of'] and delivery['expected_session'] == expected.isoformat()
    assert delivery['delivery_deadline'] == (close + timedelta(hours=2)).isoformat()
    assert result['retry_after_seconds'] == 0 and result['cache'] != 'stale' and result['refresh_pending'] is False
    fresh = result['data_freshness']
    assert fresh['artifact_status'] == 'pending' and fresh['delivery_deadline'] == delivery['delivery_deadline']
    spy = next(r for r in fresh['instruments'] if r['symbol'] == 'SPY')
    assert spy['latest_date'] == as_of and spy['is_stale'] and spy['delivery_state'] == 'pending'


def test_api_overdue_research_with_fresh_live_quote(monkeypatch):
    as_of = date.fromisoformat(artifact.decode(artifact.PATH.read_bytes()).payload['as_of'])
    missed = next_session(as_of)
    live_day = next_session(missed)
    clock = session_close(live_day) - timedelta(hours=2)
    quote = {'SPY': {'source': 'yahoo_finance', 'price': 700.0, 'previous_close': 690.0, 'observed_at': clock.isoformat(),
                     'observation_date': live_day.isoformat(), 'is_current_session': True, 'is_stale': False}}
    client = api(monkeypatch, clock.isoformat(), (quote, {'cache': 'miss', 'fetched_at': clock.isoformat()}))
    result = client.get('/api/dashboard/summary').json()
    assert result['market_status']['is_open'] and result['live_quotes']['SPY']['is_current_session']
    assert result['quote_delivery']['cache'] == 'miss'
    delivery = result['artifact_delivery']
    assert delivery['status'] == 'overdue' and not delivery['fresh']
    assert delivery['overdue_since'] == (session_close(missed) + timedelta(hours=2)).isoformat()
    assert result['cache'] == 'stale' and result['retry_after_seconds'] == artifact.RETRY_SECONDS
    assert result['data_freshness']['artifact_status'] == 'overdue'
    assert client.get('/api/data/freshness').json()['artifact_status'] == 'overdue'


def test_api_historical_request_is_labeled_historical(monkeypatch):
    bundle_ = artifact.decode(artifact.PATH.read_bytes())
    requested = bundle_.dates[-10]
    next_day = next_session(date.fromisoformat(bundle_.payload['as_of']))
    clock = session_close(next_day) + timedelta(minutes=30)
    result = api(monkeypatch, clock.isoformat()).get(f'/api/dashboard/summary?date={requested}').json()
    assert result['as_of'] == requested and result['quote_delivery'] == {'cache': 'historical'}
    delivery = result['artifact_delivery']
    assert delivery['view'] == 'historical' and delivery['requested_date'] == requested
    assert delivery['status'] == 'pending'   # still describes the artifact, not the historical view
    assert all('delivery_state' not in item for item in result['macro_summary'].values() if item)


def test_sector_endpoint_preserves_requested_window_order():
    from app.main import create_app
    with TestClient(create_app()) as client:
        daily = client.get('/api/sectors/performance?windows=1d').json()
        monthly = client.get('/api/sectors/performance?windows=1m').json()
    assert daily['windows'] == ['1d']
    assert [r['symbol'] for r in daily['sectors']] != [r['symbol'] for r in monthly['sectors']]
    values = [r['returns']['1d'] for r in daily['sectors']]
    assert values == sorted(values, reverse=True)
    assert all(set(r['returns']) == {'1d'} and set(r['relative_to_spy']) == {'1d'} for r in daily['sectors'])


def test_secondary_context_preserves_staleness_without_affecting_source_group():
    real = artifact.decode(artifact.PATH.read_bytes())
    fresh = artifact.freshness(real)
    source = next(r for r in fresh['sources'] if r['source'] == 'fred')
    rows = [r for r in fresh['instruments'] if r['source'] == 'fred' and r.get('affects_group_freshness', True)]
    assert source['is_stale'] == any(r['is_stale'] for r in rows)
    assert source['is_overdue'] == any(r['delivery_state'] == 'overdue' for r in rows)


@pytest.mark.parametrize('replacement', [[], None, {'version': 1, 'days': [], 'series': {}}])
def test_invalid_artifact_shape_is_a_validation_error(replacement):
    with pytest.raises(ValueError):
        artifact.decode(gzip.compress(json.dumps(replacement).encode()))
