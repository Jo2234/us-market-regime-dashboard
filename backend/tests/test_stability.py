from app.services.stability import stabilize, changes
import pytest
from datetime import date, timedelta


def rows(labels):
    day = date(2026, 9, 1)
    result = []
    for label in labels:
        while day.weekday() > 4 or day == date(2026,9,7):
            day += timedelta(days=1)
        result.append({'date':day.isoformat(),'regime_label':label})
        day += timedelta(days=1)
    return result


def test_persistence_resets_and_switches_only_on_fifth_observation():
    result = stabilize(rows(['a','b','b','a','b','b','b','b','b']))
    assert [r['official_label'] for r in result] == ['a']*8+['b']
    assert result[2]['emerging_label'] == 'b' and result[2]['emerging_days'] == 2
    assert result[3]['emerging_label'] is None
    assert result[7]['days_in_regime'] == 8
    assert result[8]['days_in_regime'] == 1 and result[8]['emerging_label'] is None
    assert changes(result) == 1


def test_different_candidate_missing_observation_and_strong_override():
    original = rows(['a','b','b','c','c','c'])
    result = stabilize(original)
    assert result[-1]['emerging_days'] == 3
    result = stabilize(original, strong=lambda r:r['regime_label']=='c')
    assert result[3]['strong_override'] and result[3]['official_label']=='c'
    assert 'official_label' not in original[0]
    original[3]['date'] = '2026-09-11'; original = original[:4]
    assert stabilize(original)[-1]['emerging_days'] == 1
    with pytest.raises(ValueError): stabilize([original[0], original[0]])


def test_sensitivity_counts_do_not_change_fixed_default():
    data = rows(['a']+['b']*4+['a']*5+['b']*10)
    assert changes(stabilize(data,persistence=3)) == 3
    assert changes(stabilize(data,persistence=5)) == 1
    assert changes(stabilize(data,persistence=10)) == 1
    assert stabilize(data) == stabilize(data,persistence=5)
