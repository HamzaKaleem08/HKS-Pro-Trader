# CYS MEXC Spot — 180d 5m research-only preliminary backtest

2026-04-27 through 2026-10-23 UTC. Genuine MEXC Spot 15m, 1h, 5m candles. 17,664 15m, 4,416 1h (both include 4d warmup), 51,840 5m (180d); all 100% coverage and 0 gaps.

**CYS score>=85 signal count: 5 LONG**, 3 simulated wins at every SL factor; score>=75: 11 LONG. Original production HKS SMC scoring and original 2R trailing both imported. SHORT explicitly excluded. Baseline original ATR stop x1, additional initial stop x1.5/x2; **trailing reference stays original 2*original_ATR_stop** under all factors. No TP changes.

| CYS score>=85 | Trades | Wins | Net USD at 0.2% total cost | Net USD at 0.5% total cost | Net USD at 1.0% total cost |
|---|---:|---:|---:|---:|---:|
| SL original 100% | 5 | 3 | +20.17 | +16.39 | +10.08 |
| SL x1.5 (150%) | 5 | 3 | +18.29 | +14.51 | +8.21 |
| SL x2 (200%) | 5 | 3 | +16.42 | +12.64 | +6.34 |

At 0.5% total cost, the CYS score>=75 subset produced: SL100% 11 trades, 6 wins, +$19.33; SL150% 11 trades, 6 wins, +$9.73; SL200% 11 trades, 8 wins, +$23.81. **Do not infer a superior score threshold or stop width from this 5m proxy.**

Test position notional $250 fixed, independent initial cash $1000, 1 position at a time; entry when 15m signal closes. Trade-by-trade and all summary scenarios saved separately.

**CRITICAL METHODOLOGY:** Genuine historical **1m CYS trades on these older dates were unavailable free**. This is a **5m OHLC simulation**. 5m candle high/low chronology is unknown; applying the newly tightened trailing stop from the next completed candle can cause theoretical exits at its open far below that stop, and may under- or overstate real performance. E.g. 2026-08-07 exit open $0.8202 despite previously tightened stop $0.830165, illustrating this precise risk. Therefore $12.64 is a **rough paper proxy, not verified executable profit**, and cannot validate the approved Bot2 rule. Spread, historical depth and slippage unavailable.

**Decision:** Bot2 paper V1 remains the user's approved research settings: TNK+CYS MEXC Spot long-only; min score85; 200% original ATR-derived initial SL, original trailing reference unchanged; TP unchanged. CYS remains exploratory; monitor real 1m candles prospectively before any strategy-performance judgment. Production Bot 1, wallet, risk, scanner and code unchanged, no merge/deployment or payment.
