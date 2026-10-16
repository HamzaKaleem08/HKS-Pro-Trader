# Deployable V2 verification

Final executed suite: **142 tests passed,0failures,0errors,0skipped**, including
23 real PostgreSQL cases. Eight additional real production HTTP/storage checks
passed. JavaScript syntax check exited0. V1's91tests
remain represented; the original scanner fixture is historical and never mounted
by the new `app.py`. New tests cover persistent cache/reuse, strict imports,
checksum/ZIP handling, exact missing ranges, overlap locks, safe network-denial
behavior, asynchronous jobs, per-strategy reuse and interrupted-job safety.

The real production entrypoint was launched under Gunicorn gthread against a
uniquely created disposable PostgreSQL16 database using verified TLS and a trusted
local test CA. An existing cached Docker image was used, never pulled. Test-only
credentials stayed in private temporary files and were not logged/committed.

Actual acceptance evidence:

* Two genuine, previously inspected Binance USD-M Futures15m monthly September2026
  ZIPs and official CHECKSUMs imported through the authenticated multipart API.
  BTCUSDT/ETHUSDT:2880rows each,5760total. No network market download.
* September2–5 UTC demonstration SMA strategy, with exact warm-up. Shared run twice,
  Individual once, plus Shared after restart: five CLOSED/two OPEN positions per
  mode; reconciled cash/equity. These are diagnostic model results, not verified
  HKS Normal/Reverse performance or certified Futures profitability.
* Identical shared result hashes on repeat; zero additional import/source requests.
  Public-fetch receipt count remained0, cache import count remained2.
* PostgreSQL itself restarted; Gunicorn restarted with an entirely different empty
  runtime directory. Cache rows, saved version and completed report/hash survived.
  The same cached replay after restart returned the identical result hash.
* Full regressions were executed against SQLite and a separate disposable
  auxiliary PostgreSQL schema. This includes actual cross-instance import/job
  coordination, not merely SQL-string mocks. Ordinary CI without an explicitly
  disposable PG URL correctly marks the opt-in PG cases skipped, never passed.
* JavaScript syntax and static HTML/JS ID/local-asset checks pass. Chromium's
  existing SUID sandbox helper is misconfigured, so browser clicks/rendering and
  native Windows/Android remain unverified. No sandbox disabling or screenshots.

During testing, the PostgreSQL runtime initially lacked `typing_extensions` on
the selected interpreter's path. It was resolved using already-installed
dependencies, pinned explicitly in requirements, then the actual TLS/Gunicorn
integration passed. Failed attempts were retained locally, not concealed.

No dependency download, exchange call, production DB connection, Replit access,
billing, trading, detector change or private-holdout access occurred. Actual
Replit startup, account database entitlement and persistence across Replit
republishing are NOT claimed verified. Follow the owner checklist.
