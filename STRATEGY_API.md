# Browser Python Strategy API

The exact tested example is `examples/hks_legacy_smc_reverse.py`; its SHA-256 is
`d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e`.
It is an example for manual historical TEST, not the public website's default
and not an activated trading strategy. Its original /1 requirement is supported
by the backward-compatible current Context /2 API.

Strategies define `on_bar(ctx)` and bounded `WARMUP_BARS`. Read `ctx.history`,
`ctx.bar`, `ctx.close`, `ctx.timestamp_ms`, `ctx.position`, `ctx.account` and
`ctx.state`. The original `ctx.sma`, `ctx.atr`, `ctx.enter`, `ctx.exit` and
`ctx.manage` APIs are preserved. Supported execution instructions include
explicit entries, stops/targets, exits and reductions; the unchanged financial
interpreter validates them and controls fills, costs and wallet accounting.

Declare `CONTEXT_TIMEFRAMES = {"15m": 50, "1h": 21}` to use
`ctx.candles("15m")` and `ctx.candles("1h")`. These are immutable, chronological
tuples of completed UTC-aligned candles, causally aggregated from verified 1m
data. Current/incomplete candles, gaps and future context are rejected. The
example requires 1,320 minutes before the requested start; ranges are not
silently shortened for warm-up. `ctx.last_exit` contains bounded symbol-specific
close evidence or None.

Only the final execution direction is reversed by the example. Its 1H SMA21,
15m sweep/MSS/FVG scoring, historical session bonus, ATR stop and original 50/80
trailing behavior are preserved. The 2R target is a projection, with no explicit
TP-hit exit or partial TP in this particular example. Engine support for other
strategy-defined reductions does not add them to this strategy.

Use 1m execution, risk fraction 0.01 and maximum positions 3 per wallet for the
verified example configuration. Other financial limits and costs remain visible
in the UI. Individual wallets remain independent. Historical TEST/save has no
live, paper or demo activation effect.

This is trusted Python in a browser WebAssembly worker, not a hardened OS
container for hostile code. See `SECURITY_REVIEW.md` and the original source.
