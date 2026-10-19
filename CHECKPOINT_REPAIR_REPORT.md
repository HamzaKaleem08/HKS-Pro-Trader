# Browser Backtester — 20-coin timeout/checkpoint repair

Local review branch: `fix/browser-20coin-checkpoint-20261019`.
Baseline: `b06008eb64c482b0d4e507ed5f81495385e9c25e`. No push, merge, deployment or exchange operation performed.
Final tested runtime identity: `57ffc4a7599f96b5bf206701cad86a18a540040c27f64c017bb8e8a00aa8d65b`.

## Findings: facts versus hypotheses

- The original scheduler yields only every 120 global timestamps. With 20
  symbols that is approximately 2,400 symbol-minute steps per chunk.
- The unchanged baseline's bounded native desktop profile processed 21,612
  callbacks over 182.43 seconds; the worst of nine completed chunks was 21.80
  seconds. It was a partial profile, not a successful full baseline replay.
- A controlled 15 ms callback-scheduling delay reproduced the native 30-second
  wall-budget failure before the first ordinary checkpoint. The repaired build
  completed the identical genuine-candle two-hour stress input (2,420 calls),
  worst worker chunk 1.635 seconds, no candle redownloads. This reproduces the
  resource mechanism; it does not prove the owner's exact 32-second outer
  watchdog message or physical-device cause.
- Typed checkpoint output was redundantly traversed by `primitives()` after
  encoding; callback frames were canonically encoded twice. A 5,000-row native
  synthetic microbenchmark measured 235.81 -> 43.56 ms for byte-identical JSON.
  This microbenchmark is not a genuine replay speedup claim.
- Resume restored finance but the UI explicitly set progress to zero. Input
  verification/context indexing still rebuild on Resume; financial timestamps
  and callbacks before the verified cursor are skipped.

## Implemented engineering changes

Scheduling yields after complete global timestamps, targeting one second or
about 240 symbol-candle steps (rounded up to a whole timestamp). Progress yields
do not serialize the full history. An early durable checkpoint precedes the
existing 120-timestamp cadence. Equity, pending orders, stop updates, account
allocation and strategy callbacks retain their original order.

Checkpoint/event serialization uses the same strict canonical JSON options on
already primitive/typed data, with byte-equality and rejection tests. Frame
encoding occurs once. Resume displays its saved percentage immediately and
uses restored callback counts. Profiling fields are outside financial results.
All asset hashes, bootstrap URLs and service-worker references were regenerated.

No deadline was increased: native replay 30 s, parent watchdog 32 s, strategy
callback 3 s, sandbox startup 12 s, validation 15 s, strategy checkpoint 5 s,
foreground run one hour. Existing byte, candle, entry and checkpoint caps remain.

## Actual verification

- 63 Python tests, 18 JavaScript tests: passed, zero failed/skipped.
- 14 actual-browser financial fixtures: 12 exact valid-result matches and two
  expected input rejections; includes genuine fixtures in both wallet modes.
- UI synthetic partial-close oracle: $1,017.50, two exit segments; CSV/detail,
  report reload, Context /2 and responsive viewport passed.
- Original 13 financial source pins and exact OLD SMC code unchanged:
  `d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e`.
- All 20 genuine Binance USD-M symbols tested, not just displayed. Requested
  window is 2025-11-28 00:00 through 2025-12-01 00:00 UTC, end exclusive;
  1,320 pre-window input minutes, 112,800 total candles. There were 86,420
  callbacks, 4,321 evaluations per symbol. Data files were independently hash
  checked, including full-month continuity in native regression tests.
- New 7+7+6 control runs use identical per-symbol inputs; original owner batch
  output files were not supplied. Accounts, trades, stops, open positions,
  decisions, equity timelines, signal counts and reconciliation match.
- Forced checkpoint-boundary cancellation, new Chromium process, explicit
  Resume: full financial result equals uninterrupted output. No callback before
  saved cursor; the interrupted prefix plus resumed suffix matches all 86,420
  uninterrupted callbacks in exact order; progress never reset to zero. This is cancellation/process
  restart testing, not certification of every OS power-loss condition.

| Run | Status | UI seconds | Closed segments | Open positions | Candle redownloads |
| --- | --- | ---: | ---: | ---: | ---: |
| combined-20 | COMPLETE | 1016.94 | 1 | 0 | 0 |
| batch-1 | COMPLETE | 306.81 | 0 | 0 | 0 |
| batch-2 | COMPLETE | 307.23 | 0 | 0 | 0 |
| batch-3 | COMPLETE | 267.81 | 1 | 0 | 0 |
| interrupted-20 | CANCELLED | 188.27 | — | — | 0 |
| resumed-20 | COMPLETE | 690.71 | 1 | 0 | 0 |

