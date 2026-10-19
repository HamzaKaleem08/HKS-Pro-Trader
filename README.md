# HKS-Pro-Trader — published Browser Backtester source backup

This standalone backup branch preserves the currently published Cloudflare
Browser Backtester, including its Premium UI, browser Python Sandbox, actual
completed-15m/1H Context API, isolated browser workers, Decimal financial kernel,
tests, configuration, documentation and exact verified OLD SMC Reverse example.

Published build: `3f09eb4b-f8d9-4679-9c75-e08ccd2b49db` (19 October 2026 UTC).
Site: https://hks-pro-trader-browser-staging.pages.dev/?sandbox=completed-context-v2

All included files under `web/` are the actual published files, byte-for-byte.
See `evidence/PUBLISHED_SOURCE_MATCH.json` for independent HTTPS comparisons.
Cloudflare's special `_headers` configuration is verified by its live response
headers. No website publication, `main` change, or trading-logic change is part
of this backup. The Pages project uses direct uploads and has no Git integration.

## What is included

- `web/`: exact production static application and pinned Pyodide 0.27.7 assets.
- `runtime/`: all 19 readable Python modules embedded in `web/kernel.json`.
- Root `browser_adapter.py`, `browser_stream.py`, `serve.py`, `wrangler.toml`:
  the original working adapters, local headers server and static Pages config.
- `examples/hks_legacy_smc_reverse.py`: the exact tested source, unchanged.
- `tests/`, `tools/`: current regression tests, build and verification sources.
- Eight explicitly synthetic fixture archives and synthetic/disposable-account
  financial regression oracles; these contain no production wallets.
- Integrity records, current verification summaries and original documentation.
  Documents in `docs/history/` describe earlier stages; use this README and the
  current `SMC_CONTEXT_DELIVERY_V2_REPORT.md` for present deployment status.

## Deliberate data exclusions

Historical candle caches and genuine-data fixture payloads are **not** in Git.
`HISTORICAL_DATA_EXCLUSIONS.json` lists all 26 omitted files with exact sizes and
SHA-256. Their catalogs/provenance remain unchanged. Genuine backtests require
those separately preserved files to be restored to their listed paths; this
source-only snapshot does not fabricate missing candles or substitute Spot data.

Browser profiles, cookies, owner settings, account/production databases, private
research, credentials, tokens and temporary test state are excluded. No private
Trading Terminal or ABG source is included. There are no deployment workflows on
this branch. No historical dataset is acquired automatically by backup tools.

## Restore and verify

```powershell
git clone --single-branch --branch backup/cloudflare-browser-backtester-20261019 https://github.com/HamzaKaleem08/HKS-Pro-Trader.git hks-browser-backup
cd hks-browser-backup
python tools/verify_source_backup.py
python serve.py --port 8097
```

Use current Chrome/Edge and open the local server on the same computer at
`http://127.0.0.1:8097`. Opening `index.html` as `file://` cannot provide the
required isolation headers. No API credentials or database are required.
The unchanged published UI bootstraps a fresh browser profile using
`web/fixtures/genuine_2coin_1day.json.gz`. Restore that checksum-matching excluded
fixture before opening the UI, even for synthetic tests. With this startup
fixture supplied, synthetic replays need no monthly market caches. Genuine
BTC/ETH or other market tests require the corresponding excluded data as well.
Source/unit checks remain available without those data files. Do not publish a
data-incomplete directory as a replacement live website.

`SOURCE_MANIFEST.json` records every source file and its role.
`SHA256SUMS.txt` hashes every payload file and the manifest; it excludes itself
to avoid a self-referential checksum. The Git commit pins the whole snapshot.
The verification tool checks checksums, runtime-source parity, pinned kernel
modules, the exact example hash, and absence of prohibited state/data paths.

## Testing

Python 3.12 runs the application and unit checks. Node.js 22+ runs the JavaScript
tests. No Node packages are needed for those tests. Optional real Chromium QA
requires Playwright; see `config/qa-requirements.txt` and `tests/README.md`.

```powershell
python -B -m unittest discover -s tests -p test_checkpoint.py -v
python -B -m unittest discover -s tests -p test_completed_context.py -v
python -B -m unittest discover -s tests -p test_futures_consent.py -v
python -B -m unittest discover -s tests -p test_sandbox_context_api.py -v
python -B -m unittest discover -s tests -p test_smc_compat.py -v
node tests/test_replay_consent.mjs
node tests/test_context_delivery.mjs
```

The complete 56-test Python suite additionally checks the excluded historical
files. After restoring those, run `python -B -m unittest discover -s tests -v`.
An optional 128-file legacy-archive integrity check explicitly skips if that
separate original V4 source is absent. Historical QA tools may also require
earlier source snapshots; their paths are documented in `tests/README.md`.
No incomplete run should be described as a complete historical validation.

## Execution and security scope

User Python runs in an opaque-origin WebAssembly worker with no network or
application-origin storage access. This remains **trusted-code-only** browser
execution; it is not OS-container isolation for hostile code and cannot enforce
a hard browser RAM ceiling. The financial interpreter is separate. Completed
candles, entries, stop changes, reductions, chronological wallets and accounting
retain their original behavior. Saving/testing does not activate trading.

The preserved limits are 1–20 symbols, 200,000 input candles including warm-up,
32 MiB total CSV, 10,000 entries, bounded callbacks/chunks and one foreground
hour. Four-year execution remains unavailable. Results are diagnostic Futures
price replays: historical filters, funding and liquidation are not certified.
Individual mode uses independent wallets; it is not one shared account.

Verified live: both BTC/ETH three-day modes, Reverse SHORT examples, journals,
CSV, cache reuse, checkpoint/reload/new-browser-process recovery. Physical
Android and fully offline Python recomputation remain unverified. Completed
reports can reopen offline in the verified browser path.

See `DEPLOYMENT.md`, `SECURITY_REVIEW.md`, `TEST_RESULTS.md`,
`STRATEGY_API.md` and `DEPENDENCIES.md`. Publishing remains an owner action and
is not performed by cloning or verifying this branch.
