# Exact Replit publishing and persistence verification

The application is prepared for Replit, but no Replit account or service was
accessed. PostgreSQL availability, your account's production database entitlement,
published-domain setup, dependency installation and actual redeployment must be
checked in your account. Do not enable billing or buy resources merely to follow
these instructions without your own explicit decision.

1. Open your existing Replit project. Upload/extract the complete V2 source ZIP
   or import the exact published Git branch. The root must contain `app.py`,
   `.replit`, `gunicorn.conf.py`, `requirements.txt`, and `backtester/` with
   `web/index.html`, `web/app.js`, `web/style.css`. Replace source deliberately;
   leave existing wallet SQLite files untouched. No command resets/reads them.
2. Open **Database** and inspect the offered database. The app needs a persistent
   PostgreSQL connection usable by the **published** service. In Publishing /
   database settings, link/create a production database if your plan permits it.
   An editor filesystem file is not the production database. If only an upgrade
   or payment prompt exists, stop before publishing: durable storage is an actual
   prerequisite. You may configure an already-owned external PostgreSQL instead;
   this build does not provision one or assume Cloud Console adds free storage.
3. Open **Secrets** and set these for the published deployment:

   | Name | Value supplied privately by you |
   |---|---|
   |`DATABASE_URL`|The actual production PostgreSQL connection URI; TLS required (`sslmode=require` minimum; prefer `verify-full` with trusted CA where supported)|
   |`HKS_PUBLIC_URL`|Exact proposed/published HTTPS origin, e.g. `https://your-name.replit.app`, with no path/query|
   |`HKS_BACKTEST_TOKEN`|A new cryptographically random owner token,32–256non-whitespace characters; never a shared demo password|

   Generate the token privately in your own terminal with
   `python -c "import secrets; print(secrets.token_urlsafe(40))"` and enter it only
   in Secrets and the login page. Do not commit it, put it in a URL, or send it in
   chat. Rotate the secret/restart if exposed. Token rotation does not reset data.
4. In **Publishing**, confirm Python3.12. Build:
   `pip install -r requirements.txt`. Run:
   `HKS_BACKTEST_ENV=production gunicorn --config gunicorn.conf.py app:app`.
   Port is `$PORT`, default8080, mapped to public80. The included `.replit` forces
   production settings. Do not launch the retired scanner or Python3.9 Spacefile.
5. Publish manually. Startup fails closed when a token, HTTPS public origin,
   PostgreSQL driver or reachable durable DB is missing. Check logs for safe
   configuration errors; do not copy Secrets/DB URLs into chat. `/health` checks
   the web process; `/ready` additionally checks the database and should return200.
   API requests require HTTPS at the Replit TLS proxy. A development-preview URL
   differing from `HKS_PUBLIC_URL` is intentionally not an allowed production host.
6. Open the exact published HTTPS URL. Enter your owner token. In Historical Data
   Manager select the actual market, symbol and interval. Upload an authentic CSV
   or official single-CSV ZIP and its `.CHECKSUM` if available. Source identity is
   your declaration plus the retained evidence; no exchange credentials needed.
7. Confirm inserted record count, coverage, missing intervals and checksum/source
   receipt. Select the corresponding persistent cache dataset in Backtester.
   Select both symbols if available; choose UTC dates with all `slow+1` prior
   completed warm-up candles. Do not start at the first file's very first candle
   unless earlier warm-up data was separately supplied.
8. Run Shared and Individual modes. Keep the browser open while short jobs run.
   Verify RUNNING→COMPLETE or a visible failure, reconciliation and CSV exports.
   Repeat the exact run: result hash should match and import/download counters
   should not increase. Test a changed saved SMA version using the same cache.
   This creates a new test result, never a live trading activation.

## Required actual Replit persistence check

Before relying on stored history:

1. Record the cache series IDs, counts, source SHA-256, coverage, a saved strategy
   version ID and a completed report/result hash. Export the result CSV locally.
2. Ensure no job/import is running. Restart the published app using its own UI.
   Reopen the same HTTPS URL and authenticate. Compare all recorded values.
3. Republish the identical source. Repeat the inventory/report/hash comparison.
   Run the identical test again from cache. No source download/import should occur.
4. If your settings permit an instance replacement or new app instance using the
   same production DB, verify the same values there. Do not enable paid scaling
   merely to perform this check. Keep the initial deployment at one instance if
   that is the only configuration available; distributed SQL locks are tested
   locally but actual Replit scaling behavior remains your environment check.
5. If data disappears, stop using the deployment until `DATABASE_URL` points to
   the actual durable production store. Do not compensate by copying a runtime
   SQLite file, resetting wallets or declaring `HKS_DATA_DIR` persistent.

## Interrupted work and rollback

Stale backtest phases older than3minutes become INTERRUPTED, not successful. Rerun
the deterministic test from cached data; completed results are immutable. Do not
assume a scale-to-zero server finishes an unattended background job. This build
supports short bounded requests, not a 24/7 scanner or a multi-hour worker.

If an import/download is interrupted with a retained series lock: stop every
instance/importer first, then, in an owner-only shell with the production DB
secret already injected, run:

```sh
python tools/manage_data.py recover --confirm-workers-stopped
```

This only marks incomplete jobs/imports interrupted and clears unusable staging
rows/operation locks in this app's schema. It does not delete cached candles,
completed reports, strategy versions, wallet tables or old SQLite files. Never
execute it while another instance is writing.

Rollback code through your chosen previous Git revision/source package. Keep the
same persistent DB and its stored data; do not drop the schema/database or restore
an old SQLite copy. Completed V1 compatibility reports remain readable. Provider
backup/export facilities are independent of runtime files; production backup
execution is outside this code-delivery task.
