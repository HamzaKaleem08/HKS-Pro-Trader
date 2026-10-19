# Published OLD SMC Reverse compatibility fix — verified live

**Fixed on the published build:** https://hks-pro-trader-browser-staging.pages.dev/

Verified at 2026-10-19T16:28:58.929100+05:00 (Asia/Karachi).
Deployment: `4e72d91b-a911-4f57-9691-5ccda6139d51`.
Public application source hash: `6515a14170b92630450b935d4176090d9c974778a5e6dc0a7636d40f624b43bf`.

## Actual cause and change

The original code was delivered for a locally tested compatibility build that had
not yet been published. The old deployed Context had no `candles` method and at
most 501 base one-minute bars. The exact owner-reported AttributeError was reproduced
in real Chromium on the stable HTTPS URL, with genuine cached candles and explicit
Futures consent, before making changes.

Only five public assets were changed: `app.js`, `index.html`, `kernel.json`,
`strategy-worker.js`, `sw.js`. No schema, wallet, default strategy, financial formula,
private Terminal, Replit, ABG, Git repository or billing setting was modified.
The owner-specific Python strategy file is outside web/ and was not published.

The existing browser Sandbox now supports bounded, declared completed 15m and 1H
UTC context from verified 1m input, with missing/partial/future context rejected.
Fifty completed 15m bars and 21 completed 1H bars require 1,320 pre-window minutes
including the conservative partial-hour allowance. No evaluation window is shortened.
The exit-fill-window observation preserves the legacy no-reentry-on-exit-candle rule.

The original entry/scoring/session/ATR/50%-80%-trailing formulas remain unchanged.
Only final direction reverses. The historical session is a score bonus, not a hard
ban; dual-sweep LONG precedence and OR confirmations are retained. Initial stop
fractions and updated stop prices are serialized to the existing API's 18 fractional
places, rounding half-even with at most 0.5e-18 numerical representation error per
outgoing value. No validation was removed. Projected 2R never becomes a TP-hit exit;
there is no partial TP in this strategy. Trailing uses completed 15m closes and
becomes effective at the following 1m open, without retroactive stop tightening.

## Actual successful live market tests

These were real browser executions at the published URL, not syntax checks, mocked
signals, server-side Python or reports substituted for fresh calculations.

BTCUSDT and ETHUSDT, genuine bundled November 2025 Binance USD-M Futures 1m cache.
Main window: November 2 23:00–November 3 03:00 UTC. Additional original-LONG/reversed-
SHORT window: November 17 14:00–16:00 UTC. Required pre-window history was included.
Both wallet modes used the exact supplied source, risk fraction .01, max positions 3,
fee 10 bps/side, adverse slippage 2 bps/side and KEEP_OPEN. ETH had zero qualifying
signals; it was not silently replaced. These are compatibility examples, not an
independent profitability study or full-month test.

| Actual live case | Executed side | Closed / open | Realized net USDT | Unrealized USDT | Equity change after paid fees |
| --- | --- | ---: | ---: | ---: | ---: |
| shared-genuine | LONG | 1 / 0 | -2.54754288948129632707584 | 0 | -2.54754288948129632707584 |
| individual-genuine | LONG | 1 / 0 | -2.54754288948129632707584 | 0 | -2.54754288948129632707584 |
| shared-reverse-short | SHORT | 0 / 1 | 0 | 3.07402938880840 | 2.8240303226655916 |
| individual-reverse-short | SHORT | 0 / 1 | 0 | 3.07402938880840 | 2.8240303226655916 |

Each of the four complete live financial results matched the independently audited
local result exactly, including its full result hash. Shared starts at $1000 total;
Individual at $1000 per symbol ($2000 combined). The open SHORT's marked equity is
not realized profit and includes no assumed future closing fee. Its genuine
close-based trailing stop tightened from 95861.552425714285743332675160 to
94929.544578857142851333, with entry 95084.879220; independent recomputation matched.

