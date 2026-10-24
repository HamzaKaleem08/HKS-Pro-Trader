# HKS Pro Trader — Bot 2 MEXC Spot PAPER on Vercel Hobby

**Hosting:** Existing Vercel project `hks-pro-trader`, GitHub repo `HamzaKaleem08/HKS-Pro-Trader`, persistent external PostgreSQL, cron-job.org. No new hosting account or paid data required.

**Change:** PR #6 adds one new `/bot2` dashboard for **TNKUSDT and CYSUSDT together**, independent Spot paper wallet, positions, trade history, 1m candle archive, scanner and health. Bot 1 stays at `/`, with its original Bitget Futures 70-coin logic, wallet, owners, login, reset and cron. Production `main` remains the release branch.

## Verified requirements
- Vercel: existing connected Git repository, framework Flask, domain `https://hks-pro-trader.vercel.app`, Hobby plan.
- Protected persistent env keys already on Vercel: `DATABASE_URL`, `HKS_RESET_PASSWORD`, `HKS_CRON_TOKEN`. Do not output values or put them in URLs.
- Vercel Hobby **cannot register cron schedules more frequent than daily**. Do not add a `*/1` Vercel Cron: it would reject deployment. Continue using independent external cron-job.org schedules.
- No new Python requirements; Bot 2 `bot2_spot.py` and `templates/bot2.html` installed alongside existing Flask app.
- Serverless workers are not reliable background engines. Bot 2's independently authenticated request-bound endpoint `GET /api/bot2/cron` handles genuine completed 1m bars each minute.
- Existing `/wake` remains exclusively Bot 1. **Do not change its already running cron-job.org task.**

## Before production promotion
1. Review/merge the GitHub PR only after CI and Vercel preview are **READY**.
2. Confirm an actual connected Vercel preview renders `/bot2` and `/api/bot2/state`; check production `/` Bot 1 baseline. No production wallet reset or schema replacement.
3. Bot 2 defaults to **disabled** (`HKS_BOT2_PAPER_ENABLED` absent or `0`), so the dashboard can deploy without opening paper positions automatically.
4. Check separate `hks_b2_*` tables; they are additive and isolated. Existing `hks_*` tables remain untouched. If preview and production share the same `DATABASE_URL`, previews can create the Bot 2 tables; they never alter existing Bot 1 wallet/positions.
5. Production release is the approved PR merge to `main` (the existing Vercel Git integration triggers a production deployment automatically), or use a deliberate Vercel create-deployment targeting the reviewed SHA.

## After production release — paper activation
- Add **production** environment setting `HKS_BOT2_PAPER_ENABLED=1` through Vercel Project Settings → Environment Variables, then redeploy **that reviewed production commit**. Do not change `DATABASE_URL` or any existing secret.
- Initial paper sizing assumptions: `HKS_BOT2_NOTIONAL_USDT=50` per buy, `HKS_BOT2_FEE_RATE=0.001` (0.1% per side), `HKS_BOT2_EXIT_SLIPPAGE=0.003` (0.3% additional modeled exit loss). They do not assert actual exchange costs. Optionally set `HKS_BOT2_MAX_SPREAD=0.012` and `HKS_BOT2_MAX_BUY_IMPACT=0.015`.
- In cron-job.org add **a new independent** every-minute job (leave Bot 1 existing job alone):
  - URL `https://hks-pro-trader.vercel.app/api/bot2/cron`
  - Method `GET`, interval **every 1 minute**.
  - Request header `X-Cron-Key` set to the **already configured private** `HKS_CRON_TOKEN` value. Do not put it in query strings.
- After 2–3 successful minute checks, inspect `/api/bot2/state`: scanner success timestamp, 2 coins, fresh genuine MEXC 1m prices, no stop/decision gaps and error messages. Check live Vercel runtime logs for DB/retries.

## Locked paper V1 strategy
- MEXC Spot 2 coins: TNKUSDT + CYSUSDT, **LONG-only**.
- **Original HKS SMC 15m / 1h**, min trade score **85**. SHORT filtered.
- **Initial SL** = `2 × original ATR-derived stop fraction` (original 0.8–3% clamp, initial x2 1.6–6%).
- **Trailing** = original HKS function with reference `2 × original ATR stop`, **not 2 × widened SL**, same activation, threshold and next completed 1m candle timing.
- Existing virtual TP/trailing reference unchanged: no new TP1, fixed TP or partial close.
- Paper buy uses public MEXC ask book; spread and impact gates; exit uses genuine completed 1m OHLC stop plus explicit estimate of 0.3% slippage (not verified exchange fill).
- Independent account begins with $1000. No real orders. One open spot position per allowlisted coin. Owner-authenticated manual paper close uses public MEXC bids.
- Archives genuinely observed MEXC 1m OHLC forward only; older 5m proxy for CYS **must not** change locked strategy.
- Monitor free DB storage growth (2 coins x 1440 candles/day); do not promise limitless retention.

## Important deployment caution
If Bot 2 is enabled but its **independent** cron-job.org job has not been set, `/bot2` may appear ready but **it will not scan unattended**. Do not report 24/7 trading until repeated scheduler executions were verified. On Vercel Hobby, configured Vercel Cron at 1m is not allowed.

## Rollback
Vercel dashboard → choose previous known-good production deployment and rollback if site regression. Pause the **new Bot 2 external cron** while investigating. Do not wipe PostgreSQL tables or reset existing Bot 1 wallet.
