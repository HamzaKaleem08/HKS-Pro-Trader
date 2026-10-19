# Legacy SMC Reverse — local compatibility implementation report

Status: **LOCAL EXECUTION VERIFIED; NOT PUBLISHED**.
Completed at: 2026-10-19T15:44:01.116417+05:00 (Asia/Karachi).
No deployment, push, exchange connection/order, paid resource or private HKS Terminal change.

## Delivered

* Complete paste-ready `examples/hks_legacy_smc_reverse.py` (owner file outside `web/`).
* Generic bounded, causal `ctx.candles()` and read-only `ctx.last_exit` observations.
* Pre-window 15m/1H coverage selection, upfront warm-up rejection and original
  checkpoint/source-identity safeguards. Financial loop/accounting/sizing unchanged.
* `SMC_REVERSE_COMPATIBILITY.md`, review patch and `SMC_SOURCE_SHA256.json`.

## Actual incompatibilities and corrections

1. The preserved website supplied at most 501 base 1m candles and no multi-timeframe
   API. Twenty-one completed 1H candles could not be obtained at test start.
   `CONTEXT_TIMEFRAMES` now requests bounded verified UTC aggregates. Only buckets
   completed by the callback's timestamp cross into the isolated strategy worker.
   A conservative 1,320-minute pre-window input requirement is enforced separately
   from the existing base-history limit. Gaps/partial hours are never synthesized.
2. A real non-clamped ATR value exceeded the existing execution validator's maximum
   18 fractional decimal places. The paste strategy now explicitly rounds outgoing
   fractions and stop prices half-even to that representation (error <=0.5e-18 per
   API value). ATR/clamp/progress formulas and the validator itself are unchanged.
   The pre-correction source and failing genuine SHORT test are preserved in review
   and attempt evidence; the final strategy passed that same genuine signal.
3. Read-only symbol/account exit fill windows preserve the old same-15m exit-branch
   continue, even if a position opened and stopped during one minute. The observation
   is rebuilt from the restored simulation ledger, without changing any trade.

The historical source session condition is a score BONUS, not a hard trading-hours
ban. Original dual-sweep LONG precedence and OR MSS/FVG scoring are preserved.
Only the final execution side is reversed. No TP-hit exit or partial TP is added.
Hourly look-ahead and retroactive stop application are excluded as requested.

## Executed verification

* **50 Python tests passed, 0 failed, 0 skipped** (30 preserved + 20 new).
* **9 JavaScript tests passed, 0 failed**; JavaScript syntax checks also passed.
* **44 actual opaque-worker Pyodide synthetic observation checks passed**, including
  both reversed sides, session/score boundaries, dual sweeps, ATR clamps and non-clamped
  serialization, mirrored 50/80 trailing, ratchets, no TP/partials, exit-candle guard,
  and intentional rejection of future/missing/duplicate/invalid contexts.
* **14 preserved examples actually ran in Chromium**: all 12 successful complete
  financial objects/hashes matched their frozen native V4 expectations exactly;
  two invalid-input examples were rejected as expected.
* **4 final-version genuine-market runs passed**: both wallet modes, both reversed
  execution directions. Two different historical BTC signal events are exercised;
  these are four mode-specific simulations, not four independent market events.
* Fresh-worker checkpoint restart matched the COMPLETE uninterrupted Individual
  result exactly. Actual UI source validation, two CSV exports, completed report
  reload, persisted source/consent and a fresh-session trust acknowledgement were
  tested. No success was inferred from a running process or from stored fixtures.
* Independent result-hash, original score/side, next-open adverse fill, initial ATR
  SL, 1% current-equity budget, capped quantity, original trailing final stop, fees,
  slippage, realized/unrealized PnL, reserves, cash and equity checks all passed.
  Four entry records and six mode-specific account checks reconcile within 1e-20.
* Sandboxed desktop Chromium and 412px mobile EMULATION passed; physical Android
  and the published website were NOT tested with this unpublished candidate.
* All 13 pinned financial modules and 91 original snapshot source files remain
  byte-identical. There were no market downloads or package installations.

## Genuine cached-candle examples (diagnostic only)

BINANCE USD-M USDT linear perpetual Futures; BTCUSDT + ETHUSDT; genuine November
2025 normalized 1m cache with pinned compressed/plain/original archive hashes.
Verified cache: 43,200 1m candles per symbol; 2,880 full 15m and 720 full 1H aggregates
per month. Retrieval timestamp is unknown; no receipt has been invented.

Final windows: November 2 23:00–November 3 03:00 UTC, and November 17 14:00–16:00 UTC.
Both include the required pre-window history. The first exercises an original SHORT
executed LONG; the second original LONG executed SHORT. ETH has zero qualified
signals in these windows. Periods are deliberately selected functional coverage,
not an independent performance study or strategy optimization.

