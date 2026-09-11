#!/usr/bin/env python3
"""Independent UTC dispatch watchdog for the snapshot workflow (macOS LaunchAgent).

GitHub's scheduled events were observed starting 2h45m-4h55m late. This watchdog
runs every minute on a Mac (launchd), computes due refresh slots from the NYSE
calendar in UTC, and asks GitHub to run the existing workflow through
``gh workflow run`` (workflow_dispatch). GitHub schedules stay as a fallback.

* No credentials: gh uses its own local login (macOS keychain). Nothing here
  reads, copies, stores or logs a token; gh output is redacted before logging.
* Dedupe: deterministic slot ids in an atomically replaced JSON ledger under an
  exclusive lock; an intent record is written before every dispatch, so crashes
  and restarts cannot repeat a slot.
* No storms: missed slots are coalesced into the latest one within CATCH_UP,
  older ones are marked superseded/expired; bounded attempts, persisted backoff,
  a per-slot and a per-day dispatch cap.
* Honest status: an acknowledged dispatch is "requested", not delivered. The run
  is tracked to completion and the artifact manifest is checked for an advance.

Standard library only; Python 3.9+ (macOS /usr/bin/python3 works).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

VERSION = 1
CHECKOUT = Path(__file__).resolve().parents[1]
CALENDAR = CHECKOUT / 'backend/app/data/nyse_sessions.json'
DEFAULT_REPO = 'Jo2234/us-market-regime-dashboard'
DEFAULT_WORKFLOW = 'refresh-market-data.yml'
MANIFEST = 'backend/app/data/dashboard_artifact.meta.json'
LABEL = 'com.jo2234.market-regime-watchdog'
DEFAULT_STATE = Path.home() / 'Library/Application Support/market-regime-watchdog'

# Close slots follow the official close (early closes and DST included): one
# primary build and one follow-up, both inside the API's close + 2h window.
CLOSE_OFFSETS = (('a', timedelta(minutes=30)), ('b', timedelta(minutes=90)))
FRED_UTC = time(14, 7)                     # weekday next-day FRED publications
CATCH_UP = timedelta(hours=12)             # older missed slots expire, never replay
COVER_TOLERANCE = timedelta(minutes=15)    # a run created this long before a slot covers it
BACKOFF = (120, 300, 600, 1200)            # seconds between failed dispatch attempts
MAX_ATTEMPTS = 4                           # gh invocations per slot
MAX_DISPATCHES = 2                         # acknowledged dispatches per slot (1 re-run on failure)
RERUN_DELAY = timedelta(minutes=10)
DAILY_CAP = 8                              # acknowledged dispatches per UTC day, storm fuse
GH_TIMEOUT = 45
POLL_EVERY = timedelta(minutes=2)
TRACK_LIMIT = timedelta(hours=3)
INTENT_STALE = timedelta(minutes=10)
CORRUPT_HOLD = timedelta(minutes=15)       # dispatch hold after a corrupt ledger is replaced
CLOCK_PAUSE = timedelta(hours=1)           # longer backwards jumps rebase instead of halting
KEEP = timedelta(days=14)
LOG_LIMIT = 1_000_000

TERMINAL = {'delivered', 'succeeded_unchanged', 'run_cancelled', 'failed', 'skipped_superseded',
            'skipped_redundant', 'skipped_cap', 'expired', 'untracked'}
TRACKED = {'requested', 'running', 'succeeded'}
VALID_STATUS = TERMINAL | TRACKED | {'new', 'retry_wait', 'dispatching'}
ACTIVE_RUN = {'queued', 'in_progress', 'waiting', 'requested', 'pending'}
SECRET = re.compile(r'(gh[pousr]_[A-Za-z0-9_]{6,}|github_pat_[A-Za-z0-9_]{6,}|(?i:bearer)\s+\S+|(?i:token|authorization|password)\s*[:=]\s*\S+)')


def redact(text: str, limit: int = 300) -> str:
    return SECRET.sub('[redacted]', ' '.join(str(text).split()))[:limit]


def iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('naive timestamp')
    return moment.astimezone(timezone.utc)


# --- schedule ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    id: str
    kind: str
    at: datetime

    @property
    def covered_from(self) -> datetime:
        return self.at - COVER_TOLERANCE


class Calendar:
    def __init__(self, sessions: List[Tuple[date, datetime]], valid_through: date):
        if not sessions or sessions != sorted(sessions) or len({day for day, _ in sessions}) != len(sessions):
            raise ValueError('NYSE sessions must be nonempty, sorted and unique')
        if any(close.tzinfo is None or day > valid_through for day, close in sessions):
            raise ValueError('Invalid NYSE session/calendar bound')
        self.sessions, self.valid_through = sessions, valid_through

    def completed(self, moment: datetime) -> str:
        completed = [day for day, close in self.sessions if close <= moment]
        if not completed:
            raise ValueError('No completed session at dispatch slot')
        return completed[-1].isoformat()

    @classmethod
    def load(cls, path: Path = CALENDAR) -> 'Calendar':
        raw = json.loads(path.read_text())
        return cls([(date.fromisoformat(d), datetime.fromtimestamp(ts, timezone.utc)) for d, ts in raw['sessions']],
                   date.fromisoformat(raw['valid_through']))


def slots_between(calendar: Calendar, start: datetime, end: datetime) -> List[Slot]:
    """All slots with start <= at <= end, in UTC, sorted."""
    result = []
    for day, close in calendar.sessions:
        if day <= calendar.valid_through and start - timedelta(hours=3) <= close <= end:
            result.extend(Slot(f'close-{day.isoformat()}-{tag}', 'close', close + offset) for tag, offset in CLOSE_OFFSETS)
    day = start.date()
    while day <= end.date():
        if day.weekday() < 5:
            result.append(Slot(f'fred-{day.isoformat()}', 'fred', datetime.combine(day, FRED_UTC, timezone.utc)))
        day += timedelta(days=1)
    return sorted((s for s in result if start <= s.at <= end), key=lambda s: (s.at, s.id))


def due_slots(calendar: Calendar, now: datetime) -> List[Slot]:
    return slots_between(calendar, now - CATCH_UP, now)


# --- gh process boundary -----------------------------------------------------------------

@dataclass
class Result:
    code: int
    stdout: str = ''
    stderr: str = ''


Runner = Callable[[List[str], int], Result]


def run_process(args: List[str], timeout: int) -> Result:
    # Minimal environment: gh reads its own keychain login. Token variables are
    # deliberately not forwarded; config-location variables are paths, not secrets.
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(Path.home()),
           'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1', 'NO_COLOR': '1', 'LANG': 'en_US.UTF-8'}
    env.update({k: os.environ[k] for k in ('GH_CONFIG_DIR', 'XDG_CONFIG_HOME') if k in os.environ})
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return Result(done.returncode, done.stdout, done.stderr)
    except FileNotFoundError:
        return Result(127, '', 'gh executable not found')
    except subprocess.TimeoutExpired:
        return Result(124, '', f'gh timed out after {timeout}s')
    except OSError as exc:
        return Result(126, '', f'gh could not start: {type(exc).__name__}')


class GitHub:
    def __init__(self, gh: str, repo: str, workflow: str, runner: Runner = run_process):
        self.gh, self.repo, self.workflow, self.runner = gh, repo, workflow, runner

    def _call(self, *args: str) -> Result:
        return self.runner([self.gh, *args], GH_TIMEOUT)

    def runs(self) -> Optional[List[dict]]:
        done = self._call('run', 'list', '--repo', self.repo, '--workflow', self.workflow, '--limit', '20',
                          '--json', 'databaseId,status,conclusion,event,createdAt,updatedAt,displayTitle,url,headBranch')
        if done.code:
            return None
        try:
            rows = json.loads(done.stdout)
            if not isinstance(rows, list):
                raise ValueError('Invalid workflow run list')
            return [r for r in rows if isinstance(r, dict) and parse(r.get('createdAt')) and r.get('headBranch') == 'main']
        except (ValueError, TypeError, AttributeError):
            return None

    def manifest(self) -> Optional[dict]:
        done = self._call('api', '-H', 'Accept: application/vnd.github.raw+json', f'repos/{self.repo}/contents/{MANIFEST}?ref=main')
        if done.code:
            return None
        try:
            item = json.loads(done.stdout)
            if not isinstance(item, dict) or item.get('version') != 1:
                raise ValueError('Invalid manifest')
            if not parse(item['built_at']):
                raise ValueError('Missing build timestamp')
            date.fromisoformat(item['as_of'])
            return {'as_of': item['as_of'], 'built_at': item['built_at']}
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def dispatch(self, reason: str) -> Result:
        if not re.fullmatch(r'[a-z0-9:._-]{1,80}', reason):
            raise ValueError('unsafe dispatch reason')
        return self._call('workflow', 'run', self.workflow, '--repo', self.repo, '--ref', 'main', '-f', f'reason={reason}')

    def authenticated(self) -> bool:
        return self._call('auth', 'status', '--hostname', 'github.com').code == 0


def classify(result: Result) -> str:
    text = (result.stderr + ' ' + result.stdout).lower()
    if result.code == 127:
        return 'gh_missing'
    if result.code == 124:
        return 'timeout'
    if 'auth' in text or 'login' in text or 'credential' in text or 'http 401' in text:
        return 'auth'
    if 'rate limit' in text or 'http 429' in text:
        return 'rate_limited'
    if 'http 403' in text or 'permission' in text or 'not accessible' in text:
        return 'permission'
    if re.search(r'http 5\d\d', text):
        return 'server_error'
    if 'could not resolve' in text or 'network' in text or 'connection' in text or 'timeout' in text:
        return 'network'
    return 'gh_error'


# --- ledger ------------------------------------------------------------------------------

class Busy(Exception):
    pass


class Ledger:
    """Exclusive flock + atomic JSON replace. Corrupt files are preserved, not reused."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / 'state.json'
        self._lock = None

    def __enter__(self) -> 'Ledger':
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = open(self.directory / 'watchdog.lock', 'a+')
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise Busy('another watchdog tick holds the lock')
        self._lock = handle
        for stray in self.directory.glob('.state-*.tmp'):
            stray.unlink()   # interrupted write; the previous complete file is still intact
        return self

    def __exit__(self, *exc) -> None:
        if self._lock:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            self._lock.close()
            self._lock = None

    def read(self, now: datetime) -> Tuple[dict, Optional[str]]:
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return empty(), None
        try:
            state = json.loads(raw)
            validate(state)
            return state, None
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            fd, name = tempfile.mkstemp(prefix=f"state.corrupt-{now.strftime('%Y%m%dT%H%M%SZ')}-", suffix='.json', dir=self.directory)
            os.close(fd)
            keep = Path(name)
            os.replace(self.path, keep)
            fresh = empty()
            fresh['recovered_from'] = {'file': keep.name, 'at': iso(now), 'error': type(exc).__name__}
            fresh['dispatch_hold_until'] = iso(now + CORRUPT_HOLD)
            return fresh, f'corrupt ledger preserved as {keep.name}; starting a fresh ledger'

    def write(self, state: dict) -> None:
        fd, name = tempfile.mkstemp(prefix='.state-', suffix='.tmp', dir=str(self.directory))
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(state, handle, indent=1, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(name, 0o600)
            os.replace(name, self.path)
            directory = os.open(str(self.directory), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            if os.path.exists(name):
                os.unlink(name)
            raise


def empty() -> dict:
    return {'version': VERSION, 'slots': {}, 'daily': {}, 'events': [], 'last_tick': None}


def validate(state: dict) -> None:
    if not isinstance(state, dict) or state.get('version') != VERSION or not isinstance(state.get('slots'), dict) or not isinstance(state.get('daily'), dict):
        raise ValueError('unsupported ledger')
    parse(state.get('last_tick'))
    parse(state.get('dispatch_hold_until'))
    for slot_id, record in state['slots'].items():
        if not isinstance(slot_id, str) or not re.fullmatch(r'(?:close-\d{4}-\d{2}-\d{2}-[ab]|fred-\d{4}-\d{2}-\d{2})', slot_id):
            raise ValueError('bad slot id')
        if not isinstance(record, dict) or record.get('status') not in VALID_STATUS:
            raise ValueError(f'bad slot {slot_id}')
        for key in ('attempts', 'dispatches'):
            if type(record.get(key, 0)) is not int or not 0 <= record.get(key, 0) <= MAX_ATTEMPTS:
                raise ValueError('bad attempt/dispatch count')
        if not parse(record.get('scheduled_at')):
            raise ValueError('missing scheduled timestamp')
        for key in ('next_attempt_at', 'intent_at', 'dispatched_at', 'polled_at', 'updated_at'):
            parse(record.get(key))
        if record['status'] in TRACKED | {'dispatching'} and not parse(record.get('intent_at')):
            raise ValueError('missing intent timestamp')
        if record.get('expected_as_of'):
            date.fromisoformat(record['expected_as_of'])
    for key, value in state['daily'].items():
        date.fromisoformat(key)
        if type(value) is not int or not 0 <= value <= DAILY_CAP:
            raise ValueError('bad daily counters')
    if not isinstance(state.get('events', []), list) or any(not isinstance(v, dict) for v in state.get('events', [])):
        raise ValueError('bad event history')
    state.setdefault('events', [])


# --- state machine -------------------------------------------------------------------------

class Watchdog:
    def __init__(self, state: dict, github: GitHub, calendar: Calendar, now: datetime, *, dry_run: bool = False):
        self.state, self.github, self.calendar, self.now, self.dry_run = state, github, calendar, now, dry_run
        self.messages: List[str] = []
        self._runs: Optional[List[dict]] = None
        self._runs_loaded = False
        self._manifest = None
        self._manifest_loaded = False

    def log(self, message: str) -> None:
        line = redact(message, 500)
        self.messages.append(line)
        self.state['events'] = (self.state.get('events', []) + [{'at': iso(self.now), 'message': line}])[-50:]

    def runs(self) -> Optional[List[dict]]:
        if not self._runs_loaded:
            self._runs, self._runs_loaded = (None if self.dry_run else self.github.runs()), True
        return self._runs

    def manifest(self) -> Optional[dict]:
        if not self._manifest_loaded:
            self._manifest = None if self.dry_run else self.github.manifest()
            self._manifest_loaded = True
        return self._manifest

    def record(self, slot: Slot) -> dict:
        return self.state['slots'].setdefault(slot.id, {'kind': slot.kind, 'scheduled_at': iso(slot.at), 'status': 'new',
                                                        'attempts': 0, 'dispatches': 0,
                                                        'expected_as_of': self.calendar.completed(slot.at)})

    def set(self, slot_id: str, status: str, **fields) -> None:
        record = self.state['slots'][slot_id]
        if record['status'] != status:
            self.log(f'{slot_id}: {record["status"]} -> {status}' + (f' ({fields["reason"]})' if fields.get('reason') else ''))
        record.update(fields, status=status, updated_at=iso(self.now))

    def tick(self) -> dict:
        last = parse(self.state.get('last_tick'))
        plausible = self.calendar.sessions[0][1] <= self.now and self.now.date() <= self.calendar.valid_through
        if last and self.now < last - timedelta(minutes=5):
            if last - self.now <= CLOCK_PAUSE or not plausible:
                self.log(f'clock moved backwards from {iso(last)}; dispatch paused until the previous tick time')
                return self.state
            # A recorded tick far in the future came from a wrong clock. Waiting for it
            # would halt the service indefinitely; drop impossible future records and
            # continue (stable slot ids still prevent repeats).
            future = self.rebase_clock()
            self.log(f'clock moved back {int((last - self.now).total_seconds() // 3600)}h from {iso(last)}; '
                     f'trusting the in-calendar system clock, dropped {len(future)} future-dated slot(s), rebased timers')
        elif last and self.now - last > timedelta(minutes=10):
            self.log(f'resumed after {int((self.now - last).total_seconds() // 60)} min without a tick (sleep/offline/crash)')
        if self.now.date() > self.calendar.valid_through:
            self.log('NYSE calendar expired: close slots disabled; run scripts/refresh_calendar.py')
        self.state['last_tick'] = iso(self.now)
        self.track()
        due = due_slots(self.calendar, self.now)
        due_ids = {s.id for s in due}
        latest = due[-1] if due else None
        for slot_id, record in list(self.state['slots'].items()):
            if record['status'] in TERMINAL or record['status'] in TRACKED or record['status'] == 'dispatching':
                continue
            if slot_id not in due_ids:
                self.set(slot_id, 'expired', reason='outside catch-up window')
            elif latest and slot_id != latest.id:
                self.set(slot_id, 'skipped_superseded', reason=f'coalesced into {latest.id}')
        for slot in due[:-1]:
            if slot.id not in self.state['slots']:
                self.record(slot)
                self.set(slot.id, 'skipped_superseded', reason=f'coalesced into {latest.id}')
        if latest:
            self.act(latest)
        self.prune()
        return self.state

    def rebase_clock(self) -> List[str]:
        """Accept a large clock correction without keeping wrong-clock holds or timers.

        Future-only slots are dropped. A corruption hold keeps at most its normal 15
        minutes from the corrected time. Retry timers keep at most the longest backoff;
        intent/poll/dispatch times restart their bounded windows from now. Dispatch
        counts made under the wrong date move to today, so the daily fuse stays
        conservative and history is not forgotten."""
        future = [k for k, v in self.state['slots'].items() if parse(v['scheduled_at']) > self.now + timedelta(hours=1)]
        for slot_id in future:
            del self.state['slots'][slot_id]
        hold = parse(self.state.get('dispatch_hold_until'))
        if hold and hold > self.now + CORRUPT_HOLD:
            self.state['dispatch_hold_until'] = iso(self.now + CORRUPT_HOLD)
        for record in self.state['slots'].values():
            retry = parse(record.get('next_attempt_at'))
            if retry and retry > self.now + timedelta(seconds=BACKOFF[-1]):
                record['next_attempt_at'] = iso(self.now + timedelta(seconds=BACKOFF[-1]))
            for key in ('intent_at', 'dispatched_at', 'polled_at', 'updated_at'):
                moment = parse(record.get(key))
                if moment and moment > self.now:
                    record[key] = iso(self.now)
        today = self.now.date().isoformat()
        for day in [d for d in self.state['daily'] if d > today]:
            self.state['daily'][today] = min(DAILY_CAP, self.state['daily'].get(today, 0) + self.state['daily'].pop(day))
        return future

    # Tracking dispatched slots: requested -> running -> succeeded -> delivered/unchanged.
    def track(self) -> None:
        for slot_id, record in self.state['slots'].items():
            if record['status'] == 'dispatching':
                self.resolve_intent(slot_id, record)
            if record['status'] not in TRACKED:
                continue
            sent = parse(record.get('dispatched_at') or record.get('intent_at'))
            polled = parse(record.get('polled_at'))
            if polled and self.now - polled < POLL_EVERY:
                continue
            if sent and self.now - sent > TRACK_LIMIT:
                self.set(slot_id, 'untracked', reason='no completed run observed within 3h')
                continue
            if record['status'] == 'succeeded':
                self.check_artifact(slot_id, record)
                continue
            runs = self.runs()
            record['polled_at'] = iso(self.now)
            if runs is None:
                continue
            run = self.match(slot_id, record, runs)
            if not run:
                continue
            record.update(run_id=run.get('databaseId'), run_url=run.get('url'), run_status=run.get('status'), run_conclusion=run.get('conclusion'))
            if run.get('status') == 'in_progress':
                self.set(slot_id, 'running')
            elif run.get('status') == 'completed' and run.get('conclusion') == 'success':
                self.set(slot_id, 'succeeded')
                self.check_artifact(slot_id, record)
            elif run.get('status') == 'completed' and run.get('conclusion') == 'cancelled':
                self.set(slot_id, 'run_cancelled', reason='cancelled (a newer queued run supersedes it, or manual)')
            elif run.get('status') == 'completed':
                self.run_failed(slot_id, record, run.get('conclusion'))

    def match(self, slot_id: str, record: dict, runs: List[dict]) -> Optional[dict]:
        if record.get('run_id'):
            known = next((r for r in runs if r.get('databaseId') == record['run_id']), None)
            if known:
                return known
        intent = parse(record.get('intent_at'))
        # The workflow's run-name embeds this exact reason. Never claim unrelated
        # manual dispatches merely because their timestamps are nearby.
        tagged = [r for r in runs if f'(watchdog:{slot_id})' in str(r.get('displayTitle', ''))
                  and intent and parse(r['createdAt']) >= intent - timedelta(minutes=1)]
        return max(tagged, key=lambda r: r['createdAt']) if tagged else None

    def check_artifact(self, slot_id: str, record: dict) -> None:
        record['polled_at'] = iso(self.now)
        listed = self.manifest()
        if listed is None:
            return   # retried on the next poll until TRACK_LIMIT
        # built_at is the newest provider fetch time; it only moves when a run after
        # our request fetched changed observations.
        expected = record.get('expected_as_of') or self.calendar.completed(parse(record['scheduled_at']))
        advanced = (parse(listed['built_at']) >= parse(record['intent_at']) - timedelta(minutes=2)
                    and date.fromisoformat(listed['as_of']) >= date.fromisoformat(expected))
        record.update(artifact_as_of=listed['as_of'], artifact_built_at=listed['built_at'])
        self.set(slot_id, 'delivered' if advanced else 'succeeded_unchanged',
                 reason=f"artifact as_of {listed['as_of']} built_at {listed['built_at']}; expected research {expected}"
                 + ('' if advanced else ' (required research/date advance not observed)'))

    def run_failed(self, slot_id: str, record: dict, conclusion: Optional[str]) -> None:
        slot_at = parse(record['scheduled_at'])
        if (record.get('dispatches', 0) < MAX_DISPATCHES and record.get('attempts', 0) < MAX_ATTEMPTS
                and self.now + RERUN_DELAY < slot_at + CATCH_UP):
            self.set(slot_id, 'retry_wait', next_attempt_at=iso(self.now + RERUN_DELAY), reason=f'run concluded {conclusion}; one re-dispatch allowed')
        else:
            self.set(slot_id, 'failed', reason=f'run concluded {conclusion}; dispatch budget exhausted')

    def resolve_intent(self, slot_id: str, record: dict) -> None:
        """Uncertain write/crash: observe the exact tagged run before retrying."""
        intent = parse(record['intent_at'])
        if self.now - intent > TRACK_LIMIT:
            self.set(slot_id, 'untracked', reason='interrupted/uncertain dispatch could not be resolved within 3h; no blind repeat')
            return
        polled = parse(record.get('polled_at'))
        if polled and self.now - polled < POLL_EVERY:
            return
        runs = self.runs()
        record['polled_at'] = iso(self.now)
        if runs is None:
            return  # An unavailable listing is not evidence that dispatch failed.
        run = self.match(slot_id, record, runs)
        if run:
            day = intent.date().isoformat()
            self.state['daily'][day] = min(DAILY_CAP, self.state['daily'].get(day, 0) + 1)
            record['dispatches'] = record.get('dispatches', 0) + 1
            self.set(slot_id, 'requested', run_id=run.get('databaseId'), dispatched_at=iso(intent),
                     reason='exact tagged run found after interrupted/uncertain dispatch')
        elif self.now - intent >= INTENT_STALE:
            self.fail_attempt(slot_id, record, 'interrupted', 'successful listing found no exact run after 10m uncertainty window')

    def fail_attempt(self, slot_id: str, record: dict, kind: str, detail: str) -> None:
        attempts = record['attempts']
        slot_at = parse(record['scheduled_at'])
        wait = timedelta(seconds=BACKOFF[min(attempts, len(BACKOFF)) - 1])
        if attempts >= MAX_ATTEMPTS or self.now + wait >= slot_at + CATCH_UP:
            self.set(slot_id, 'failed', last_error=kind, reason=f'{kind}: {detail}; attempts exhausted')
        else:
            self.set(slot_id, 'retry_wait', last_error=kind, next_attempt_at=iso(self.now + wait), reason=f'{kind}: {detail}; retry in {int(wait.total_seconds())}s')

    @staticmethod
    def covered(slot: Slot, runs: List[dict]) -> Optional[dict]:
        for run in runs:
            created = parse(run['createdAt'])
            if (run.get('status') in ACTIVE_RUN
                    and created >= (slot.covered_from if run.get('status') == 'in_progress' else slot.at - TRACK_LIMIT)):
                return run   # a queued run reads providers when it starts; one started after the slot also covers it
            if run.get('status') == 'completed' and run.get('conclusion') == 'success' and created >= slot.covered_from:
                return run
        return None

    def act(self, slot: Slot) -> None:
        record = self.record(slot)
        if record['status'] in TERMINAL or record['status'] in TRACKED or record['status'] == 'dispatching':
            return
        wait_until = parse(record.get('next_attempt_at'))
        if wait_until and self.now < wait_until:
            return
        if record['attempts'] >= MAX_ATTEMPTS or record.get('dispatches', 0) >= MAX_DISPATCHES:
            # Checked before any attempt/dispatch mutation so the ledger stays within
            # the bounds validate() enforces; an issued final request is still tracked.
            self.set(slot.id, 'failed', reason=f'attempt budget exhausted ({record["attempts"]} attempts, {record.get("dispatches", 0)} dispatches)')
            return
        hold = parse(self.state.get('dispatch_hold_until'))
        if hold and self.now < hold:
            return
        today = self.now.date().isoformat()
        if self.state['daily'].get(today, 0) >= DAILY_CAP:
            self.set(slot.id, 'skipped_cap', reason=f'daily cap of {DAILY_CAP} dispatches reached')
            return
        runs = self.runs()
        if runs is None and not self.dry_run:
            record['attempts'] += 1
            self.fail_attempt(slot.id, record, 'gh_unavailable', 'could not list workflow runs')
            return
        hit = self.covered(slot, runs or [])
        if hit:
            # Adopt a covering run and watch its outcome; queued does not mean
            # successful. A later failure can still trigger bounded recovery.
            self.set(slot.id, 'requested', run_id=hit.get('databaseId'), run_url=hit.get('url'),
                     intent_at=hit['createdAt'], dispatched_at=hit['createdAt'], adopted=True,
                     reason=f"tracking {hit.get('event')} run {hit.get('databaseId')} ({hit.get('status')}) covering this slot")
            return
        if self.dry_run:
            self.log(f'{slot.id}: would dispatch (dry run)')
            return
        record['attempts'] += 1
        # Intent first: tick() persists it before calling GitHub, so a crash can't repeat the slot.
        self.set(slot.id, 'dispatching', intent_at=iso(self.now), dispatched_at=None,
                 run_id=None, run_url=None, polled_at=None, adopted=False)

    def acknowledge(self, slot_id: str, result: Result) -> None:
        record = self.state['slots'][slot_id]
        if result.code == 0:
            today = self.now.date().isoformat()
            self.state['daily'][today] = min(DAILY_CAP, self.state['daily'].get(today, 0) + 1)
            record['dispatches'] = record.get('dispatches', 0) + 1
            self.set(slot_id, 'requested', dispatched_at=iso(self.now), next_attempt_at=None, last_error=None,
                     reason='workflow_dispatch acknowledged by GitHub (not yet delivered)')
        else:
            kind = classify(result)
            if kind in ('timeout', 'network', 'server_error'):
                self.set(slot_id, 'dispatching', last_error=kind,
                         reason='dispatch outcome uncertain; inspect exact tagged run before any repeat')
            else:
                self.fail_attempt(slot_id, record, kind, redact(result.stderr or result.stdout or f'exit {result.code}', 200))

    def prune(self) -> None:
        cutoff = self.now - KEEP
        self.state['slots'] = {k: v for k, v in self.state['slots'].items() if parse(v['scheduled_at']) >= cutoff}
        self.state['daily'] = {k: v for k, v in self.state['daily'].items() if k >= cutoff.date().isoformat()}


def tick(state_dir: Path, github: GitHub, calendar: Calendar, now: datetime, *, dry_run: bool = False) -> Tuple[dict, List[str]]:
    """One locked pass. Intent is persisted before the network write, then the outcome."""
    if dry_run:
        # Atomic real writes allow a coherent read without acquiring a lock or
        # creating/renaming any local files during an offline preview.
        warning = None
        try:
            state = json.loads((state_dir / 'state.json').read_text())
            validate(state)
        except FileNotFoundError:
            state = empty()
        except (ValueError, TypeError, KeyError, AttributeError):
            state = empty()
            warning = 'corrupt ledger detected in dry run; original file retained unchanged'
        machine = Watchdog(state, github, calendar, now, dry_run=True)
        if warning:
            machine.log(warning)
        machine.tick()
        return state, machine.messages
    with Ledger(state_dir) as ledger:
        state, warning = ledger.read(now)
        machine = Watchdog(state, github, calendar, now, dry_run=dry_run)
        if warning:
            machine.log(warning)
        machine.tick()
        pending = [k for k, v in state['slots'].items() if v['status'] == 'dispatching' and v.get('intent_at') == iso(now)]
        if dry_run:
            return state, machine.messages
        ledger.write(state)
        for slot_id in pending:
            machine.acknowledge(slot_id, github.dispatch(f'watchdog:{slot_id}'))
            ledger.write(state)
        return state, machine.messages


# --- logging -----------------------------------------------------------------------------

def append_log(state_dir: Path, now: datetime, messages: List[str]) -> None:
    if not messages:
        return   # idle ticks stay silent
    path = state_dir / 'watchdog.log'
    if path.exists() and path.stat().st_size > LOG_LIMIT:
        os.replace(path, state_dir / 'watchdog.log.1')
    with open(path, 'a') as handle:
        for message in messages:
            handle.write(f'{iso(now)} {redact(message, 500)}\n')


# --- LaunchAgent ---------------------------------------------------------------------------

TEMP_ROOTS = ('/private/var/folders/', '/var/folders/', '/tmp/', '/private/tmp/')


def plist_for(python: str, gh: str, checkout: Path, state_dir: Path, repo: str, workflow: str) -> dict:
    script = checkout / 'scripts/dispatch_watchdog.py'
    return {
        'Label': LABEL,
        'ProgramArguments': [python, str(script), 'tick', '--state-dir', str(state_dir), '--repo', repo, '--workflow', workflow, '--gh', gh],
        'WorkingDirectory': str(checkout),
        'EnvironmentVariables': {'PATH': f'{Path(gh).parent}:/usr/bin:/bin:/usr/sbin:/sbin'},
        'RunAtLoad': True,
        'StartInterval': 60,
        'ProcessType': 'Background',
        'StandardOutPath': str(state_dir / 'launchd.out.log'),
        'StandardErrorPath': str(state_dir / 'launchd.err.log'),
    }


def plist_path() -> Path:
    return Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'


def check_install(python: str, gh: str, checkout: Path, allow_temp: bool) -> List[str]:
    problems = []
    for name, value in (('python', python), ('gh', gh)):
        if not os.path.isabs(value) or not os.access(value, os.X_OK):
            problems.append(f'{name} must be an absolute executable path: {value}')
        if not allow_temp and str(Path(value).absolute()).startswith(TEMP_ROOTS):
            problems.append(f'{name} executable path is temporary; use a persistent absolute path')
    resolved = str(checkout.resolve()) + '/'
    if not allow_temp and resolved.startswith(TEMP_ROOTS):
        problems.append(f'checkout {checkout} is temporary; clone to a stable path first')
    if not (checkout / 'scripts/dispatch_watchdog.py').is_file() or not (checkout / 'backend/app/data/nyse_sessions.json').is_file():
        problems.append(f'{checkout} is not a dashboard checkout')
    return problems


BOOTSTRAP_TRIES = 3
pause = time_module.sleep


def launchctl(*args: str, runner: Runner = run_process) -> Result:
    return runner(['/bin/launchctl', *args], 30)


def install(args, runner: Runner = run_process) -> int:
    checkout = Path(args.checkout).resolve()
    problems = check_install(args.python, args.gh, checkout, args.allow_temp_checkout)
    if not args.allow_temp_checkout and str(Path(args.state_dir).expanduser().absolute()).startswith(TEMP_ROOTS):
        problems.append('state directory is temporary; use persistent state for deduplication')
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 2
    github = GitHub(args.gh, args.repo, args.workflow, runner)
    if not args.skip_auth_check and not github.authenticated():
        print('gh is not authenticated for github.com; run `gh auth login` interactively first (nothing is stored by this tool)', file=sys.stderr)
        return 3
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = plistlib.dumps(plist_for(args.python, args.gh, checkout, state_dir, args.repo, args.workflow))
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_bytes(content)
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    print(f'wrote {target}')
    if args.no_load:
        return 0
    domain = f'gui/{os.getuid()}'
    launchctl('bootout', f'{domain}/{LABEL}', runner=runner)   # absent on first install
    enabled = launchctl('enable', f'{domain}/{LABEL}', runner=runner)
    if enabled.code:
        print(f'launchctl enable failed: {redact(enabled.stderr)}', file=sys.stderr)
        return 4
    # bootout is asynchronous; an immediate bootstrap on reinstall can fail with
    # "5: Input/output error" until teardown finishes.
    for attempt in range(BOOTSTRAP_TRIES):
        loaded = launchctl('bootstrap', domain, str(target), runner=runner)
        if not loaded.code:
            break
        if attempt + 1 < BOOTSTRAP_TRIES:
            pause(1 + attempt)
    if loaded.code:
        print(f'launchctl bootstrap failed: {redact(loaded.stderr)}', file=sys.stderr)
        return 4
    print(f'loaded {LABEL}; verify with: {args.python} {checkout / "scripts/dispatch_watchdog.py"} status --state-dir "{state_dir}"')
    return 0


def uninstall(args, runner: Runner = run_process) -> int:
    launchctl('bootout', f'gui/{os.getuid()}/{LABEL}', runner=runner)
    target = plist_path()
    if target.exists():
        target.unlink()
        print(f'removed {target}')
    state_dir = Path(args.state_dir).expanduser()
    if args.purge_state and state_dir.exists():
        # Purge only this service's known files; never recursively delete an
        # arbitrary caller-supplied directory or unrelated contents.
        for path in state_dir.iterdir():
            if path.is_file() and (path.name in ('state.json', 'watchdog.lock', 'watchdog.log', 'watchdog.log.1', 'launchd.out.log', 'launchd.err.log')
                                   or re.fullmatch(r'state\.corrupt-\d{8}T\d{6}Z(?:-[A-Za-z0-9_-]+)?\.json', path.name)
                                   or re.fullmatch(r'\.state-[A-Za-z0-9_-]+\.tmp', path.name)):
                path.unlink()
        try:
            state_dir.rmdir()
        except OSError:
            pass
        print(f'purged watchdog files in {state_dir}; unrelated contents retained')
    else:
        print(f'ledger and logs kept in {state_dir}')
    return 0


def status(args, runner: Runner = run_process, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    state_dir = Path(args.state_dir).expanduser()
    report: Dict[str, object] = {'label': LABEL, 'plist': str(plist_path()), 'plist_installed': plist_path().exists()}
    service = launchctl('print', f'gui/{os.getuid()}/{LABEL}', runner=runner)
    report['launchd_loaded'] = service.code == 0
    if service.code == 0:
        report['launchd'] = {k: v for k, v in re.findall(r'^\s*(state|runs|last exit code|run interval)\s*=\s*(.+)$', service.stdout, re.M)}
    try:
        state = json.loads((state_dir / 'state.json').read_text())
        validate(state)
        last = parse(state.get('last_tick'))
        report['last_tick'] = state.get('last_tick')
        report['last_tick_age_seconds'] = int((now - last).total_seconds()) if last else None
        report['slots'] = {k: {f: v.get(f) for f in ('status', 'scheduled_at', 'expected_as_of', 'attempts', 'dispatches', 'run_id', 'run_url', 'run_status', 'run_conclusion', 'artifact_as_of', 'artifact_built_at', 'last_error', 'reason')}
                           for k, v in sorted(state['slots'].items(), key=lambda kv: kv[1]['scheduled_at'])[-12:]}
        report['recent_events'] = state.get('events', [])[-10:]
        report['recovered_from'] = state.get('recovered_from')
    except FileNotFoundError:
        report['ledger'] = 'not created yet'
    except (ValueError, TypeError, KeyError) as exc:
        report['ledger'] = f'unreadable ({type(exc).__name__}); next tick preserves it and starts fresh'
    upcoming = slots_between(Calendar.load(), now, now + timedelta(days=3))
    report['next_slots'] = [f'{s.id} {iso(s.at)}' for s in upcoming[:6]]
    if args.github:
        github = GitHub(args.gh, args.repo, args.workflow, runner)
        report['gh_authenticated'] = github.authenticated()
        report['artifact_manifest_on_main'] = github.manifest()
        runs = github.runs()
        report['recent_runs'] = [{k: r.get(k) for k in ('databaseId', 'event', 'status', 'conclusion', 'createdAt', 'displayTitle')} for r in (runs or [])[:5]]
    print(json.dumps(report, indent=1, default=str))
    return 0


# --- CLI -----------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--state-dir', default=str(DEFAULT_STATE))
    common.add_argument('--repo', default=DEFAULT_REPO)
    common.add_argument('--workflow', default=DEFAULT_WORKFLOW)
    common.add_argument('--gh', default=shutil.which('gh') or '/opt/homebrew/bin/gh')
    run = sub.add_parser('tick', parents=[common], help='one scheduling pass (launchd runs this every 60 s)')
    run.add_argument('--dry-run', action='store_true', help='decide only: no gh calls, no ledger write')
    run.add_argument('--now', help='simulated UTC time; requires --dry-run')
    plan = sub.add_parser('plan', help='list upcoming UTC slots (offline)')
    plan.add_argument('--now')
    plan.add_argument('--days', type=int, default=7)
    show = sub.add_parser('status', parents=[common], help='launchd + ledger status')
    show.add_argument('--github', action='store_true', help='also read gh auth state, recent runs and the artifact manifest')
    setup = sub.add_parser('install', parents=[common], help='write and load the user LaunchAgent')
    setup.add_argument('--python', default=sys.executable)
    setup.add_argument('--checkout', default=str(CHECKOUT))
    setup.add_argument('--allow-temp-checkout', action='store_true')
    setup.add_argument('--skip-auth-check', action='store_true')
    setup.add_argument('--no-load', action='store_true', help='write the plist only')
    remove = sub.add_parser('uninstall', parents=[common], help='unload and remove the LaunchAgent')
    remove.add_argument('--purge-state', action='store_true')
    render = sub.add_parser('render-plist', parents=[common], help='print the LaunchAgent plist')
    render.add_argument('--python', default=sys.executable)
    render.add_argument('--checkout', default=str(CHECKOUT))
    args = parser.parse_args(argv)

    if args.command == 'plan':
        if not 1 <= args.days <= 31:
            parser.error('--days must be from 1 to 31')
        now = parse(args.now) if args.now else datetime.now(timezone.utc)
        for slot in slots_between(Calendar.load(), now, now + timedelta(days=args.days)):
            print(f'{iso(slot.at)}  {slot.id}')
        return 0
    if args.command == 'render-plist':
        sys.stdout.write(plistlib.dumps(plist_for(args.python, args.gh, Path(args.checkout).resolve(), Path(args.state_dir).expanduser().resolve(), args.repo, args.workflow)).decode())
        return 0
    if args.command == 'install':
        return install(args)
    if args.command == 'uninstall':
        return uninstall(args)
    if args.command == 'status':
        return status(args)
    if args.now and not args.dry_run:
        parser.error('--now is only allowed with --dry-run')
    now = parse(args.now) if args.now else datetime.now(timezone.utc)
    state_dir = Path(args.state_dir).expanduser()
    github = GitHub(args.gh, args.repo, args.workflow)
    try:
        _, messages = tick(state_dir, github, Calendar.load(), now, dry_run=args.dry_run)
    except Busy:
        return 0
    if args.dry_run:
        print('\n'.join(messages) or 'nothing due')
    else:
        append_log(state_dir, now, messages)
    return 0


if __name__ == '__main__':
    sys.exit(main())
