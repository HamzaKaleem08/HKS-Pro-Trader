# Bot 2 / MEXC Spot — Replit Autoscale deployment & activation

**Status (2026-10-24): code prepared and CI tested in PR #6. NOT merged, NOT applied to the owner's live Replit app, and NOT activated.** There is no Replit deployment confirmation in GitHub.

## Safety gate (before merging or deploying)

1. Confirm Replit's **actual running app.py** and repository state against GitHub `main`; `app.py` in GitHub states that this is a lightweight stand-alone PAPER implementation, not the user's historical production financial kernel. **If they differ, reconcile first; never overwrite/Replit-import blindly.**
2. Back up persistent PostgreSQL (wallet/trades/positions/owner sessions), deployment secrets and Replit source. Do not reset or migrate any Bot 1 records. No secrets in git or log output.
3. Review PR #6 and CI: `Bot 2 Paper Isolation Checks` plus `HKS Owner Review Tests`, both passing as of 2026-10-24.
4. Only after source parity/backups, make the new `bot2_spot.py`, `templates/bot2.html`, and small `app.py` registration/navigation edits available **together** in the existing Replit deployment (not a new app). Requirements unchanged. Do not merge/directly deploy just to force source parity.

## Dry-run deploy (scanner disabled)
- Existing persistent `DATABASE_URL` stays exactly the same. Startup creates **only new** `hks_b2_*` tables; no alterations to existing `hks_wallet`, `hks_position`, `hks_closed_trade`, `hks_coin` tables.
- Set deployment environment `HKS_BOT2_PAPER_ENABLED=0` (default). Boot the upgraded version using the **existing** Gunicorn start command and persistence settings.
- Confirm `/` still serves Bot 1 and its wallet/trades/controls untouched.
- Confirm `/bot2` displays **1 dashboard for both TNKUSDT and CYSUSDT**. `/api/bot2/state` should show enabled=false, 2 independent coins, $1000 separate paper wallet.
- Confirm `/api/bot2/cron` refuses requests lacking `X-Cron-Key`. Existing `/wake`, `/api/cron`, `/api/state`, owner login, reset and manual close remain Bot 1-owned.

## Paper-only activation
- In **Replit deployment environment** set `HKS_BOT2_PAPER_ENABLED=1`, redeploy.
- Default paper `HKS_BOT2_NOTIONAL_USDT=50` per entry; `HKS_BOT2_FEE_RATE=0.001` per side; `HKS_BOT2_EXIT_SLIPPAGE=0.003` on modeled OHLC stop exits. These are conservative *assumptions*, not fee claims. Entry uses current public MEXC ask-depth weighted pricing. The order is **paper-only; no real MEXC order endpoints or keys**.
- Create a **separate** every-minute external HTTP scheduler, without changing Bot 1's `/wake` job:
  - URL: `https://<your-actual-deployed-host>/api/bot2/cron`
  - Method: `GET`
  - Header: `X-Cron-Key: <existing strong private HKS_CRON_TOKEN>`
  - Cron-job.org supports arbitrary custom headers and 1min free scheduling. Never embed the secret in the URL.
- Verify 2 successive successful `/api/bot2/state` scanner timestamps with the browser closed. Missing 1m continuity or stale MEXC quotes fail closed for the impacted coin.
- Owner login cookie shared with Bot 1. Bot 2 manual-paper-close uses MEXC public bid depth; no account orders.

## Strategy & operational caveats
- Original 15m SMC/ATR `evaluate_smc`, Score>=85, LONG only, 2 coins. INITIAL SL = 2 * original ATR stop distance (1.6–6% relative to entry before execution uncertainty). Trailing reference stays **2 * original ATR distance**, not 2x widened stop. The original trailing algorithm and its 1m next-bar timing are imported, not rewritten. No new TP or partial profit rules.
- Each coin stores real MEXC 1m candles forward in `hks_b2_1m_bar`. No old candles are invented; archive grows over time and must be monitored against database free-tier capacity.
- Scanner uses a distinct PostgreSQL advisory lock and 40s debounce. A successful scanner response means it processed a completed-bar pass, **not** a promise of continuous market access. Monitor cron response duration/failures and database capacity.
- Browser-launched background Bot 2 scanning is only best-effort on Replit Autoscale; **reliable unattended operation requires separate scheduler and successful repeated scans**.
- The model treats OHLC stop events as paper fills minus configured slippage, not actual order-book historical execution. A large unfavorable gap can be worse than the stop. The historical 29d TNK 4-trade result is preliminary, and CYS older 5m-only results are not 1m proof.
- When HKS_BOT2_PAPER_ENABLED=0, no paper entries will open, but existing Bot 2 positions should not be treated as safely closed; use owner-authorized manual paper close first if needed. This is not an exchange real-money safety switch.

## Rollback
- Revert the deployed Python/template code to the exact prior verified Replit revision. Keep b2 tables and the original Bot 1 database unchanged. Disable new external Bot 2 cron while rolling back; do not delete persistent Bot 1 tables or reset wallets.

**Deployment has not been performed until the Replit runtime was inspected and a real HTTP smoke test on the deployed app passed.**
