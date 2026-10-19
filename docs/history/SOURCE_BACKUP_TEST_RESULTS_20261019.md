# Source-backup verification — 19 October 2026 UTC

This task preserves source. It does not republish the site, change financial
calculations, acquire market data or rerun research.

## Executed during this backup

| Check | Actual result |
| --- | --- |
| Independent current HTTPS asset retrieval | 39 included served assets match source SHA-256 and size exactly |
| Pages headers | Published app, sandbox and financial-worker policies verified |
| Python regression suite | 56 passed, 0 failed, 0 skipped |
| JavaScript Context/delivery tests | 7 passed, 0 failed, 0 skipped |
| JavaScript diagnostic-consent tests | 9 passed, 0 failed, 0 skipped |
| Actual sandboxed Chromium synthetic replay | Passed: complete result equals the independent pinned oracle |
| Synthetic partial-position accounting | 2 closed exit segments; ending equity $1,017.50 |
| Browser journal, CSV, detail dialog and reload | Passed |
| Exact OLD SMC source loaded in real browser Pyodide | Context /2, completed 15m/1H access, opaque origin confirmed |
| 412 × 915 responsive viewport | No horizontal overflow; not a physical Android test |
| Source and embedded-archive secret scan | No unresolved findings; one pinned public standard-library documentation example reviewed |

Logs and machine-readable receipts are under `evidence/`. The full Python suite
ran in a disposable copy with all 26 excluded historical inputs restored and
checksum checked. These data files were never added to the source backup. The
optional original 128-file archive check used its separately preserved original.

The source-only browser test initially reproduced a fresh-profile bootstrap
failure because the exact published UI loads the excluded
`web/fixtures/genuine_2coin_1day.json.gz`. No application change was made. The
successful repeat supplied this checksum-matching fixture only in disposable
test storage; the actual executed replay was synthetic. This dependency must be
restored to use the unchanged UI. Other genuine replays need their market data.

Synthetic replay result hash:
`12e0297e42ba38c8a3c8331d703dd9e108b42e3fe1387c36f60d2f4a1ffc8bb2`.

## Previously executed published-market evidence, preserved without rerunning

`evidence/PUBLISHED_TEST_SUMMARY.json` records the already verified exact OLD
SMC Reverse strategy on genuine BTC/ETH November 2025 three-day inputs, both
wallet modes, financial parity, CSV, restart/reload and zero candle redownloads.
These are diagnostic Futures price replays, not certified execution results.

- Shared result hash:
  `7160f0c0d79a98c5f412f1c2865ec854359a4af759d6e6d649ea753a86ea4199`.
- Individual result hash:
  `75654c2be87a71e05cfa3001777f2a9c66f8551a1fa4501eb0934bc5bd76b670`.
- Exact example SHA-256:
  `d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e`.

Physical Windows/Android device tests and fully offline Python recomputation
are not claimed. The source-only branch deliberately cannot reproduce genuine
market runs until its excluded, checksum-matching inputs are restored.

`tools/verify_source_backup.py` verifies the final source inventory, readable and
embedded runtime parity, original financial pins and exact example hash. The
post-push independent GitHub-clone receipt is recorded outside the snapshot so
the immutable commit does not need to include its own future commit hash.
