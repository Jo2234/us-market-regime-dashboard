"""Real ledger/state machine, fake gh/launchctl only; no dispatch or install."""
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dispatch_watchdog', ROOT / 'scripts/dispatch_watchdog.py')
w = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = w
spec.loader.exec_module(w)


def utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


@pytest.fixture
def calendar():
    return w.Calendar.load()


def run(slot='close-2026-10-02-a', status='queued', conclusion=None, created='2026-10-02T20:30:00Z', identity=7):
    return {'databaseId': identity, 'status': status, 'conclusion': conclusion, 'event': 'workflow_dispatch',
            'createdAt': created, 'updatedAt': created, 'headBranch': 'main',
            'displayTitle': f'Refresh market and macro snapshots (watchdog:{slot})', 'url': 'https://example.invalid/7'}


class FakeGitHub:
    def __init__(self, runs=None, result=None, manifest=None):
        self.rows = [] if runs is None else runs
        self.result = result or w.Result(0)
        self.listed = manifest
        self.calls = []

    def runs(self):
        self.calls.append('runs')
        return self.rows

    def manifest(self):
        self.calls.append('manifest')
        return self.listed

    def dispatch(self, reason):
        self.calls.append(('dispatch', reason))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def dispatches(github):
    return [v for v in github.calls if isinstance(v, tuple)]


@pytest.mark.parametrize('day, closes', [
    ('2026-10-02', ['20:30', '21:30']), ('2026-11-02', ['21:30', '22:30']),
    ('2026-11-27', ['18:30', '19:30']), ('2026-11-26', []), ('2026-10-03', []),
    ('2026-03-09', ['20:30', '21:30']),
])
def test_nyse_close_slots_dst_early_close_holiday_weekend(calendar, day, closes):
    slots = w.slots_between(calendar, utc(day + 'T00:00:00Z'), utc(day + 'T23:59:59Z'))
    assert [s.at.strftime('%H:%M') for s in slots if s.kind == 'close'] == closes
    assert [s.at.strftime('%H:%M') for s in slots if s.kind == 'fred'] == ([] if date.fromisoformat(day).weekday() >= 5 else ['14:07'])


def test_due_boundary_dedupe_restart_and_idle_economy(tmp_path, calendar):
    github = FakeGitHub()
    at = utc('2026-10-02T20:30:00Z')
    state, _ = w.tick(tmp_path, github, calendar, at)
    key = 'close-2026-10-02-a'
    assert state['slots'][key]['status'] == 'requested'
    assert state['slots'][key]['expected_as_of'] == '2026-10-02'
    assert len(dispatches(github)) == 1
    github.rows = [run(status='completed', conclusion='success')]
    github.listed = {'as_of': '2026-10-02', 'built_at': '2026-10-02T20:32:00Z'}
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=3))
    assert state['slots'][key]['status'] == 'delivered'
    github.calls.clear()
    w.tick(tmp_path, github, calendar, at + timedelta(minutes=4))
    assert github.calls == []  # Terminal slot has no minute-by-minute API polling.
    assert json.loads((tmp_path / 'state.json').read_text())['slots'][key]['status'] == 'delivered'


def test_wake_coalesces_only_latest_slot_and_old_slots_expire(tmp_path, calendar):
    github = FakeGitHub()
    state, _ = w.tick(tmp_path, github, calendar, utc('2026-10-02T22:00:00Z'))
    assert len(dispatches(github)) == 1
    assert state['slots']['close-2026-10-02-a']['status'] == 'skipped_superseded'
    assert state['slots']['fred-2026-10-02']['status'] == 'skipped_superseded'
    assert state['slots']['close-2026-10-02-b']['status'] == 'requested'
    github.calls.clear()
    w.tick(tmp_path, github, calendar, utc('2026-10-04T12:00:00Z'))
    assert not dispatches(github)  # Do not replay Friday's slots on Sunday.


