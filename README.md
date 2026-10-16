# HKS Historical Backtester — deployable V2

A standalone Flask application for private, owner-authenticated historical tests.
The old scanner entrypoint has been replaced as explicitly authorized. No live
wallet, trading orders, exchange credentials or arbitrary code sandbox is used.
This is separate from the private HKS Trading Terminal and all Volume Sniper/ABG
research. The available strategy is **illustrative SMA**, NOT verified HKS
Normal/Reverse. Missing authentic strategies do not prevent using this app.

## What works

* Responsive data manager, strategy editor, backtest controls and report dashboard.
* Immutable saved structured strategy versions, with hashes; saving/testing never
  activates a paper/live strategy. Uploaded Python/JavaScript is not executed.
* Individual mode: one independent virtual starting account per selected coin.
* Shared mode: one shared wallet, chronological multi-symbol events, reserved
  capital/risk, deterministic simultaneous order allocation, explicit rejections.
* Completed-candle decisions, next-bar execution, stop/target ambiguity handling,
  fees, slippage, OPEN/CLOSED lifecycle, exact account reconciliation, MFE/MAE and
  sampled drawdown. Futures remains a clearly acknowledged diagnostic price model
  without certified funding/filters/liquidation.
* Searchable, sorted, paginated journal, individual trade detail, per-coin/monthly/
  exit reports and complete CSV exports.
* Background jobs return immediately; the UI polls durable status/phase progress.
  Failed/interrupted jobs never become invented successful reports.

## Persistent historical data — import once, reuse

Hosted mode stores normalized candles, coverage, source receipts, saved strategies,
job state and results in **PostgreSQL**, in its own `hks_backtester` schema.
Replit's container filesystem holds only temporary bounded exports/workers; it is
not treated as durable storage. No Replit Object Storage SDK/credentials were
available here; using PostgreSQL avoids pretending local SQLite is persistent.

The UI accepts normalized CSV, native Binance CSV, or a single-CSV ZIP, optionally
with its official `.CHECKSUM`. Select the actual market/symbol/interval. Enter an
honest source attribution. Original retrieval time stays unknown when not supplied.
Spot archives with genuine microsecond timestamps are normalized explicitly to the
millisecond grid; original bytes are hashed. No Futures-to-Spot relabeling.

Inputs are validated and staged in batches of500. Corrupt/gapped/duplicate input
or conflicting stored prices cannot overwrite committed candles. Reimporting the
same candles inserts zero duplicates. Coverage and exact missing ranges are
indexed; gaps across separate imports remain visible and block a requested run.

Optional public downloads use official Binance Spot or USD-M klines only. A batch
requests at most8 pages (1000candles/page),16MiB,8-second request timeout and a
45-second cooperative planning budget. HTTP403/429/denials, redirects and missing
history are not retried or replaced with another source. Repeat requests fetch
only missing intervals; fully cached coverage makes zero source requests.
Network collection was tested offline with fixtures, not via a real exchange
request from Codex. Native public access from Replit must be checked there.

All imports remain reusable across different saved strategies and both modes.
The data manager displays the latest100 import receipts; all receipts remain in
the persistent database. A declared exchange identity is not independently
authenticated solely by a normalized CSV; preserve authentic archives/checksums.

## Publish on Replit

Detailed steps: [REPLIT_DEPLOYMENT.md](docs/REPLIT_DEPLOYMENT.md).

1. Import this exact development branch/source ZIP into your existing Replit
   project, replacing the app source. Do not delete/reset old wallet database files;
   this app does not read them. No old-feature migration is required.
2. Link a **durable production PostgreSQL database**, not an editor-only or SQLite
   file. Replit Database may offer this depending on your account/plan. Check the
   production database connection in Publishing. If it requires an unapproved
   payment/upgrade, stop; no free production entitlement is assumed here.
3. Set three Secrets using Replit's secure UI: `DATABASE_URL`, `HKS_PUBLIC_URL`
   (the exact published HTTPS origin), and a freshly generated strong
   `HKS_BACKTEST_TOKEN` (at least32characters). Never send values in chat/Git.
