# Pinned dependencies and source layout

- Application/static server and host unit tests: Python 3.12 standard library.
- Browser Python: vendored Pyodide 0.27.7, Python 3.12.7, including the exact JS,
  Wasm and standard-library distribution used by the published site. Upstream
  source/integrity and per-file hashes are in `evidence/PYODIDE_RUNTIME_RECEIPT.json`.
  Upstream package metadata/README and lockfile are preserved under
  `web/vendor/pyodide/`; preserve their license notices.
- JavaScript unit tests: Node.js 22+ built-in runner. Verified environment used
  Node 24.19.0; no npm install is needed for the app or these unit tests.
- Optional real-browser QA: Playwright 1.62.0, greenlet 3.5.5, pyee 13.0.1 and a
  normally sandboxed Chromium. These are test dependencies, not browser/server
  runtime services. No package installation is performed by backup verification.
- Optional later publishing CLI: Wrangler 4.151.1 was used for the existing site.
  It is not required to run the app locally and is not invoked by this backup.

The readable `runtime/` tree mirrors all 19 sources in `web/kernel.json` exactly.
The browser loads that pinned bundle; core financial sources must not be silently
changed or replaced. `tools/build_static.py` preserves the established build
process. It updates adapters/context sources and metadata, not trading formulas.

No server database, Flask/Gunicorn service, paid worker, or exchange SDK is part
of this static browser application. Historical prices are separately required
for genuine-market runs, exactly as listed in `HISTORICAL_DATA_EXCLUSIONS.json`.