Full and resumed result hash: `85299dff93e7a3e8debd7899e495e88366ed56905e8e35e5f712a47d9a538ac6`.
Combined ending equity: `19997.44754960000106569092316672` from $20,000 across 20 independent wallets.
There was one closed TRX SHORT, net -$2.55245039999893430907683328.
Independent Decimal wallet/trade reconciliation passed at 1e-20 tolerance.
Raw genuine results, callback traces and CSVs are retained under
`/workspace/hks-browser-checkpoint-review-20261019/final-genuine-verification-continuation`; source evidence summaries are in `evidence/`.

The owner confirmed the published defaults: $1,000 per coin, fee 10 bps per side,
adverse slippage 2 bps per side, 1% risk, max positions 3, KEEP_OPEN, explicit
diagnostic Futures consent. Those exact defaults were used for this campaign.
These are diagnostic hypothetical Futures price replays, not certified fills.

## Measured performance and resource limits

- Combined worker wall: 1008.88 s; financial initialization
  6.277 s; input validation
  3.137 s; context initialization
  0.356 s.
- Ordinary progress slice worst: 5.194 s.
  Durable snapshot slice worst: 21.809 s.
  Final result/report slice: 8.385 s.
  The one-second target is checked at safe boundaries; it is not a hard promise.
- 37 durable checkpoints; financial capture
  168.00 s total, max
  10.11 s; strategy snapshots
  0.784 s total; persistence
  29.26 s total, max
  1.774 s.
- Financial Wasm heap at completion 534.6 MiB;
  strategy 20.0 MiB. Peak sampled Chromium
  RSS sum 4.52 GiB (shared pages can
  be counted more than once; PSS was not obtained). This desktop used a four-CPU
  quota and 32 GiB container limit, Chromium 151.0.7922.173.
- Large full-history checkpoints still dominate late-run cost and memory.
  Ordinary work slicing does not make snapshot encoding constant-sized. Mobile
  and low-RAM reliability are NOT certified by this desktop success. No claim
  of an end-to-end speedup versus a completed original full run is made.

## Compatibility, preservation and rollback

Finance checkpoint schema 1, IndexedDB schema/name, OPFS names, dataset IDs and
checksums are unchanged. Reports remain readable. No owner production profile,
candle file or saved job was accessed; all tests used isolated disposable state.

Cross-runtime resume remains rejected before strategy restore. Old checkpoints
are preserved and the UI explains why Resume is disabled. The real local
old-build -> candidate -> old-build test preserved its report, candle cache and
checkpoint, then successfully resumed under the original build. This test's
temporary HTTP server disables incorrect mtime-based 304s when selecting an
older artifact; application security headers and checksum checks remain enforced.

Rollback means serving the exact original verified build (with its separately
preserved data), not editing a checkpoint identity. A candidate-created job
likewise needs its candidate build. Start a new test explicitly when changing
runtime versions; verified candle data is reused. Work after the latest durable
checkpoint may need recalculation; no pre-cursor financial callbacks are rerun.

## Commands and honest remaining gates

Executed: `python -B -m unittest discover -s tests -v` in an isolated copy with
all 26 excluded inputs restored, and `node tests/test_context_delivery.mjs`,
`node tests/test_replay_consent.mjs`, `node tests/test_replay_scheduling.mjs`.
Browser drivers: `tools/verify_twenty_coin_recovery.py` (full, synthetic and
latency suites), `tools/verify_checkpoint_upgrade.py`, and
`tools/verify_source_browser.py`. Their CLIs require preserved data and fresh
output directories. They use installed Linux Chromium; physical Windows and
Android tests were not performed.

A prior full verification campaign completed the combined 20-symbol run and
first two controls, but its last six-symbol control failed at 71.69% with
`Strategy response deadline exceeded` (the unchanged three-second RPC guard).
That campaign and its exact failure receipt remain immutable in
`final-genuine-full-campaign/`. This continuation verifies hashes and reuses
only its COMPLETE controls; it reruns the failed control in a fresh browser
process without changing application code or any deadline. This is a real
observed scheduling limitation, not a passing run or proof that every device
can meet the callback budget.

Earlier cold-start and harness failures and the intentionally interrupted
pre-serialization-optimization profile remain in `/workspace/hks-browser-checkpoint-review-20261019`; they are not
counted as passing acceptance runs. The first stress receipts' top-level dates
name the three-day target; `CHECKPOINT_REPAIR_STRESS.json` and the actual result
configuration explicitly identify the two-hour stress scope.

Verdict: mandatory local desktop replay/recovery assertions PASS. Not deployed.
Owner review and physical-device resource
testing remain before a staging publication decision. No permission to publish
or push is implied by the local tests.