def test_retry_budget_persisted_backoff(tmp_path, calendar):
    github = FakeGitHub(result=w.Result(1, stderr='HTTP 401 auth failure'))
    at = utc('2026-10-02T20:30:00Z')
    for wait in (0, 120, 300, 600):
        at += timedelta(seconds=wait)
        state, _ = w.tick(tmp_path, github, calendar, at)
    key = 'close-2026-10-02-a'
    assert state['slots'][key]['attempts'] == w.MAX_ATTEMPTS
    assert state['slots'][key]['status'] == 'failed'
    assert len(dispatches(github)) == 4
    w.tick(tmp_path, github, calendar, at + timedelta(minutes=1))
    assert len(dispatches(github)) == 4


def test_timeout_ack_is_uncertain_not_failed_or_delivered(tmp_path, calendar):
    github = FakeGitHub(result=w.Result(124, stderr='timeout'))
    at = utc('2026-10-02T20:30:00Z')
    state, _ = w.tick(tmp_path, github, calendar, at)
    key = 'close-2026-10-02-a'
    assert state['slots'][key]['status'] == 'dispatching'
    assert state['slots'][key]['last_error'] == 'timeout'
    github.rows = None  # API outage gives no evidence of dispatch failure.
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=20))
    assert state['slots'][key]['status'] == 'dispatching'
    assert len(dispatches(github)) == 1
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(hours=4))
    assert state['slots'][key]['status'] == 'untracked'
    assert state['slots'][key]['dispatches'] == 0


def test_crash_persists_intent_and_adopts_exact_run(tmp_path, calendar):
    github = FakeGitHub(result=RuntimeError('simulated crash before ack'))
    at = utc('2026-10-02T20:30:00Z')
    with pytest.raises(RuntimeError):
        w.tick(tmp_path, github, calendar, at)
    key = 'close-2026-10-02-a'
    assert json.loads((tmp_path / 'state.json').read_text())['slots'][key]['status'] == 'dispatching'
    github.result = w.Result(0)
    github.rows = [run(status='in_progress')]
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=3))
    assert state['slots'][key]['status'] == 'requested'
    assert state['slots'][key]['dispatched_at'] == w.iso(at)
    assert state['slots'][key]['run_id'] == 7
    assert len(dispatches(github)) == 1


def test_crash_before_actual_request_recovers_without_immediate_repeat(tmp_path, calendar):
    github = FakeGitHub(result=RuntimeError('crash before request'))
    at = utc('2026-10-02T20:30:00Z')
    with pytest.raises(RuntimeError):
        w.tick(tmp_path, github, calendar, at)
    github.result = w.Result(0)
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=5))
    key = 'close-2026-10-02-a'
    assert state['slots'][key]['status'] == 'dispatching'
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=11))
    assert state['slots'][key]['status'] == 'retry_wait'
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=14))
    assert state['slots'][key]['status'] == 'requested'
    assert len(dispatches(github)) == 2


def test_matching_never_adopts_unrelated_manual_dispatch(calendar):
    now = utc('2026-10-02T20:30:00Z')
    machine = w.Watchdog(w.empty(), FakeGitHub(), calendar, now)
    slot = w.due_slots(calendar, now)[-1]
    record = machine.record(slot)
    record['intent_at'] = w.iso(now)
    unrelated = run(slot='different-slot')
    assert machine.match(slot.id, record, [unrelated]) is None
    exact = run()
    assert machine.match(slot.id, record, [unrelated, exact]) == exact


def test_covering_queued_job_is_tracked_then_failed_job_can_recover(tmp_path, calendar):
    at = utc('2026-10-02T20:30:00Z')
    row = run()
    row.update(event='schedule', displayTitle='Refresh market and macro snapshots')
    github = FakeGitHub(runs=[row])
    state, _ = w.tick(tmp_path, github, calendar, at)
    key = 'close-2026-10-02-a'
    assert state['slots'][key]['status'] == 'requested' and not dispatches(github)
    row.update(status='completed', conclusion='failure')
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=2))
    assert state['slots'][key]['status'] == 'retry_wait'
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=12))
    assert state['slots'][key]['status'] == 'requested'
    assert state['slots'][key]['run_id'] is None  # New intent cannot remain bound to old failed run.
    assert len(dispatches(github)) == 1


