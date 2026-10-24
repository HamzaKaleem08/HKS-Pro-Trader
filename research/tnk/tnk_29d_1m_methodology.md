# TNK MEXC SPOT — 29-day real 1m historical candle validation (2026-09-25 through 2026-10-23 UTC)
Full downloaded dataset: 41,760 native MEXC 1m candles, 100% coverage, 0 gaps.
Cross-validation: 8,352 native 5m candles, reconstructed OHLC from 1m data, 0 mismatches.
Signals: unmodified HKS 15m SMC/ATR scorer; stops/trail: imported production HKS trail_stop/get_stop_fill, executed against 1m OHLC (not exact tick fills).
Normal LONG: 9 trades. Reverse-derived LONG: 0 eligible signals in this period.
Starting cash per cost scenario: $1,000. Costs: 0.2% or 0.5% round trip (assumptions, NOT verified fees/slippage).
1m Normal: 0.2% scenario -0.516%, 0.5% scenario -1.405%.
5m Normal, same 29d: 0.2% +0.151%, 0.5% -0.746%.
MFE/MAE columns in CSV are GROSS excursion of finished 1m candles preceding the exit-minute candle; omit the ambiguous exit-minute high/low rather than wrongly attributing post-exit extrema. Therefore they are conservative pre-exit observations, not exact tick-level MFE/MAE.
Important: even 1m backtest has intra-minute stop ambiguity and possible opening-gap fills; no order book, depth or exact fill verification. Do not merge research branch into production main. Older 180d 5m trade figures have not been revised and should be treated as provisional.
