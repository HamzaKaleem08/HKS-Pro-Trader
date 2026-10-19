# Legacy SMC Reverse compatibility — owner review

This is a local, isolated compatibility candidate. It has **not been deployed**.
The original browser workspace and the private HKS Trading Terminal are unchanged.

## Paste file and website prerequisite

Copy the complete contents of `examples/hks_legacy_smc_reverse.py` into the Python
editor. The currently published browser build does not provide `ctx.candles()`;
publication of this reviewed compatibility patch needs separate owner approval.
Do not paste into the old build expecting equivalent 1H/15m behavior: it supplies
at most 501 one-minute candles, insufficient for 21 completed hourly bars.

The generic browser update adds `HKS_BROWSER_COMPLETED_CONTEXT/1`:

* Declare `CONTEXT_TIMEFRAMES = {"15m": 50, "1h": 21}` as a literal dictionary.
* Use `ctx.candles("15m")` and `ctx.candles("1h")` for completed UTC aggregates.
  The current incomplete hour is excluded. Requested context is bounded to two
  supported timeframes and 2–64 bars each. No other symbol or future candles are
  supplied to a callback.
* The input composer requires 1,320 pre-window 1m candles (22 hours, including a
  conservative extra hour for non-hour-aligned starts). The two-bar base API
  warm-up is separate. Missing coverage is rejected before simulated entries;
  no shortening of the requested period or delayed in-window warm-up occurs.
* `ctx.last_exit` is None or a copy of the symbol/account's latest closed-leg
  timestamps, fill window and reason. It prevents reentry in the exit's 15m
  candle, including an entry and stop occurring inside the same minute. A fresh
  runtime reconstructs this observation from its restored simulation ledger.

## Settings

Select genuine Binance USD-M Futures, **1m execution**, risk fraction **0.01**,
maximum positions **3**, and explicit diagnostic Futures consent. Costs remain
user-selected assumptions; verification uses fee 10 bps/side and adverse slippage
2 bps/side. Use Shared for a single wallet or Individual for independent wallets.
The paste file does not override financial configuration or account sizing.

Starting November 1 at 00:00 is rejected because earlier warm-up is not bundled.
The final-version functional examples are BTC/ETH November 2 23:00–November 3
03:00, 2025 and a separate November 17 14:00–16:00 UTC reverse-SHORT coverage
example. Earlier-candidate 3-day November 2–5 runs are preserved separately;
their shorter decimal inputs passed, while the subsequent non-clamped ATR test
exposed the serialization issue corrected in the final version. These periods were
chosen to cover known signal branches, not to estimate profitability or select
better-performing parameters.

## Exact source rules

Owner-supplied legacy archive SHA256:
`bf4d04d5728c58a96daef26797c6a528c1344a1c72433d814f4c3acdb4dadb1e`.
The unchanged excerpts and hashes are recorded under
`review/smc-compat-v1/source-evidence` and
`evidence/smc-compat-v1/SOURCE_PROVENANCE.json`.

The 20-bar swing range is `[-25:-5]` of 50 completed 15m candles. A strict sweep
scores 35; applicable MSS 30; applicable FVG 15; original-side SMA21 alignment 10;
08:00 <= the **signal candle's opening UTC hour** < 22:00 adds 10. Entry score
is at least 75. Session is a **bonus, not a hard entry ban**. Equality with hourly
SMA21 gives SHORT bias. Dual sweeps preserve LONG precedence and the original
OR confirmation convention; opposite-sweep confirmation can therefore contribute
points. Final execution direction alone is reversed.

ATR is the simple mean of the last 14 true ranges. Initial stop fraction is
`clamp(ATR / signal_close * 1.5, .008, .03)`, applied to the actual next-open
adversely slipped entry. Initial stop distance times two is a reference projection;
it is deliberately not supplied as an executable target.

The existing execution validator allows at most **18 fractional decimal places**.
Outgoing stop fractions and updated stop prices are explicitly rounded half-even
to that representation, with error at most 0.5e-18 per transmitted value. Internal
ATR, score and progress calculations retain Decimal precision. An initial stop's
price effect is bounded by entry price times 0.5e-18; this is disclosed numerical
serialization, not a new risk/stop formula or a relaxation of the validator.

At a completed 15m close: below 50% reference progress, no trailing update; 50% to
below 80% locks 10% of projected distance; at/above 80%, lock
`floor(progress/5)*5 - 10` percent of projected distance. Stops ratchet only and
become eligible at the following 1m open. The prior stop protects the trigger
minute. LONG/SHORT mirror. There is no fixed TP-hit exit, partial TP or discretionary
new exit. The unchanged end-of-test option is an explicit simulator close, not
an SMC strategy signal; verification uses KEEP_OPEN.

## Necessary execution differences and limitations

* Old source accessed the unfinished hour and tightened a stop before testing
  that same candle's range. Both look-ahead defects are excluded as requested.
  This can change results compared with the defective original backtest.
* Stops are checked on genuine 1m candles between 15m evaluations; gap fills,
  adverse slippage, fees and conservative candle ordering remain the existing
  engine's behavior. No tick-level sequence or exchange fill is certified.
* The current engine budgets 1% of marked current equity. Its unchanged 1×,
  25%-allocation cap can produce **less than 1% actual planned stop risk**.
  It cannot guarantee an exact 1% position under those capital constraints.
* Three open positions is **per wallet**: three overall in Shared; Individual
  accounts can exceed three in aggregate across different symbols. A global cap
  across independent wallets is not implemented by this compatibility change.
* Projected 2R is computed for trailing. The report's executable `target` remains
  null by design; it has no reference-only TP column.
* Funding, historical exchange tick/lot/leverage filters, liquidation and liquidity
  remain uncertified. Results are diagnostic Futures price replay. No new exchange
  assumptions, financial formulas, strategy activation or orders were added.
* Existing source-identity checks remain strict. Completed reports/cache are
  retained, but a pre-update interrupted job cannot silently resume under a
  different application build. Start a new test with the saved source/settings.
* Browser execution remains trusted-code-only, in a separate opaque-origin Python
  WebAssembly worker. No OS-container or hard browser-memory isolation is claimed.

## Reproduction

No new packages are needed in this workspace. Rebuild generic runtime metadata:

```sh
cp browser_adapter.py runtime/browser_adapter.py
python -B tools/build_static.py
python -B -m unittest discover -s tests -v
node tests/test_replay_consent.mjs
python -B tools/smc_cached_evidence.py
python -B tools/verify_smc_browser.py --start 2025-11-02T23:00 --end 2025-11-03T03:00
python -B tools/reconcile_smc_results.py
```

Browser verification requires existing Playwright and system Chromium, a permitted
loopback server and the Chromium sandbox. It uses disposable profiles and local
bundled assets, never production browser storage. Evidence output directories
must be unique; preserve previous runs rather than overwriting them. The Python
strategy itself executes only inside browser Pyodide, never host/server Python.

See `SMC_COMPATIBILITY_REPORT.md` for executed results, hashes and review files.
