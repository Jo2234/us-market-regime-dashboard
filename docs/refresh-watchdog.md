# Independent snapshot refresh on RP

The RP watchdog is a user macOS LaunchAgent that checks the UTC schedule every
60 seconds and requests the existing GitHub workflow through `gh workflow run`.
It is an independent trigger for the same provider fetch/build/commit path.
GitHub's scheduled triggers remain a fallback. Installation and live dispatch
require operator action; source code and passing mocked tests do not prove that
the service is installed or that new data reached the deployed dashboard.

Five recorded scheduled starts were 2h45m–4h55m late, beyond the two-hour research
delivery window. Those observations show a real timing problem without proving
that every weekday failed. Moving fallback cron away from minute zero may help;
it does not guarantee delivery. The dispatcher bypasses the scheduled-event
trigger but still depends on GitHub runner capacity, provider availability,
build/commit success and production deployment/delivery.

## Schedule and freshness

The checked-in NYSE calendar supplies official UTC closes, including holidays,
DST and early closes. The primary and follow-up slots are **close + 30 minutes**
and **close + 90 minutes**. For a normal 16:00 ET close these are 20:30/21:30 UTC
in EDT and 21:30/22:30 UTC in EST; a 13:00 EST early close produces 18:30/19:30 UTC.
There are no close slots on NYSE holidays or weekends. FRED gets a weekday
14:07 UTC slot, including equity holidays because its series have their own
publication calendars. This slot is a refresh opportunity, not a claim that all
series have released. The fixed GitHub fallback times are weekday 14:07, 21:17
and 22:37 UTC; early-close timing comes from the watchdog.

Research delivery uses the unchanged official-close + two-hour deadline:

| API status | Meaning |
| --- | --- |
| `current` | Artifact covers the latest completed NYSE session |
| `pending` | A newer completed session awaits delivery within its two-hour window |
| `overdue` | A required completed session is still absent after its deadline |

`pending` describes awaiting delivery and does not confirm an active job. If an
older required session is already missing, research stays overdue even while a
newer session's delivery window is open. The API exposes `as_of`, `built_at`,
expected session/close, deadline, `overdue_since`, evaluated time and next session.
Legacy `fresh` still means the delivery deadline has not been missed; consumers
should use `status` to distinguish current from pending. `scheduled` identifies
the artifact delivery mechanism, not proof of an installed RP service.

Source observations retain their original dates and turn stale under their own
NYSE/FRED cadence rules. Additive `delivery_state` and `is_overdue` explain whether
those stale observations await delivery or are overdue. The UI shows stale dates
alongside awaiting/overdue wording. Live quote freshness and polling remain
separate from daily research. Historical views are labeled explicitly; the source
freshness panel identifies the latest stored artifact's scope.

## Install after review

Use a persistent checkout, interpreter and state directory. The audit checkout
under `/var/folders` and its virtual environment are unsuitable for a permanent
LaunchAgent. The script is standard-library-only and supports Python 3.9+; the
backend build dependencies run on GitHub, not in the RP watchdog. Keep the Mac
logged in, awake and reachable. A user LaunchAgent runs in that user's GUI login
session. RP sleep, logout, reboot before login or an offline network stops ticks.

On macOS, keep the checkout and physically resolved Python/gh executables outside
`Documents`, `Desktop` and `Downloads` unless background access has been explicitly
permitted. Privacy controls can allow an interactive terminal to read a path while
blocking a LaunchAgent. A symlink outside those folders still depends on access to
its target; inspect the resolved locations, not just the paths in the plist. RP's
deployment required moving both the checkout and the gh binary out of `Documents`.
An executable copy contains no login credentials; gh continues to use the operator's
existing local login. Keep the ledger/state directory when relocating or reinstalling.

Example operator setup (adjust persistent executable/checkout paths):

