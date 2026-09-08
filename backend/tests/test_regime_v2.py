from datetime import date
import json
import math
from pathlib import Path
import pytest
from app.data import database
from app.services import regime_v2 as model, analytics, market_data, macro_data, artifact

@pytest.fixture(scope='module')
def recorded_history():
    with database.session(':memory:') as conn:
        database.init_schema(conn)
        market_data.populate_database(conn,market_data.validate_snapshot(json.loads(market_data.SNAPSHOT_PATH.read_text())),'snapshot')
        macro_data.populate_database(conn,macro_data.read_snapshot(),{})
        yield analytics.MarketHistory(conn)


def test_percentile_midrank_and_constant_series():
    assert model.percentile(1,[1,1,1])==50
    assert model.percentile(2,[1,2,2,3])==50
    assert model.percentile(9,[1,2,3])==100
    assert model.percentile(0,[1,2,3])==0
    assert model.percentile(1,[]) is None


def test_single_axis_weights_and_quadrants():
    assert len(model.SPECS)==18
    assert len({key for key in model.SPECS})==18
    assert model.quadrant(50,49)=='Goldilocks'
    assert model.quadrant(50,50)=='Reflation'
    assert model.quadrant(49,50)=='Stagflation'
    assert model.quadrant(49,49)=='Slowdown'
    assert [model.stress_label(x) for x in (59.9,60,79.9,80)]==['Calm','Elevated','Elevated','Stressed']


def test_confidence_uses_magnitude_agreement_and_official_quadrant():
    signals=[{'axis':'Growth','percentile':80},{'axis':'Inflation','percentile':20}]
    result=model.confidence(80,20,signals,'Goldilocks')
    assert result['magnitude']==60 and result['agreement']==100 and result['score']==80
    assert result['label']=='High'
    waiting=model.confidence(80,20,signals,'Slowdown')
    assert waiting['magnitude']==0 and waiting['agreement']==50


def test_releases_never_enter_history_early(recorded_history):
    inputs=model.Inputs(recorded_history)
    for symbol,observed,release in [('ICSA','2026-09-19','2026-09-24'),('NFCI','2026-09-25','2026-09-30'),('CPI_INDEX','2026-08-01','2026-09-15'),('DGS2','2026-09-29','2026-09-30')]:
        assert macro_data.available_on(symbol,date.fromisoformat(observed)).isoformat()==release
        before=date.fromordinal(date.fromisoformat(release).toordinal()-1)
        assert all(row['date'].isoformat()<observed for row in inputs.macro_rows(symbol,before))
    feb=inputs.features(date(2026,2,17),model.Config())['cpi_acceleration']
    assert feb['held_for_missing_month']
    assert feb['observations']['CPIAUCSL']=='2025-12-01'
    # Weekend publication approximation rolls forward for CPI.
    assert macro_data.available_on('CPI_INDEX',date(2026,1,1))==date(2026,2,17)


def test_weekly_freshness_does_not_use_stock_session_age():
    assert not macro_data.freshness('NFCI',date(2026,9,25),date(2026,10,1))['is_stale']
    assert macro_data.freshness('ICSA',date(2026,9,12),date(2026,10,1))['is_stale']


def test_recorded_history_is_deterministic_and_all_signals_are_complete(recorded_history):
    a=model.build(recorded_history)
    b=model.build(recorded_history)
    assert a==b and len(a['snapshots'])==252
    assert [r['date'] for r in a['snapshots']]==[r['date'].isoformat() for r in recorded_history.price_frames['SPY'][-252:]]
    for row in a['snapshots']:
        assert len(row['signals'])==18
        for axis in model.FAMILIES:
            signals=[s for s in row['signals'] if s['axis']==axis]
            assert sum(s['weight'] for s in signals)==pytest.approx(1)
            assert row['axis_scores'][axis]==pytest.approx(sum(s['weight']*s['percentile'] for s in signals))
        assert all(s['baseline_count']==756 and s['available_on']<=row['date'] for s in row['signals'])
        assert row['days_in_regime']>=1
    # Bundled artifact is reproducible from the recorded provider inputs.
    bundle=artifact.decode(artifact.PATH.read_bytes())
    assert bundle.selected()['regime_v2']==a['snapshots'][-1]


def test_nearest_flip_inversion_crosses_the_claimed_boundary(recorded_history):
    bundle=model.build(recorded_history)
    row=bundle['snapshots'][-1]
    by_key={s['key']:s for s in row['signals']}
    assert 2<=len(row['nearest_flips'])<=3
    for flip in row['nearest_flips']:
        s=by_key[flip['key']]
        p=model.percentile(flip['target_raw'],bundle['baselines'][flip['key']])
        if s['inverse']: p=100-p
        score=row['axis_scores'][s['axis']]+s['weight']*(p-s['percentile'])
        assert score==pytest.approx(flip['composite_after'])
        assert score>=flip['boundary'] if flip['increasing'] else score<flip['boundary']
    # Tied distributions and impossible single-input changes are explicit.
    assert model.invert_rank([2]*10,2,75,False,True)>2
    assert model.invert_rank([2]*10,2,101,False,True) is None


def test_current_observation_excluded_from_reference_distribution(recorded_history):
    bundle=model.build(recorded_history)
    inputs=model.Inputs(recorded_history)
    days=[r['date'] for r in recorded_history.price_frames['SPY']]
    vix=[inputs.features(day,model.Config())['vix']['value'] for day in days[-757:-1]]
    assert bundle['baselines']['vix']==vix
