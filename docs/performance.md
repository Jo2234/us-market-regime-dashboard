# Production performance audit — 2026-09-29

The final Yahoo path worked directly from Vercel. Five redeployments of each implementation were measured from Johan's Mac against the production alias, with the function in `iad1`. These are small, dated samples, not availability or latency guarantees.

## Request timings

Each cell is **median / maximum**, in milliseconds; **n = 5** per row and implementation. Request time includes the Singapore-to-Vercel round trip and response transfer.

| Request | Before (`d4c8ef3`) | Optimized (`56bcf7b`) |
| --- | ---: | ---: |
| First API request after redeploy | 6313.38 / 6592.56 | 1551.84 / 1789.20 |
| Warm instance, cache miss | 1512.92 / 1695.23 | 1227.09 / 1245.14 |
| Warm instance, memory hit | 1048.71 / 1181.90 | 837.72 / 884.95 |
| CDN hit | 15.20 / 274.76 | 19.63 / 407.74 |

The median first request improved by 75.4%. CDN results are dominated by network variability; they do not run application code. The CDN returns the original origin telemetry, so its replayed `fetch_ms` is not a new upstream fetch.

| Server measurement | Before median / max | Optimized median / max |
| --- | ---: | ---: |
| Import on first request | 3074.98 / 3294.31 | 518.75 / 536.34 |
| App processing, cold request | 1653.46 / 1853.29 | 804.63 / 819.42 |
| App processing, warm miss | 1271.36 / 1376.76 | 702.14 / 742.96 |
| App processing, memory hit | 641.11 / 718.03 | 350.52 / 364.61 |
| Yahoo batch, cold instance | 946.76 / 1061.33 | 385.18 / 401.25 |
| Yahoo batch, warm miss | 556.12 / 718.84 | 319.57 / 366.70 |

App time excludes module import and platform startup, while request time includes them. Local fresh-process import measurements (five each) also fell from median 338.0 ms / max 364.6 ms to 164.18 ms / 165.86 ms. Production measurements were the deciding evidence.

## Method and raw results

A deployment was created for every cold sample. The cold response had `X-Market-Request: 1`, a new `X-Market-Instance`, and a CDN MISS. The subsequent memory hit and forced warm miss used the same instance. A temporary authenticated POST diagnostic expired the in-memory cache for the warm-miss measurement; visitors never had an unauthenticated bypass. The repeated GET verified `X-Vercel-Cache: HIT`.

One baseline attempt reached a previous deployment's CDN entry during alias propagation. It was excluded and repeated, with its raw result retained. Later runs waited for alias propagation and used a deployment-specific query key; that key bypasses only the CDN entry, not the instance cache. Unique deployment URLs required Vercel authentication, so measurements used the public production alias.

- [Five baseline runs](performance/baseline.json)
- [Five optimized runs, including per-symbol five-day timings](performance/optimized.json)
- [Excluded alias-propagation sample](performance/baseline-excluded.json)
- [Earlier unsuccessful User-Agent configuration](performance/initial-user-agent-probe.json)
- [Temporary Vercel settings removal](performance/benchmark-cleanup.json)
- [Independent live-value verification](performance/live-verification.txt)

The temporary encrypted `MARKET_REGIME_BENCHMARK_TOKEN` and `MARKET_REGIME_BENCHMARK_EXPIRES` settings were removed and their absence verified. The diagnostics route was removed from the final application. No repository visibility, branch, quota, or permanent Vercel project setting changed.

## Fetch and rate-limit decisions

The final configuration had **0/375 HTTP 429 responses (0%)**, **0/375 HTTP 401 responses**, and no retries across the optimized measurements: five cold two-year batches, five warm two-year batches and five five-day batches, each containing 25 symbols. The valid baseline runs had 0/250 HTTP 429 responses.

An earlier configuration with a full Chrome-style User-Agent received **51 HTTP 429 responses across three failed batches**. Twenty requests were started per batch; 17 returned 429 before outstanding siblings were cancelled. The normal dashboard requests served the real, dated snapshot; the isolated five-day diagnostics probe returned 500. A local check also received 429 with that configuration. Restoring the previously verified minimal `Mozilla/5.0` User-Agent succeeded locally and in all five subsequent production runs. This is an observed configuration difference, not proof of Yahoo's internal blocking rules. The unsuccessful evidence is retained above rather than folded into the final configuration's success rate.

Eight concurrent requests share one HTTPX client/connection pool. Each request has an eight-second timeout, at most two retries for transport failures/429/5xx, exponential backoff plus jitter, and an 18-second batch deadline. Permanent 4xx responses fail immediately. On batch failure, outstanding tasks are cancelled and a validated last-known-good snapshot is served. Every refresh attempt, including total failure without a fallback, starts a 900-second cooldown. Concurrent visitors share a single-flight lock. Bootstrap requests only read real cached/snapshot data and never call Yahoo.

The five-day batch had median **259.33 ms**, maximum **275.07 ms**, versus **319.57 / 366.70 ms** for the warm two-year batch. Saving about 60 ms did not justify splitting adjusted histories: splits/distributions can revise older adjusted bars, and the dashboard still needs 1Y returns, 200-day averages and regime history even when its chart is set to 1D. The application retains one coherent two-year dataset per 15-minute refresh window, shared by all views and API endpoints. Switching views does not cause extra downloads within that window.

Pandas/NumPy and exchange_calendars were removed from the request path. Standard-library calculations match the previous implementation exactly on recorded Yahoo data across four dates, all six return windows, market blocks, charts and regime classifications. The NYSE schedule is generated offline, retains holiday/DST/early-close behavior, and must be maintained after exceptional closure announcements and before its 2031 expiry.

The cache is per instance plus CDN, not a global distributed quota: newly scaled instances can each refresh once. Yahoo's unofficial service can still block requests. The committed scheduled snapshot remains necessary.

## Loading and failure checks

Chrome frames were inspected at 1200 px desktop and **375 px mobile**, using local development-only delays/failures and the real committed Yahoo snapshot. No requests were sent to Yahoo to deliberately force a rate limit.

| State | Desktop / 375 px result |
| --- | --- |
| Initial skeleton | Cards, index tiles, charts and table placeholders; no zeros; status changes after four seconds |
| Background refresh | Real dated SPY/QQQ values remain visible; Updating status and chip spinner; controls/layout retained |
| Refresh failure with data | Close date and last successful fetch time remain visible; explicit unavailable/retrying notice and Refresh button |
| Failure without real data | Friendly Live data unavailable page and Retry button; no example numbers |

Screenshots from the local inspection are retained in `/tmp/regime-qa` on the task machine. `aria-busy` is set on loading content; status messages have a polite live region outside it. CSS disables shimmer/spin/transitions under `prefers-reduced-motion`. Stable status slots prevent messages moving the mobile cards during refresh.

Validation: 36 backend tests and 32 frontend tests passed; the production Vite build passed. Backend tests block networking and cover recorded data, calculation parity, holidays, the single-flight lock, eight-worker/shared-session bound, retry counts, failure telemetry, cooldown with/without a snapshot, and the production demo guard. Frontend tests use deferred responses and fake timers for initial loading, the four-second message, immediate cached delivery, background replacement, retained-data failure, retry backoff/cooldown, error recovery and rejection of synthetic persisted data.
