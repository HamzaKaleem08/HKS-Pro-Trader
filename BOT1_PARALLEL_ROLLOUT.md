# Bot 1 parallel NORMAL / REVERSE — isolated review (26 Oct 2026)

**NOT DEPLOYED. NOT APPROVED FOR HOSTED CUTOVER.** Feature default: OFF. Bot 2 is unchanged.

## Owner-approved target
- Every qualified original 15m signal is evaluated once, then NORMAL uses the original direction and REVERSE uses the exact opposite.
- Existing original scoring, 17-point displayed convention, thresholds, fee assumptions, 1m stop-first/trailing causality and risk fractions are NOT edited.
- Each mode has its own $1,000 strategy ledger (including realized/unrealized performance), initial $2,000 virtual collateral, up to the existing 5-position cap **per mode**, isolated trade history, position state and equity curve.
- The extra $1,000 is collateral ONLY. The per-entry cash-fraction sizing uses the mode's $1,000 strategy ledger and is not doubled by the buffer.
- Both mode attempts are persisted atomically on each eligible signal. A rejected side is recorded with its reason; never invent the missing trade.
- Manual close requires matching symbol+mode; both remain independent.
- The old Bot 1 legacy tables remain untouched until the owner confirms Reset BOTH. All Bot 2 b2_* tables are outside this scope.
- No demo orders, exchange credentials or external trading API execution.

## Safe cutover after owner has screenshots
1. Owner saves screenshots of OLD open/closed trades and wallet graphs BEFORE any cutover.
2. Review this feature branch and focused tests; confirm code/DB backup and rollback.
3. Ensure all legacy Bot 1 positions can be safely retired/reset; do not silently abandon an open legacy position.
4. Only after explicit owner approval, deploy reviewed commit and enable `HKS_BOT1_PARALLEL_ENABLED=1` in the relevant Vercel environment. Feature is OFF by default.
5. Owner-confirmed **Reset BOTH** clears legacy Bot 1 finance/history and new mode ledgers; initializes each mode to $2,000 collateral + $1,000 strategy equity. Market scanner analysis state stays intact. Owner password, same-origin check and scanner lock still required. This is irreversible unless separate backup exists.
6. Hosted acceptance: one qualified synthetic/replay signal opens Normal LONG and Reverse SHORT (or mirrored SHORT/LONG), 2 isolated SL trails, 2 independent equity histories, reconciling wallets and 0 Bot 2 changes. Confirm live scanner cadence before calling 24/7 PASS.

## Critical limits / review checkpoints
- Synthetic 1m OHLC cannot establish intraminute exchange fill ordering.
- $2,000 collateral is not an extra $1,000 of strategy equity or risk budget.
- Market data/cache failure pauses both modes; old strategy still rejects when a score/position/cooldown rule fails.
- Legacy data clearing is permitted ONLY via explicit owner Reset BOTH action **after** screenshots; this draft branch does not delete production records.
- Green local tests alone would not establish hosted delivery, latency or independent ongoing scanning.
