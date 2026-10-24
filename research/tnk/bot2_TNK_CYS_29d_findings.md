# Bot 2 – MEXC Spot TNKUSDT / CYSUSDT research

Research only. 25 Sep–23 Oct 2026 UTC, 29 completed days. MEXC genuine 1m data: 41,760 bars per coin, 100% coverage; verified MEXC Spot exchangeInfo for both pairs. HKS production 15m SMC signal function and baseline trailing function imported unchanged. No live trades, no exchange order fills. LONG only; reject SHORT. 3 SL multipliers: 100%, 75%, 50% of original ATR stop. 3 trailing models: original coupling, decoupled baseline to original ATR distance, or alternative trailing activated at +1R with rolling 2x 1m ATR and fee breakeven. 2 hypothetical roundtrip cost levels: 0.2% and 0.5%, not actual exchange fee/slippage. This is a hypothesis screen, NOT a validated strategy edge.

Fixed $250 notional per trade, independent $1,000 starting wallet per coin/scenario, 1 open position per coin. Fixed notional isolates SL tightening from increased position sizing; the production paper position-sizing and multi-coin constraints differ, so do not label it production-equivalent. No fixed TP/partial TP was added; existing virtual 2R trailing retained in baseline. Stop checked before favorable-high update, new trail effective from next completed 1m candle; within-candle OHLC still has no tick order. MFE/MAE are approximate, not fill guarantees.

29d eligible signals: TNK original LONG 11 with score>=75, SHORT 0. CYS original LONG 0 and SHORT 0 with score>=75. CYS zero-trade rows reflect absent setups, NOT poor execution or predicted profits.

Score>=85 original-ATR baseline HKS trailing TNK (0.2% costs): 4 trades, 3 winners, $16.724 net on fixed $250 notional per entry. 75% SL: 5 trades, 3 winners, $7.673. 50% SL: 5 trades, 2 winners, -$6.549. Threshold and sample size too small for selecting live rules. See full CSV for both cost assumptions and ATR trailing variants. Sample period includes only recent 29d, not 180d genuine 1m.

No code merged or deployed. Do not buy historical data without user permission. No external accounts or credentials used.


## Wider-period 15m signal audit — 180d (not 180d 1m execution backtest)
Period 27 Apr–23 Oct 2026 UTC, 17,280 complete MEXC 15m and 4,320 complete MEXC 1h candles per pair; 0 gaps.
- TNKUSDT: 35 original eligible LONG (score >=75), 23 SHORT filtered; 12 eligible LONG at score >=85.
- CYSUSDT: 11 original eligible LONG (score >=75), 2 SHORT filtered; **5 LONG at score >=85**. None of these CYS qualifying signals occurred in the recent 29d genuine 1m test window.
This confirms CYS can be included in the proposed Bot2 watchlist but gives no validated 1m exit PnL for the old signals.

## Live MEXC Spot order-book friction (2026-10-24 snapshot, not historical)
Approximate instant buy and immediately sell same base asset, no transaction fee, no market movement, using publicly displayed resting book at the snapshot:
| Notional | TNKUSDT no-fee round-trip depth/spread friction | CYSUSDT |
|---:|---:|---:|
| $25 | 0.7505% | 0.3626% |
| $50 | 0.8257% | 0.3626% |
| $100 | 1.0011% | 0.3626% |
| $250 | 1.2952% | 0.4692% |
These are **only momentary** order-book estimates, not historical fill costs, nor stable future costs. TNK may be substantially worse during rapid pumps/reversals. Do not report +1.67% as realistically executable when the strategy assumed only 0.2% round-trip costs.

## TNK score>=85 original SL and original trailing, $250 fixed notional, 4 paper trades, 29d
| Hypothetical **total** round-trip cost (including any spread/slippage + fees) | Hypothetical paper NET on $1,000 wallet |
|---:|---:|
| 0.2% | +$16.724 |
| 0.5% | +$13.696 |
| 1.0% | +$8.649 |
| 1.5% | +$3.602 |
| 2.0% | -$1.445 |
This is a constant-cost stress test on the same four historical modeled exits, **not** an order-book re-simulation at each historical minute. True historical spreads and executable fills unknown.

## Research decision
1. CYS is retained as a Bot2 MEXC Spot LONG-only *research watchlist* item, **not enabled to trade** until a tested entry/exit record exists.
2. TNK threshold 85 + **original full ATR stop and original trailing** is the leading tentative candidate for forward paper observation. It is **not verified profitable after real spread/slippage**.
3. The 75% and 50% SL-tightening hypothesis failed to improve 29d matched-period results. Do not promote tighter stops just because initial-stop losers have low MFE.
4. Alternative 1m ATR trailing marginally changed the recent original-stop sample, insufficient to replace existing trailing.
5. Future Bot2 should have its own dashboard/wallet/ledger/scanner, and historical bid/ask-aware paper execution. TP is unchanged; no partial TP introduced.
6. No merge, deployment, account operation, historical-data payment or production change.