@pytest.mark.parametrize('as_of,built,status', [
    ('2026-10-01', '2026-10-02T20:40:00Z', 'succeeded_unchanged'),
    ('2026-10-02', '2026-10-02T19:00:00Z', 'succeeded_unchanged'),
    ('2026-10-02', '2026-10-02T20:40:00Z', 'delivered'),
])
def test_delivery_requires_expected_research_date_and_build_advance(tmp_path, calendar, as_of, built, status):
    at = utc('2026-10-02T20:30:00Z')
    github = FakeGitHub()
    w.tick(tmp_path, github, calendar, at)
    github.rows = [run(status='completed', conclusion='success')]
    github.listed = {'as_of': as_of, 'built_at': built}
    state, _ = w.tick(tmp_path, github, calendar, at + timedelta(minutes=12))
    assert state['slots']['close-2026-10-02-a']['status'] == status


def test_daily_cap_and_backward_clock_do_not_dispatch(tmp_path, calendar):
    now = utc('2026-10-02T20:30:00Z')
    state = w.empty()
    state['daily']['2026-10-02'] = w.DAILY_CAP
    github = FakeGitHub()
    machine = w.Watchdog(state, github, calendar, now)
    machine.tick()
    assert state['slots']['close-2026-10-02-a']['status'] == 'skipped_cap'
    assert not github.calls
    state = w.empty()
    state['last_tick'] = w.iso(now + timedelta(minutes=30))
    machine = w.Watchdog(state, github, calendar, now)
    machine.tick()
    assert not state['slots'] and state['last_tick'] == w.iso(now + timedelta(minutes=30))
    assert any('paused' in message for message in machine.messages)
    assert not github.calls


def test_large_backward_clock_rebases_instead_of_halting(calendar):
    now = utc('2026-10-02T20:30:00Z')
    state = w.empty()
    state['last_tick'] = w.iso(now + timedelta(days=4))    # written once under a wrong future clock
    state['slots']['close-2026-10-06-b'] = {'kind': 'close', 'scheduled_at': '2026-10-06T21:30:00+00:00',
                                            'status': 'expired', 'attempts': 0, 'dispatches': 0}
    github = FakeGitHub()
    machine = w.Watchdog(state, github, calendar, now)
    machine.tick()
    assert 'close-2026-10-06-b' not in state['slots']       # the real future slot is not pre-consumed
    assert state['slots']['close-2026-10-02-a']['status'] == 'dispatching'
    assert state['last_tick'] == w.iso(now) and any('trusting' in m for m in machine.messages)
    bogus = w.empty()
    bogus['last_tick'] = w.iso(now)
    machine = w.Watchdog(bogus, FakeGitHub(), calendar, utc('2001-01-02T14:07:00Z'))
    machine.tick()
    assert not bogus['slots'] and any('paused' in m for m in machine.messages)


def test_atomic_ledger_lock_corruption_hold_and_temp_recovery(tmp_path, calendar):
    now = utc('2026-10-02T20:30:00Z')
    with w.Ledger(tmp_path) as ledger:
        with pytest.raises(w.Busy):
            with w.Ledger(tmp_path):
                pass
        ledger.write(w.empty())
    assert json.loads((tmp_path / 'state.json').read_text())['version'] == w.VERSION
    (tmp_path / '.state-interrupted.tmp').write_text('partial')
    (tmp_path / 'state.json').write_text('{broken')
    github = FakeGitHub()
    state, messages = w.tick(tmp_path, github, calendar, now)
    assert not dispatches(github)
    assert state['recovered_from'] and state['dispatch_hold_until']
    assert list(tmp_path.glob('state.corrupt-*.json'))
    assert not (tmp_path / '.state-interrupted.tmp').exists()
    assert any('corrupt ledger' in line for line in messages)
    w.validate(state)


