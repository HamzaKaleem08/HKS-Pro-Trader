# Bot 2 – MEXC Spot TNKUSDT / CYSUSDT research

Research only. 25 Sep–23 Oct 2026 UTC, 29 completed days. MEXC genuine 1m data: 41,760 bars per coin, 100% coverage; verified MEXC Spot exchangeInfo for both pairs. HKS production 15m SMC signal function and baseline trailing function imported unchanged. No live trades, no exchange order fills. LONG only; reject SHORT. 3 SL multipliers: 100%, 75%, 50% of original ATR stop. 3 trailing models: original coupling, decoupled baseline to original ATR distance, or alternative trailing activated at +1R with rolling 2x 1m ATR and fee breakeven. 2 hypothetical roundtrip cost levels: 0.2% and 0.5%, not actual exchange fee/slippage. This is a hypothesis screen, NOT a validated strategy edge.

Fixed $250 notional per trade, independent $1,000 starting wallet per coin/scenario, 1 open position per coin. Fixed notional isolates SL tightening from increased position sizing; the production paper position-sizing and multi-coin constraints differ, so do not label it production-equivalent. No fixed TP/partial TP was added; existing virtual 2R trailing retained in baseline. Stop checked before favorable-high update, new trail effective from next completed 1m candle; within-candle OHLC still has no tick order. MFE/MAE are approximate, not fill guarantees.

29d eligible signals: TNK original LONG 11 with score>=75, SHORT 0. CYS original LONG 0 and SHORT 0 with score>=75. CYS zero-trade rows reflect absent setups, NOT poor execution or predicted profits.

Score>=85 original-ATR baseline HKS trailing TNK (0.2% costs): 4 trades, 3 winners, $16.724 net on fixed $250 notional per entry. 75% SL: 5 trades, 3 winners, $7.673. 50% SL: 5 trades, 2 winners, -$6.549. Threshold and sample size too small for selecting live rules. See full CSV for both cost assumptions and ATR trailing variants. Sample period includes only recent 29d, not 180d genuine 1m.

No code merged or deployed. Do not buy historical data without user permission. No external accounts or credentials used.
