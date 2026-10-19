"""Owner paste file; NOT a public website default.

Requires HKS_BROWSER_COMPLETED_CONTEXT/1 compatibility build.
Use 1m execution, risk fraction 0.01, maximum positions 3.
The original session rule is a score bonus, not an entry prohibition.
"""
from decimal import Decimal as D, ROUND_HALF_EVEN

WARMUP_BARS = 2
CONTEXT_TIMEFRAMES = {"15m": 50, "1h": 21}


def api_number(value):
    # The existing execution API accepts at most 18 decimal places. Round only
    # the outgoing number; the ATR/progress formulas above that boundary stay
    # Decimal calculations. Maximum rounding error is 0.5e-18 per API value.
    return value.quantize(D("0.000000000000000001"), rounding=ROUND_HALF_EVEN).normalize()


def on_bar(ctx):
    # Evaluate only when a UTC 15m candle has fully closed. The context API
    # excludes the current/incomplete 1H candle, including at hour boundaries.
    if ctx.timestamp_ms % 900000:
        return None
    bars = ctx.candles("15m")
    hourly = ctx.candles("1h")
    b = bars[-1]
    if b.open_ms + 900000 != ctx.timestamp_ms:
        raise ValueError("Completed 15m context is missing or stale")

    p = ctx.position
    if p is not None:
        # Reference TP is a projection ONLY. No target/TP-hit exit or partial.
        distance = abs(p.entry_price - p.initial_stop) * 2
        if distance <= 0:
            raise ValueError("Initial stop must have positive distance")
        sign = D(1) if p.side == "LONG" else D(-1)
        progress = sign * (b.close - p.entry_price) / distance * 100
        if progress >= 80:
            locked = (progress // 5) * 5 - 10
        elif progress >= 50:
            locked = D(10)
        else:
            return None
        proposed = api_number(p.entry_price + sign * distance * locked / 100)
        stop = max(p.stop, proposed) if p.side == "LONG" else min(p.stop, proposed)
        if stop != p.stop:
            # Effective next 1m open; never applied to the trigger candle.
            return ctx.manage(stop=stop)
        return None

    # Preserve the old exit-branch 'continue', including an entry and stop
    # inside one minute. A closed trade is identified by its actual fill
    # window, not by server time or the later candle-close timestamp.
    if ctx.last_exit is not None:
        exited_in = ctx.last_exit["fill_window_start_ms"]
        if b.open_ms <= exited_in < b.open_ms + 900000:
            return None

    swing_high = max(x.high for x in bars[-25:-5])
    swing_low = min(x.low for x in bars[-25:-5])
    bull_sweep = b.low < swing_low and b.close > swing_low
    bear_sweep = b.high > swing_high and b.close < swing_high
    if not (bull_sweep or bear_sweep):
        return None
    bull_mss = any(x.close > swing_high for x in bars[-4:-1])
    bear_mss = any(x.close < swing_low for x in bars[-4:-1])
    bull_fvg = b.low > bars[-3].high
    bear_fvg = b.high < bars[-3].low

    # Deliberately preserve dual-sweep LONG precedence and the original OR
    # confirmation convention. Reverse does not change the score or HTF bias.
    original = "LONG" if bull_sweep else "SHORT"
    score = 35
    if (bull_sweep and bull_mss) or (bear_sweep and bear_mss):
        score += 30
    if (bull_sweep and bull_fvg) or (bear_sweep and bear_fvg):
        score += 15
    sma21 = sum((x.close for x in hourly), D(0)) / 21
    bias = "LONG" if hourly[-1].close > sma21 else "SHORT"
    if original == bias:
        score += 10
    hour = (b.open_ms // 3600000) % 24
    if 8 <= hour < 22:
        score += 10
    if score < 75:
        return None

    atr14 = sum((max(bars[i].high - bars[i].low,
                     abs(bars[i].high - bars[i-1].close),
                     abs(bars[i].low - bars[i-1].close))
                 for i in range(len(bars)-14, len(bars))), D(0)) / 14
    stop_fraction = max(D("0.008"), min(D("0.03"), atr14 / b.close * D("1.5")))
    executed = "SHORT" if original == "LONG" else "LONG"
    # The unchanged engine sizes from equity/risk, reserves capital, enforces
    # position limits and anchors SL to the actual adversely slipped fill.
    return ctx.enter(executed, stop_fraction=api_number(stop_fraction))
