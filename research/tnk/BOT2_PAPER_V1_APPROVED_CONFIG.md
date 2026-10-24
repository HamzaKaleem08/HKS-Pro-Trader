# HKS Bot 2 — MEXC Spot / PAPER V1 — Research Configuration Lock
Date: 2026-10-24 (owner-approved research selection, **NOT a production deployment**)

## Independent identity
- **Bot 1:** Existing HKS Bitget Futures engine, 70 dynamic coins, strategy, scanner, wallet, positions, and dashboard **unchanged**.
- **Bot 2:** Separate MEXC Spot-only scanning, wallet, ledger, configuration and dashboard under HKS. Research watchlist **TNKUSDT and CYSUSDT**. Long-only: original SHORT signals are **never traded** and REVERSE does not bypass filter.
- Initial deployment scope: independent forward **paper/demo simulation** only. No real orders, credentials or funds.

## Locked V1 research rules
1. Signal: import **unchanged production HKS 15m/1h SMC/ATR scoring**; minimum **Score 85**.
2. **Initial SL = 200% of the original ATR-derived stop distance** (original formula clips 0.8–3% before multiplying; final price SL 1.6–6%). Price distance doubles, so dollar risk at fixed notional doubles.
3. **Trailing reference stays exactly at original 100% stop's virtual 2R reference**. Original trailing activation at 40% of that reference, interpolation and profit-lock all unchanged, with new stop effective from next completed candle. No coupling of trailing distance to widened initial SL.
4. **TP unchanged**: do not insert automatic partial TP, TP1, or new exit rules.
5. Fixed $250 notional was used **for controlled historical tests only**. This is not a mandate to size forward paper orders at $250; decide independent Bot 2 paper risk controls before enabling.
6. Both market-data feeds and execution-price assumptions must come from **MEXC Spot**; no switching to Bitget Futures candles or false liquidity.
7. Costs/assumed fills: separate assumptions, account for bid-ask spread/depth and slippage in forward paper PnL. Historical candle OHLC does not guarantee executable orders.
8. Selection based on TNK's 29d true 1m research is a **candidate for forward testing**, not established profitable edge; strict no paid datasets.

## Evidence/limitations
- TNK: 29d native MEXC 1m candles from 2026-09-25 to 2026-10-23 UTC; Score85 200% SL + original trailing = 4 trades, +$25.773 net at 0.2% assumed *total* cost, +$22.732 at 0.5% assumed total cost, $250 notional each, $1,000 independent wallet.
- Sample contains only 4 trades and **cost assumptions** may materially understate actual MEXC spot bid/ask-depth execution impact.
- CYS: zero score>=85 signals in this 29d 1m dataset. Longer 180d 15m/1h audit had 5 eligible LONG signals; true older 1m candles were not free. CYS older 5m-only tests are exploratory and cannot validate genuine 1m trailing fills.
- Halt/skip scanner when data gaps or exchange API errors occur; do not synthesize candles.

**Change control:** Locked as approved Bot 2 **research / proposed forward-paper configuration**. No merge, production rollout, wallet mutation or alteration to Bot 1. Actual Bot 2 implementation and activation remain separate reviewed steps.
