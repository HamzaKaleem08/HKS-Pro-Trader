# Actual final test evidence

- `python -m unittest discover -s tests -v`:25passed,0failed,0skipped.
  `evidence/UNIT_TESTS_FINAL.log`. Includes13 preserved feasibility tests and12
  new checkpoint tests. Original326-test server baseline was NOT rerun or added
  to these counts; it remains historical evidence in the preserved V4 candidate.
- `python tools/verify_staging.py --origin http://127.0.0.1:8098 --output evidence/cloudflare-runtime-final`:
  28PASS integration checks,0failed; ordinary Chromium OS sandbox enabled.
  Playwright + actual local Pages/workerd; no real Android device or public site.
- All12 successful original native fixture results match whole-object and hash;
  both invalid fixtures rejected. No simulated market-data downloads occurred.
- `node --check` ran for app/client/strategy worker; Python module compile checks ran.
- Source/package secret-pattern scan and original/source/archive hash checks are
  in `evidence/PUBLICATION_SAFETY_SCAN.json` and `evidence/FINAL_PRESERVATION.json`.

Earlier attempts are retained, not overwritten: browser-run-1 completed20checks
then its Playwright string wait violated app CSP. The QA predicate was corrected
without changing CSP. browser-run-2 completed27checks on the static mirror. Final
run completed28checks on the actual Cloudflare local runtime. These are not added
together. No mandatory current test is failing. Public deployment and physical
Android remain UNVERIFIED, not passed.

Final browser checks:

- Actual premium page boots with COOP/COEP and normal Chromium OS sandbox
- Frozen native/browser parity: genuine_20coin_30min
- Frozen native/browser parity: genuine_20coin_6hours
- Frozen native/browser parity: genuine_2coin_1day
- Frozen native/browser parity: genuine_2coin_1day_individual
- Frozen native/browser parity: genuine_2coin_1hour
- Frozen native/browser parity: genuine_2coin_1hour_individual
- Frozen native/browser parity: synthetic_atr_gap
- Frozen native/browser parity: synthetic_hand_partial
- Frozen native/browser parity: synthetic_invalid_decimal
- Frozen native/browser parity: synthetic_invalid_stop
- Frozen native/browser parity: synthetic_long_trailing
- Frozen native/browser parity: synthetic_multicoin_costs_individual
- Frozen native/browser parity: synthetic_multicoin_costs_shared
- Frozen native/browser parity: synthetic_short_trailing
- Fresh Python worker restore at ALL 4 partial/stop/open boundaries yields exact full result hash
- Actual worker checkpoints preserve Decimal ctx.state and mutable global counters across fresh interpreters
- Actual premium Python editor → Run → exact $1,017.50 hand ledger → detail dialog → full CSV
- Invalid pasted draft does not replace last successfully tested strategy/settings/report across reload
- All 864,000 genuine monthly candles cached in OPFS; warm reuse downloads ZERO candle chunks
- 20 genuine symbols compose from month cache, run globally chronological Shared wallet, reconcile, zero redownload
- Cancel after durable genuine-data checkpoint → reload → UI Resume → exact frozen one-day result
- Actual journal pagination, symbol filtering and page reset
- Web Locks prevents a second tab from executing the same device runner concurrently
- Damaged OPFS checkpoint is rejected before any restoration; original disposable checkpoint restored
- Actual strategy worker stays opaque-origin, denies network and app storage, receives no server secret
- Fresh browser process restores genuine report, Python, settings and verified OPFS candle inventory
- Actual mobile emulation: touch Run, real Python partials, responsive width, details, CSV and reload persistence