@pytest.mark.parametrize('mutate', [
    lambda s: s.update(events='not a list'),
    lambda s: s.update(daily={'2026-10-02': -1}),
    lambda s: s.update(slots={'unsafe-id': {'status': 'new'}}),
    lambda s: s.update(slots={'fred-2026-10-02': {'status': 'new', 'attempts': -1, 'scheduled_at': '2026-10-02T14:07:00Z'}}),
    lambda s: s.update(slots={'fred-2026-10-02': {'status': 'requested', 'scheduled_at': '2026-10-02T14:07:00Z'}}),
])
def test_malformed_ledger_rejected(mutate):
    state = w.empty()
    mutate(state)
    with pytest.raises(ValueError):
        w.validate(state)


def test_gh_boundary_filters_branch_uses_array_args_and_no_secret_env(monkeypatch):
    rows = [run(), {**run(identity=8), 'headBranch': 'feature'}, {**run(identity=9), 'createdAt': None}]
    calls = []
    def runner(args, timeout):
        calls.append(args)
        return w.Result(0, json.dumps(rows))
    github = w.GitHub('/fake gh', w.DEFAULT_REPO, w.DEFAULT_WORKFLOW, runner)
    assert len(github.runs()) == 1
    github.dispatch('watchdog:close-2026-10-02-a')
    assert calls[-1][-1] == 'reason=watchdog:close-2026-10-02-a'
    monkeypatch.setenv('GH_TOKEN', 'offline-placeholder-never-forwarded')
    seen = []
    def subprocess_run(args, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
    monkeypatch.setattr(subprocess, 'run', subprocess_run)
    w.run_process(['/fake gh', 'run', 'list'], 4)
    assert 'GH_TOKEN' not in seen[0]['env'] and 'GITHUB_TOKEN' not in seen[0]['env']
    assert seen[0]['timeout'] == 4 and seen[0]['stdin'] is subprocess.DEVNULL


def test_missing_gh_and_timeout_are_bounded(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert w.run_process(['/missing gh'], 5).code == 127
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('gh', 5)))
    assert w.run_process(['/fake gh'], 5).code == 124
    assert '[redacted]' in w.redact('Authorization=secret ghp_offline_example_token')
    assert 'offline_example_token' not in w.redact('ghp_offline_example_token')


def test_plist_install_uninstall_are_mocked_and_preserve_unrelated_files(tmp_path, monkeypatch):
    target = tmp_path / 'agents/watchdog.plist'
    monkeypatch.setattr(w, 'plist_path', lambda: target)
    monkeypatch.setattr(w, 'check_install', lambda *args: [])
    state = tmp_path / 'state with spaces'
    args = SimpleNamespace(checkout=str(ROOT), python=sys.executable, gh='/fake gh', allow_temp_checkout=True,
                           skip_auth_check=True, state_dir=str(state), repo=w.DEFAULT_REPO,
                           workflow=w.DEFAULT_WORKFLOW, no_load=False)
    calls = []
    runner = lambda args, timeout: calls.append(args) or w.Result(0)
    assert w.install(args, runner) == 0
    parsed = plistlib.loads(target.read_bytes())
    assert parsed['StartInterval'] == 60 and parsed['RunAtLoad']
    assert parsed['ProgramArguments'][0] == sys.executable
    assert str(state) in parsed['ProgramArguments']
    assert any('bootstrap' in command for command in calls)
    calls.clear()
    outcomes = iter([w.Result(5, '', 'Bootstrap failed: 5: Input/output error'), w.Result(0)])
    flaky = lambda args, timeout: calls.append(args) or (next(outcomes) if 'bootstrap' in args else w.Result(0))
    monkeypatch.setattr(w, 'pause', lambda seconds: None)
    assert w.install(args, flaky) == 0
    assert sum('bootstrap' in command for command in calls) == 2
    always = lambda args, timeout: w.Result(5, '', 'Bootstrap failed') if 'bootstrap' in args else w.Result(0)
    assert w.install(args, always) == 4
    (state / 'unrelated.txt').write_text('keep me')
    (state / 'state.json').write_text('{}')
    args.purge_state = True
    assert w.uninstall(args, runner) == 0
    assert not target.exists() and (state / 'unrelated.txt').exists() and not (state / 'state.json').exists()


