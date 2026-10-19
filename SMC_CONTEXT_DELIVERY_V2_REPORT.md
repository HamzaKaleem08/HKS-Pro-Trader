# Published Sandbox Context API correction V2

Final status: PASS for the requested online SMC compatibility workflow.

Website: https://hks-pro-trader-browser-staging.pages.dev/?sandbox=completed-context-v2

## Cause and narrow correction

The old published Sandbox Context has no candles method. Its unversioned runtime assets and missing Context capability handshake allowed a stale browser profile to continue executing that old API. The original disposable QA profile retained cache hks-premium-static-83131fb94e91e133, whose worker had neither the compatibility patch nor the new Context class. This was independently observed in live-original-profile-verified/BROWSER_EVIDENCE.json.

The actual browser Context class now exposes candles('15m') and candles('1h'), with independent chronology, completeness, UTC alignment, OHLCV, freshness and no-future validation. Data comes only from the verified, causal financial broker; returned Candle tuples are immutable. The preserved original Context and 13 Decimal/financial modules remain byte-identical. No strategy code was changed.

Runtime files are now loaded through a checksum-pinned manifest and versioned URLs. A worker must prove the expected Context contract, timeframes and runtime identity before on_bar is invoked. Bootstrap waits for its static runtime update. Service-worker changes preserve IndexedDB/OPFS; canonical document cache lookup also supports versioned entry queries and Cloudflare's extensionless HTML routes.

An already-open old JavaScript realm cannot be safely replaced during a running job. Use the versioned entry URL once; do not clear site data. A copy of the actual pre-fix QA profile took that path and preserved every existing dataset, job, strategy version, setting and verified candle byte/hash before the successful runs.

## Actual final published three-day runs

Period: 2025-11-02 00:00 UTC inclusive to 2025-11-05 00:00 UTC exclusive.
Data: genuine checksum-verified Binance USD-M USDT perpetual Futures BTCUSDT and ETHUSDT 1m candles, with 1,320 pre-window minutes for completed 15m / 1H context. No Spot substitution or fabricated bars.
Settings: 1m execution, 1% risk budget, maximum 3 positions per wallet, 10 bps fee per side, 2 bps adverse slippage per side, KEEP_OPEN. Existing 25% capital allocation cap and all accounting rules remain unchanged. Individual mode has two independent $1,000 wallets; its total is not one shared account.

| Mode | Starting total | Ending total | Net realized USD | Closed / open | Measured replay |
|---|---:|---:|---:|---:|---:|
| shared | 1000 | 997.45245711051870367292416 | -2.54754288948129632707584 | 1 / 0 | 81.20s |
| individual | 2000 | 1997.45245711051870367292416 | -2.54754288948129632707584 | 1 / 0 | 96.61s |

Both runs closed one BTC LONG (original SHORT reversed), at INITIAL_STOP. ETH had no signals/trades. Additional genuine 2025-11-17 14:00–16:00 UTC runs executed a SHORT in both modes, tightened the legacy trailing stop, and retained one OPEN position; unrealized PnL was not called realized profit. The full four short-window financial result objects match their previously frozen results exactly.

Shared result SHA256: 7160f0c0d79a98c5f412f1c2865ec854359a4af759d6e6d649ea753a86ea4199
Individual result SHA256: 75654c2be87a71e05cfa3001777f2a9c66f8551a1fa4501eb0934bc5bd76b670

The final published three-day runs each executed 8,642 real Pyodide callbacks and made ZERO candle download requests, reusing the verified existing cache. Each complete result object matches the prior live run, including ledger, fills, fees and result hash.

## Executed verification

- 56 Python tests passed; 0 failed.
- 16 JavaScript tests passed; 0 failed (9 existing consent tests + 7 Context/delivery tests).
- 44 actual isolated Pyodide strategy/API checks passed, including reverse sides, legacy scoring/session boundaries, ATR precision, trailing, exits and invalid/future context.
- 14 original financial browser fixtures passed locally: 12 exact full-result/native-hash matches and 2 expected invalid-input rejections.
- Both final published three-day wallet runs passed; trade detail opening and actual downloaded CSV row counts were checked.
- Independent signal, reversed direction, fill/slippage, ATR stop, sizing, fees, final stop and cash/equity reconciliation passed on final live results (maximum Decimal residual 1e-20).
- Current report hash, exact strategy text and consent survived page reload and a genuinely new Chromium process.
- Original QA datasets/jobs/reports/candle hashes survived the update. Offline reopening of the versioned report link passed after the single-asset cache correction.
- Checkpoint recovery produced exactly the same full financial result in local and live browser tests.
- Chromium mobile viewport 412×915 passed overflow checks. Physical Android was NOT available/tested.

## Preserved source and deployment

Exact unchanged strategy SHA256: d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e
Strategy version: PYTHON_V1_3fe0dbe04e6fb837d0cfaacc3b031b521c55d36acee0253fc546a06563e159f8
Context contract: HKS_BROWSER_COMPLETED_CONTEXT/2 (backward-compatible with this file's /1 requirement).
Runtime source hash: 158621d515ab70e0a3b1759f6d73db2c6818481ac29ce0fba71ed7cb2e07e6a4
Final Pages deployment: 3f09eb4b-f8d9-4679-9c75-e08ccd2b49db.
Final static-cache build: 89075a3d4ba8f4e6.

Only the existing staging site was published: the first correction uploaded 10 runtime assets; the offline-routing follow-up uploaded one service-worker asset. CSP, browser sandbox, financial worker, storage implementation, trading formulas, fees/slippage logic and the strategy file remain unchanged. No Replit, private HKS/ABG project, Git push, exchange action or billing change.

## Limits and unsuccessful attempts retained

These are DIAGNOSTIC Futures price replays. Historical instrument filters, funding and liquidation are not certified. This validates compatibility; it is not profitability certification. The existing browser trusted-code limitation remains: this is an opaque-origin browser worker, not OS-container isolation for hostile code.

An extra fully offline Python initialization test timed out at the existing 12-second deadline. Fully offline recomputation is NOT certified. Offline reopening of completed reports is independently verified; no isolation policy or deadline was weakened.

Earlier interrupted/timed-out verification attempts remain in the deployment evidence directory, including an unverified live cached upgrade and the genuine offline query-routing failure that prompted the one-asset correction. They are not counted as successful tests. Final authoritative evidence is final-published/FINAL_LIVE_EVIDENCE.json plus its independent audit and FINAL_PYTHON_TESTS.log. Physical owner-device behavior is not remotely observed.

Review: SMC_CONTEXT_DELIVERY_V2.patch and SMC_CONTEXT_DELIVERY_V2_SHA256.json. All evidence stays outside the public web/ directory; the strategy is not installed as a public website default.