4. Python3.12; build `pip install -r requirements.txt`; production run:
   `HKS_BACKTEST_ENV=production gunicorn --config gunicorn.conf.py app:app`.
   `.replit` already supplies these settings and forces production mode.
5. Publish manually. Open the HTTPS URL, authenticate, import a genuine small
   CSV/ZIP/checksum, choose a covered range **including indicator warm-up**, run
   each mode, inspect results and CSVs. No deployment was performed by Codex.
6. Verify cache/report persistence in YOUR Replit deployment after a restart and
   republish using [the checklist](docs/REPLIT_DEPLOYMENT.md). Local PostgreSQL
   restart/new-runtime tests passed; actual Replit redeployment was not accessed.

The root HTML contains only the login interface and local assets; every state/
data/mutation/export API requires the owner token. Tokens are kept only in page
memory. HTTPS, exact Host/Origin checks, no CORS, safe errors and upload/request
bounds are enforced. This is a single-owner app, not a multi-tenant login service.

## Local installation and tests

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests_backtester -v
.venv/bin/python -m backtester.cli init-demo
```

Supply a random owner token through your local environment, then run:

```sh
HKS_BACKTEST_ENV=local .venv/bin/python -m backtester.cli serve --port 8081
```

Open `http://127.0.0.1:8081` on that computer. Local mode uses SQLite and is NOT
proof of Replit durability. Synthetic demo creation is explicit, never a history
fallback. Local CLI includes the earlier synchronous compatibility mode; the
production `app:app` entrypoint always uses asynchronous bounded workers.

Windows: `py -3.12 -m venv .venv`, then use
`.\.venv\Scripts\python.exe` instead of `.venv/bin/python`. PowerShell local mode:
set `$env:HKS_BACKTEST_ENV="local"` and the token securely in that terminal.
Do not expose local HTTP outside loopback. Native Windows/browser execution was
not performed here; Linux worker hard limits are not available on Windows.

## Bounds and operational honesty

* Upload24MiB; ZIP expansion64MiB; one CSV/member; max700,000rows per import;
  strict UTC/OHLCV and hash checks. Identical overlaps are reusable, changes fail.
* Stored history can exceed a run's limit. A run snapshots only the chosen range
  plus warm-up in500-row batches. Up to20symbols/200,000candles/run. Missing or
  oversized ranges fail clearly; they are never shortened or synthesized.
* Cache export20s; simulation loop30s; worker40s wall, Linux512MiB address space,
  35CPU seconds,16MiB output,64file descriptors; max10,000entries. Large report
  output can reach the limit before the input ceiling. Select a shorter range or
  fewer symbols. Multi-year streaming computation is not claimed.
* One active job across PostgreSQL-connected app instances, and one import/fetch
  operation per exact series. Immutable price/version/report constraints remain.
* Completed reports/cache survive through the external database. Replit Autoscale
  may suspend/terminate background work during scaling or redeploy; **unattended
  job completion is not guaranteed**. Keep the browser open/polling for these
  short jobs. Stale job phases after3minutes become INTERRUPTED and can be rerun
  from the same cache; an old process cannot overwrite a completed/interrupted job.
  This is not a continuously running scanner or a heavy-job hosting claim.
* Interrupted imports retain no partial usable dataset. If an importer dies with
  a durable lock, stop all instances/importers and use the explicit owner recovery
  command in the deployment guide. No automatic destructive cleanup exists.
* Provider storage/compute limits and charges still apply. No billing was enabled
  and no claim of unlimited/free Replit database capacity is made.

## Evidence and limitations

See [V2_TEST_RESULTS.md](docs/V2_TEST_RESULTS.md) for actual counts, real Gunicorn,
PostgreSQL/TLS, genuine-data reuse and restart evidence. Browser automation remains
blocked by this environment's misconfigured Chromium sandbox helper. It was not
disabled. HTTP/static tests are not a claimed browser rendering pass.

Original V1 review archives remain unchanged locally. Older files under
`docs/backtester/` describe the historical foundation, not current deployment
configuration. The obsolete Spacefile was retired. No production, GitHub main,
private HKS project, ABG research or frozen detector was changed by this build.