def test_dry_run_has_no_api_calls_no_ledger_write(tmp_path, calendar):
    github = FakeGitHub()
    state, messages = w.tick(tmp_path, github, calendar, utc('2026-10-02T20:30:00Z'), dry_run=True)
    assert not github.calls and not (tmp_path / 'state.json').exists()
    assert any('would dispatch' in line for line in messages)


def test_calendar_expiry_suppresses_future_close_slots():
    calendar = w.Calendar([(date(2026, 10, 2), utc('2026-10-02T20:00:00Z'))], date(2026, 10, 2))
    assert not [s for s in w.slots_between(calendar, utc('2026-10-03T00:00:00Z'), utc('2026-10-05T23:00:00Z')) if s.kind == 'close']
    with pytest.raises(ValueError):
        w.Calendar([], date(2026, 10, 2))


def test_corrupt_dry_run_is_read_only(tmp_path, calendar):
    path = tmp_path / 'state.json'
    path.write_text('{broken')
    github = FakeGitHub()
    _, messages = w.tick(tmp_path, github, calendar, utc('2026-10-02T20:30:00Z'), dry_run=True)
    assert path.read_text() == '{broken' and list(tmp_path.iterdir()) == [path]
    assert not github.calls and any('retained unchanged' in text for text in messages)


def ledger_ok(directory):
    """The persisted file must pass validation, with no corruption reset."""
    state = json.loads((directory / 'state.json').read_text())
    w.validate(state)
    assert 'recovered_from' not in state and not list(directory.glob('state.corrupt-*.json'))
    return state


def test_run_failure_after_list_failures_never_exceeds_attempt_budget(tmp_path, calendar):
    """Checker R1: three list outages, a fourth attempt that dispatches, then a failed run."""
    key = 'close-2026-10-02-a'
    github = FakeGitHub()
    github.rows = None                                           # `gh run list` unavailable
    at = utc('2026-10-02T20:30:00Z')
    for minute in (0, 2, 7):
        w.tick(tmp_path, github, calendar, at + timedelta(minutes=minute))
        ledger_ok(tmp_path)
    assert ledger_ok(tmp_path)['slots'][key]['attempts'] == 3 and not dispatches(github)
    github.rows = []
    w.tick(tmp_path, github, calendar, at + timedelta(minutes=17))
    state = ledger_ok(tmp_path)
    assert state['slots'][key]['status'] == 'requested' and state['slots'][key]['attempts'] == 4
    github.rows = [run(key, 'completed', 'failure', '2026-10-02T20:47:00Z')]
    w.tick(tmp_path, github, calendar, at + timedelta(minutes=19))
    state = ledger_ok(tmp_path)
    assert state['slots'][key]['status'] == 'failed' and 'budget exhausted' in state['slots'][key]['reason']
    github.rows = []
    for minute in (29, 30, 45):
        w.tick(tmp_path, github, calendar, at + timedelta(minutes=minute))
        state = ledger_ok(tmp_path)
    assert len(dispatches(github)) == 1                          # no fifth request
    assert state['slots'][key]['attempts'] == w.MAX_ATTEMPTS and state['slots'][key]['dispatches'] == 1
    assert state['slots']['fred-2026-10-02']['status'] == 'skipped_superseded'   # dedupe history kept
    assert state['daily']['2026-10-02'] == 1


def test_persisted_exhausted_retry_wait_fails_without_gh_calls(calendar):
    now = utc('2026-10-02T20:40:00Z')
    state = w.empty()
    state['last_tick'] = w.iso(now - timedelta(minutes=1))
    state['slots']['close-2026-10-02-a'] = {'kind': 'close', 'scheduled_at': '2026-10-02T20:30:00+00:00', 'status': 'retry_wait',
                                            'attempts': w.MAX_ATTEMPTS, 'dispatches': 1, 'next_attempt_at': w.iso(now - timedelta(seconds=1))}
    github = FakeGitHub()
    w.Watchdog(state, github, calendar, now).tick()
    assert state['slots']['close-2026-10-02-a']['status'] == 'failed' and not github.calls
    assert state['slots']['close-2026-10-02-a']['attempts'] == w.MAX_ATTEMPTS
    w.validate(state)