## Verification completed

* 50 Python tests and 9 JavaScript tests passed.
* 44 synthetic observation checks executed inside the real published opaque-origin
  Python worker; normal/reversed sides, legacy scoring, session and ATR boundaries,
  non-clamped serialization, mirrored trailing, ratchets, exit-candle guard and
  invalid/future context rejection all passed.
* All 14 original financial examples executed on the published URL: 12 complete
  successful result objects/hash pins matched frozen V4 results, including partial
  accounting; 2 invalid examples were rejected as expected.
* Independent result hashes, signal qualification/direction, SL, sizing, quantity,
  trailing and wallet/fees/slippage/PnL reconciliation passed for all four live cases.
* Actual closed-trade CSV exports matched journals. Open-only cases correctly show
  'No records to export'; no nonexistent closed trades or fills were manufactured.
* Exact source, report and diagnostic consent survived reload. Fresh trust
  acknowledgement remains required by design.
* A genuine live Individual checkpoint was persisted, the page reloaded, then fresh
  financial and strategy workers restored it. The entire recovered result exactly
  matched the uninterrupted result. The two cached monthly candle records and
  hashes remained unchanged, and the recovered journal exported successfully.
* Live desktop Chromium, isolation headers, opaque worker origin and 412px mobile
  layout emulation passed. Physical Android testing was not available.
* All 13 original pinned financial modules and all 19 reviewed source-file hashes
  remain unchanged after publication. No new credential matches were found in the
  public upload; no credentials were supplied to the browser.

## Honest limits and preserved QA failures

An existing disposable pre-upgrade Chromium profile initially loaded old cached code;
its later full-process relaunch timed out in the local launcher. Automatic old-profile
upgrade was therefore NOT certified. No cache, database or owner data was cleared to
make this check pass. Use a hard refresh before pasting; on Windows Ctrl+Shift+R.
Do not clear site data. Actual new-build reload persistence and worker checkpoint
recovery passed independently. Physical Android and full OS/browser-process recovery
on the owner's machine remain unverified.

Earlier verification-driver failures are retained: expecting a CSV for a zero-closed-
trade case, and an initial combined fixture pass that aborted at its second fixture.
The latter did not record a precise error; the complete fixture set was independently
rerun in a clean real browser and all 14 passed with no source change. The final
receipts distinguish these attempts from successful checks.

The unchanged 1x/25%-allocation cap can size below the 1% risk budget. The three-
position maximum is per wallet, not globally across independent wallets. Funding,
liquidation, historical exchange filters and actual exchange fills remain uncertified;
Futures outputs are diagnostic. No real/demo orders were placed.

## Paste and run

1. Open the stable URL and hard-refresh the updated application (Ctrl+Shift+R on
   Windows). Do not delete site data, strategy history or cached candles.
2. Paste the complete `examples/hks_legacy_smc_reverse.py` source. Select 1m execution;
   the strategy obtains its completed 15m/1H context automatically.
3. Set risk .01, maximum positions 3, selected wallet mode, a covered UTC window,
   explicit diagnostic Futures consent and trusted-code acknowledgement. Run.

The tested strategy definition ID is
`PYTHON_V1_3fe0dbe04e6fb837d0cfaacc3b031b521c55d36acee0253fc546a06563e159f8`.
Exact paste-file SHA256: `d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e`.

Evidence resides in `deployment/smc-live-20261019/`: `FINAL_LIVE_RECEIPT.json`,
`DEPLOYMENT_RECEIPT.json`, `STATIC_UPLOAD_MANIFEST.json`, before/fresh/regression live
browser records, complete result archives, actual CSVs/screenshots,
`INDEPENDENT_LIVE_FINANCIAL_AUDIT.json`, and `live-recovery/RECOVERY_EVIDENCE.json`.
The reusable live test driver is `tools/verify_smc_published.py`. Browser profiles
contain disposable test state and are excluded from the evidence hash inventory.