```sh
# Use a reviewed persistent checkout containing this revision.
CHECKOUT="$HOME/.local/share/market-regime-watchdog/checkout"
WATCHDOG_PYTHON="/usr/bin/python3"
GH_BIN="$HOME/.local/share/market-regime-watchdog/bin/gh"
WATCHDOG_STATE="$HOME/Library/Application Support/market-regime-watchdog"

# Python and gh must be real accessible executables (or resolve to accessible paths).
"$WATCHDOG_PYTHON" "$CHECKOUT/scripts/dispatch_watchdog.py" plan --days 7
"$WATCHDOG_PYTHON" "$CHECKOUT/scripts/dispatch_watchdog.py" tick --dry-run \
  --state-dir "$WATCHDOG_STATE" --gh "$GH_BIN"

# Foreground auth check only; also verify background access after installation.
# gh uses the operator's existing login; this tool never stores/copies a token.
"$GH_BIN" auth status --hostname github.com
"$WATCHDOG_PYTHON" "$CHECKOUT/scripts/dispatch_watchdog.py" install \
  --checkout "$CHECKOUT" --python "$WATCHDOG_PYTHON" --gh "$GH_BIN" \
  --state-dir "$WATCHDOG_STATE"
"$WATCHDOG_PYTHON" "$CHECKOUT/scripts/dispatch_watchdog.py" status \
  --state-dir "$WATCHDOG_STATE" --gh "$GH_BIN" --github
```

The installer writes `~/Library/LaunchAgents/com.jo2234.market-regime-watchdog.plist`,
checks absolute executable paths and rejects temporary checkout/interpreter/state
paths by default. Reinstalling unloads the old job first and retries `launchctl
bootstrap` up to three times, because unloading finishes asynchronously; a
persistent failure exits 4. `--no-load` writes the plist only; `render-plist` previews it
without installing. `--allow-temp-checkout` is an explicit temporary-test override.
Install checks gh authentication unless `--skip-auth-check` is explicitly used.
The subprocess environment does not forward `GH_TOKEN`/`GITHUB_TOKEN`; gh must
have a persistent local login. It retains only normal PATH/home/config-location
settings and disables interactive prompts. No token is present in plist/state/logs.

## Ledger, recovery and API economy

The ledger lives in the configured state directory, guarded by exclusive `flock`.
Writes use fsync plus atomic replacement. Slots have stable IDs such as
`close-2026-10-02-a`, and dispatch intent is durable **before** calling gh. A
restart inspects the exact audit label in the workflow run title. Unrelated
manual runs cannot be adopted just because their timestamps are close. A known
covering scheduled/manual run is tracked by its run ID and can trigger bounded
recovery if it fails; merely being queued is not delivery.

On wake, only the latest slot in the previous 12 hours is eligible; earlier slots
are superseded and older ones expire. No weekend or long-outage replay storm is
performed. A corrupt ledger is preserved under a unique backup filename and
starts with a 15-minute dispatch hold. This reduces immediate repeats but cannot
recover perfect history after arbitrary state loss. Keep the persistent state
when updating/uninstalling. A clock moving backwards by five minutes to one hour
pauses new work until it catches up to the last tick time. A larger jump back to
a time inside the calendar range is treated as a corrected clock: future-dated
slot records written under the wrong clock are dropped, a corruption hold keeps
at most 15 minutes from the corrected time, retry timers keep at most the longest
(20-minute) backoff, intent/poll times restart their bounded windows, and
dispatch counts recorded under a future date are added to today's fuse. Terminal
slot history is kept, so a single bad reading cannot halt the service for days or
cause repeats. A clock reading outside the calendar range keeps the pause. Refresh the checked-in
calendar before expiry and after exceptional NYSE closure announcements.

Failed attempts use persisted 2/5/10/20-minute backoff, at most four attempt cycles
per slot; workflow failures can consume at most two acknowledged dispatches per
slot. Both budgets are shared: a re-dispatch after a failed run is allowed only
while attempts remain, so list outages earlier in the slot reduce later recovery.
The fourth failed attempt ends the slot, so its final 20-minute backoff is
not normally used. A UTC-day fuse caps acknowledged dispatches at eight.
Every gh subprocess has a 45-second timeout. If a dispatch times out or loses its
connection, its write is **uncertain**, not immediately failed: successful run
listings inspect the exact label for ten minutes before a bounded retry. An
unavailable listing is not proof that no run exists. Unresolved tracking ends
after three hours with `untracked`, without a blind repeat. GitHub has no caller
idempotency key for this endpoint, so at-least-once dispatch under ambiguous
network outcomes cannot be eliminated; bounded retries/caps limit that risk.

