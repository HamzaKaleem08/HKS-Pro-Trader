# Source-backup test inputs

All original Python/JavaScript regression sources are preserved without changes.
The five Python test-module commands in the root README use synthetic input and
the included pinned kernel. The two JavaScript files use Node's built-in runner.

`test_preserved.ProbeTests.test_fixture_compressed_checksums_and_csv_checksums`
and `test_all_monthly_cache_candles_independently_validate` need the 26 market
files listed in `HISTORICAL_DATA_EXCLUSIONS.json`. They are intentionally absent
from Git. Restore them from separately preserved, checksum-matching data before
requesting a full historical-input test pass. Do not weaken those assertions.

The `NATIVE_CONTAINER_BASELINES.json` file contains expected modeled results for
synthetic/disposable $1,000 accounts, including tests using public market input.
These are regression oracles, not real owner account or wallet exports. All
input candles are separately excluded. Its result hashes preserve financial
parity with the original kernel.

The optional original-archive test checks 128 files at `HKS_V4_SOURCE_ROOT` (or
its original workspace default) and explicitly skips when that separate legacy
archive is missing. It is not needed to verify the 19 included current browser
modules. Some historical packaging/upgrade tools reference earlier public
source snapshots in their original workspace locations; those tools are kept
for audit provenance and are not the current build entry point.

Portable commands are `python tools/verify_source_backup.py`, `python serve.py`,
the root README's synthetic tests, and the build tool `tools/build_static.py`.
Real Chromium tests require an installed, normally sandboxed Chromium and
Playwright. Several historical verification drivers target Linux Chromium at
`/usr/bin/chromium`; physical Windows/Android execution is not claimed by those
drivers. `tools/verify_source_browser.py` accepts the Chromium executable path.
The published UI's fresh-profile initialization reads the excluded
`genuine_2coin_1day` fixture. The source smoke driver accepts `--data-root` pointing
to separately preserved data, verifies that fixture's recorded hash, and restores
it only into disposable test storage. The executed replay remains explicitly
synthetic. Without that fixture, the exact unmodified published UI cannot finish
fresh-profile startup; this source-only backup does not hide that dependency.

Regenerating the build can update `evidence/STATIC_BUILD.json` file/byte totals
because market caches were deliberately excluded. The published source snapshot
and its checksums should be preserved; perform rebuild experiments in a copy.