Fee 10 bps/side, adverse slippage 2 bps/side, risk fraction .01, maximum positions 3,
KEEP_OPEN end policy. Shared starts with $1000 total; Individual starts $1000 per
symbol ($2000 combined). Returns from these capital bases are not interchangeable.

| Run | Starting capital | Closed / open | Realized net | Unrealized | Equity change after paid costs | Browser seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| shared-genuine-result | 1000 | 1 / 0 | -2.54754288948129632707584 | 0 | -2.54754288948129632707584 | 7.26 |
| individual-genuine-result | 2000 | 1 / 0 | -2.54754288948129632707584 | 0 | -2.54754288948129632707584 | 8.15 |
| shared-reverse-short-result | 1000 | 0 / 1 | 0 | 3.07402938880840 | 2.8240303226655916 | 6.65 |
| individual-reverse-short-result | 2000 | 0 / 1 | 0 | 3.07402938880840 | 2.8240303226655916 | 5.82 |

The SHORT remains OPEN; its positive marked equity is not realized profit and does
not include a future exit fee. Actual close-based trailing tightened that genuine
SHORT from 95861.552425714285743332675160 to 94929.544578857142851333 (entry
95084.879220). The independent calculation confirmed this stop. Reference TP was
never installed as an exit. MFE alone did not retroactively tighten the stop.

Earlier pre-precision candidates also completed 3-day November 2–5 runs in both
modes; these are retained under attempt evidence and are not mislabeled as final
strategy-version runs. Final short windows avoid unnecessarily repeating those
long runs after fixing the outgoing-number representation.

## Limits requiring disclosure

* This is diagnostic Futures price replay: funding, liquidation, historical exchange
  tick/lot/notional filters, order-book liquidity and true exchange fills remain
  uncertified. Funding is unknown, not claimed to be verified zero.
* The unchanged engine budgets 1% equity but its 1x/25%-allocation cap can size below
  that risk. The three-position maximum is per wallet; Individual accounts can have
  more than three positions in aggregate. No global cross-wallet cap is claimed.
* Projected 2R is used for progress only; the report's executable target is null.
* The original rule tightens on completed **15m closes**, not intraminute MFE peaks.
* Existing saved data are not deleted. Old interrupted jobs cannot silently resume
  under a changed application identity. Recreate a test from saved source/settings.
* No native trading activation, paper/live execution or protected private strategy
  registration is added. Python remains browser trusted-code-only, not an OS sandbox.
* Current supplied/public browser build lacks this context API. Publication needs
  separate owner approval. This local verification is not a deployment claim.

## Evidence and reproduction

* `evidence/smc-compat-v1/browser/BROWSER_EVIDENCE.json`
* `evidence/smc-compat-v1/browser/*-result.json.gz`, trade CSVs and screenshots
* `evidence/smc-compat-v1/browser/INDEPENDENT_ENTRY_AUDIT.csv`
* `evidence/smc-compat-v1/browser/INDEPENDENT_RECONCILIATION.json`
* `evidence/smc-compat-v1/PYTHON_TESTS.log`, `JAVASCRIPT_DIRECT.log`
* `evidence/smc-compat-v1/CACHE_VERIFICATION.json`, `GENUINE_SIGNAL_ORACLE.csv`
* Preserved initial failures: advanced-panel and trust-acknowledgement test-driver
  mistakes; actual non-clamped precision rejection; stale prior-job test-driver race.
  Final verification resumed only already completed results with matching application
  identity AND immutable strategy-definition hash. No failed result is called success.

Actual final strategy definition ID:
`PYTHON_V1_3fe0dbe04e6fb837d0cfaacc3b031b521c55d36acee0253fc546a06563e159f8`

Paste file SHA256: `d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e`.

Final result hashes:

* `shared-genuine-result`: `ecac7b314f5ed728ae0e43985164cd490fc1a123fb1d8489767c5739e7a3513b`
* `individual-genuine-result`: `dac59912925bfab390603462d76299ecfdc2b2fc6407dc77fbd10a22700ab470`
* `shared-reverse-short-result`: `11aa487ea09fb3541d2a5b746dcf8e0ca158964908126914b4f99657316eac95`
* `individual-reverse-short-result`: `70a182165d2cabd29d63258379a6c6b7935a2de3d3e24d7f2cf4fb2640c318da`

Use the commands in `SMC_REVERSE_COMPATIBILITY.md`. New browser evidence directories
must be unique. `--resume-evidence` verifies definition hashes before carrying over
already verified results; it never bypasses the application's checkpoint identity.
Next owner action: approve publication of ONLY this reviewed compatibility update
if it should become usable on the existing staging website. No publication performed.