`requested` means GitHub acknowledged a request. `running` requires a matching
run. `succeeded` requires a completed successful run. `delivered` additionally
requires the manifest to show both a build timestamp at/after the request (with a
two-minute clock tolerance) and research covering the slot's expected completed
NYSE session. A fresh FRED timestamp with older research cannot establish
`delivered`. `succeeded_unchanged`, `failed`, `run_cancelled` and `untracked` retain
the actual limitation. The manifest establishes publication on GitHub main;
production UI/API delivery must still be verified separately.

Idle/terminal ticks make **zero gh API calls** and do not append logs. Tracked
slots poll at most every two minutes; a tick shares one run-list and one manifest
result across all tracked slots. A dispatch tick uses at most one list plus one
dispatch (and possibly one shared manifest if an earlier job completed). With
45-second call limits, a busy tick can take up to about 135 seconds, so 60 seconds
is an intended cadence rather than an execution guarantee. Launchd and the ledger
lock prevent overlapping dispatch passes. Ordinary operation requests at most
three slots per weekday, with fallback coexistence often reducing dispatches.
A later GitHub cron can still run redundantly after a watchdog-triggered build; this ledger does not deduplicate GitHub's independent schedule trigger or promise exactly one build per slot. Tracking is bounded; failed listings use the same backoff budget. These requests
consume GitHub API and Actions resources. Private-repository minutes or deployment
builds may count against account plans; no paid cloud scheduler is provisioned.

Visitors load the bundled artifact and perform bounded quote refreshes. Only
pending/overdue research probes a small manifest, at most once per 15 minutes per
instance; the 6 MB artifact is fetched only for a newer listed version. Hash,
source coverage and research-block checks reject corrupt, older, inconsistent,
incomplete or future-session artifacts. Failure keeps the last real observations.
This path performs no daily provider-history downloads or model computation.
Current same-session FRED updates normally arrive through the deployment triggered
by snapshot commits; a current-artifact visitor does not poll GitHub repeatedly.

## Verify and operate

Verify the actual background context after installation or any path relocation:

- Inspect the loaded LaunchAgent, an advancing `last_tick`, its last exit code and
  `launchd.out.log`/`launchd.err.log`. A plist on disk or a successful foreground
  dry run alone does not prove the job can read its checkout or start its executables.
- Run the same read-only `status --github` command through a one-off LaunchAgent
  using the installed job's interpreter, gh path, checkout, working directory and
  environment. Inspect its captured JSON for `gh_authenticated: true` and successful
  run/manifest reads, plus its exit code/logs, then remove that probe job. Running
  `status --github` in a terminal checks foreground auth, not background access.
  An idle Sunday tick makes no gh calls, so a healthy heartbeat alone cannot prove
  background gh authentication.

After installation, verify all of the following before claiming the refresh
service operational: launchctl service loaded, recent tick/state/log, a real
matching workflow request, run outcome, manifest advance/expected research date,
and anonymously fetched production API/UI showing the actual new source dates.
A Sunday installation can correctly be idle until Monday; use the existing
workflow's authorized manual dispatch for a publication smoke check and report
that it does not yet prove a due watchdog slot ran. No script test substitutes
for the final production delivery check.

`status --github` performs bounded read-only gh checks. Local `status` reads the
ledger/service only. State/logs distinguish missed ticks, authentication/API
failures, queues, cancellations and unchanged data. Unknown terminal outcomes do
not erase the UI's stale/overdue warning. For a manual retry after an expired or
untracked slot, invoke the existing GitHub workflow through the normal authorized
operator workflow rather than editing ledger counters to appear successful.

```sh
"$WATCHDOG_PYTHON" "$CHECKOUT/scripts/dispatch_watchdog.py" uninstall \
  --state-dir "$WATCHDOG_STATE"
```

Uninstall preserves state/logs for deduplication. Optional `--purge-state` removes
only recognized watchdog files and leaves unrelated directory contents intact.
The service requires a stable reviewed checkout; update it deliberately when
shipping later revisions. Offline tests use fake gh/launchctl and real temporary
ledgers, without provider requests, credential access or actual dispatch/install.
