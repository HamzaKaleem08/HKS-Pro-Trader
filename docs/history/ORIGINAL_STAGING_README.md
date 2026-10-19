# HKS Pro Trader — static premium browser staging

This is the separate, public Backtester staging build. The preserved V4 Python
candidate and completed browser feasibility proof are unchanged. No private HKS
Trading Terminal, ABG, Volume Sniper, wallet, account credential or production
service is part of this site.

## Run locally

Python 3.12 (standard library only) serves static files; it never executes user
strategies. Start `python serve.py --port 8097`, then open the localhost address
on that same computer. Ordinary file:// opening cannot provide required headers.

`python tools/build_static.py` regenerates metadata from the isolated staging
sources only. `python -m unittest discover -s tests -v` runs unit/integrity tests.
Browser QA additionally needs installed Playwright and sandboxed Chromium; see
`tools/verify_staging.py`. No --no-sandbox fallback is used.

## Use

1. Choose genuine Binance USD-M November 2025 history or an explicitly labeled
   verification fixture. The example is an illustrative public SMA/ATR strategy,
   **not** an authentic private HKS Normal/Reverse strategy.
2. Paste supported Python defining on_bar(ctx). Use the original V4 strategy API
   described in the editor. Save creates an immutable local version; it does not
   activate any trading. Only the last successfully tested source/settings are
   restored on reload; a later untested draft cannot replace them.
3. Select available symbols, explicit UTC dates and Individual or Shared mode.
   A valid 3-day preset is supported; custom ranges are checked exactly. Longer
   presets remain disabled until their data and streaming execution are verified.
4. Acknowledge diagnostic Futures assumptions and that the Python is trusted.
   Press Run. All calculations happen on this device in browser workers.
5. Inspect real results, partial-exit segments, position-level win rate, details,
   reconciliation, chart and complete CSV exports. Fees/slippage are explicit.
   Futures funding, liquidation and historical instrument filters are not modeled.
6. Cache downloads once. OPFS with IndexedDB metadata is preferred; IndexedDB is
   the fallback. Request persistent storage, but do not treat browser storage as
   an external backup. Each device/profile/origin has its own data, not an account
   or cloud-synchronized wallet.
7. Keep the tab visible. Interrupted jobs with a verified checkpoint can Resume
   from Saved tests. Source/config/data must match exactly; completed reports
   remain readable after an application update, but old checkpoints must not be
   resumed with different engine/strategy code.

## Honest release limits

- 1–20 symbols; 200,000 total input candles including warm-up.
- 16MiB CSV/file, 32MiB CSV/input, 10,000 entries. No silent truncation.
- Computation yields at completed global chronological boundaries. Default
  checkpoint spacing is 120 timestamps. The original 30-second computation
  budget applies to a chunk; each Python decision has a 3-second deadline;
  a foreground session is limited to one hour.
- Financial checkpoints: typed JSON, 64MiB expanded / 16MiB compressed. Latest
  two complete checkpoint files are retained. Strategy recovery state: 1MiB.
- Recovery supports deterministic ctx.state and serializable global data. It is
  not a Python process/OS snapshot. Clocks/randomness, JS/OS external state,
  mutable closures/function attributes/defaults, mutated modules and custom
  class/native-handle state are unsupported; several are explicitly rejected.
  Reflection and side effects outside the documented contract are not resumable.
- Browser code is TRUSTED-CODE ONLY. Opaque origin/network isolation is retained,
  but a hostile strategy can consume device RAM. There is no hard per-worker
  memory cap or OS-container-equivalent security promise.
- 20 genuine November source series (864,000 candles) are bundled for reuse.
  **20 coins ×4 years is not implemented, benchmarked or enabled.** Larger
  periods require additional verified history plus a bounded long-history kernel;
  the current limits deliberately reject them.
- No server worker, account authentication/sync, live market service, trading
  activation, real/demo orders, or production PostgreSQL is present/required.
- Physical Android and public Cloudflare hosting require separate actual checks.
  Emulation and the local Cloudflare runtime are not hosted/physical proof.
- Offline asset/candle/report storage is provided. Fresh opaque-frame startup
  fully offline can depend on browser cache behavior; do not assume all browsers
  can initialize a new Python run without the site being reachable.

See DEPLOYMENT.md, IMPLEMENTATION_REPORT.md, SECURITY_REVIEW.md and TEST_RESULTS.md.