def test_clock_correction_bounds_corruption_hold_and_restores_liveness(tmp_path, calendar):
    """Checker R2: a corruption hold created under a wrong future clock lasts <= 15 min after correction."""
    (tmp_path / 'state.json').write_text('{broken')
    github = FakeGitHub()
    w.tick(tmp_path, github, calendar, utc('2026-10-06T20:30:00Z'))     # wrong clock: hold until Oct 6 20:45
    assert list(tmp_path.glob('state.corrupt-*.json')) and not dispatches(github)
    real = utc('2026-10-02T20:30:00Z')
    state, messages = w.tick(tmp_path, github, calendar, real)
    assert any('trusting' in m for m in messages)
    assert state['dispatch_hold_until'] == w.iso(real + w.CORRUPT_HOLD)   # safety kept, bounded
    assert not any(k.startswith('close-2026-10-06') for k in state['slots'])
    w.tick(tmp_path, github, calendar, real + timedelta(minutes=14))
    assert not dispatches(github)
    state, _ = w.tick(tmp_path, github, calendar, real + w.CORRUPT_HOLD)
    assert dispatches(github) == [('dispatch', 'watchdog:close-2026-10-02-a')]
    for minute in (16, 17, 30):
        state, _ = w.tick(tmp_path, github, calendar, real + timedelta(minutes=minute))
    assert len(dispatches(github)) == 1                                   # no storm after liveness returns
    w.validate(state)
    assert len(list(tmp_path.glob('state.corrupt-*.json'))) == 1           # no further corruption reset


def test_clock_correction_rebases_record_timers_and_keeps_daily_fuse(calendar):
    real = utc('2026-10-02T20:30:00Z')
    wrong = real + timedelta(days=4)
    state = w.empty()
    state['last_tick'] = w.iso(wrong)
    state['daily'] = {'2026-10-02': 1, '2026-10-06': 3}
    state['slots'] = {
        'fred-2026-10-02': {'kind': 'fred', 'scheduled_at': '2026-10-02T14:07:00+00:00', 'status': 'delivered',
                            'attempts': 1, 'dispatches': 1, 'intent_at': '2026-10-02T14:07:00+00:00'},
        'close-2026-10-02-a': {'kind': 'close', 'scheduled_at': '2026-10-02T20:30:00+00:00', 'status': 'retry_wait',
                               'attempts': 1, 'dispatches': 0, 'next_attempt_at': w.iso(wrong + timedelta(minutes=2))},
        'close-2026-10-01-b': {'kind': 'close', 'scheduled_at': '2026-10-01T21:30:00+00:00', 'status': 'dispatching',
                               'attempts': 1, 'dispatches': 0, 'intent_at': w.iso(wrong), 'polled_at': w.iso(wrong)},
    }
    github = FakeGitHub(runs=[])
    w.Watchdog(state, github, calendar, real).tick()
    w.validate(state)
    assert state['daily'] == {'2026-10-02': 4}                            # wrong-date dispatches still count today
    assert state['slots']['fred-2026-10-02']['status'] == 'delivered'      # terminal history preserved
    retry = w.parse(state['slots']['close-2026-10-02-a']['next_attempt_at'])
    assert retry <= real + timedelta(seconds=w.BACKOFF[-1])
    stuck = state['slots']['close-2026-10-01-b']
    assert w.parse(stuck['intent_at']) <= real and w.parse(stuck['polled_at']) <= real
    later = w.Watchdog(state, FakeGitHub(runs=[]), calendar, real + w.INTENT_STALE + timedelta(minutes=1))
    later.tick()                                                          # uncertainty window now expires normally
    assert state['slots']['close-2026-10-01-b']['status'] != 'dispatching'
