# Accepted historical files

UI: select the actual Binance Spot or USD-M Futures market, uppercase USDT symbol,
and interval `1m`, `5m`, `15m`, or `1h`. Upload ONE CSV or ONE ZIP containing a
single plain CSV. Attach the matching official `.CHECKSUM` when available.
No arbitrary filesystem path or source URL is accepted by the API.

Normalized UTF-8 CSV has exactly this header/order:

```csv
open_time,open,high,low,close,volume
```

`open_time` is UTC milliseconds or explicit UTC ISO8601. All OHLC/volume fields
are finite decimal strings; prices positive, volume nonnegative, OHLC consistent.
No missing/duplicate/out-of-order interval inside one submitted segment. Separate
valid segments can be stored with a visible gap that must be filled before a run.
Only completed candles are accepted; a future/current incomplete candle fails.

Native Binance12-column archives are also accepted (with the normal first6fields,
close time and native volume/count fields). Official Spot microsecond open/close
timestamps are normalized explicitly; raw source bytes keep their SHA-256 receipt.
A native Binance archive member's symbol/timeframe must match the declared source.
ZIP paths, multiple members and excessive expansion fail. No executable files.

UI import source metadata corresponds to:

```json
{
  "exchange": "BINANCE",
  "market": "USDT_LINEAR_PERPETUAL",
  "symbol": "BTCUSDT",
  "interval": "15m",
  "synthetic": false,
  "source": "Owner-supplied official monthly ZIP; original download timestamp unknown",
  "retrieved_at": null
}
```

Synthetic fixtures require `exchange:"SYNTHETIC",synthetic:true` and remain
visibly labeled. Original retrieval timestamps stay null if unknown, never
reconstructed from an intake timestamp. Intake times/hash/coverage/checksum status
are recorded separately. A source declaration and matching sidecar certify the
provided bytes, not independently the whole exchange's historical listing rules.

Owner-local CLI (requires the same securely configured DB environment):

```sh
python tools/manage_data.py import BTCUSDT-15m-2026-09.zip \
  --metadata examples/source_metadata.json \
  --checksum BTCUSDT-15m-2026-09.zip.CHECKSUM
python tools/manage_data.py inventory
python tools/manage_data.py plan --metadata examples/source_metadata.json \
  --start 2026-09-01T00:00:00Z --end 2026-10-01T00:00:00Z
```

Do not substitute a futures file for Spot. Preserve delisting/eligibility evidence
and original files yourself; normalized CSVs alone cannot prove those facts.
Current fees/filters are not certified historical execution evidence. Futures
price replay requires explicit diagnostic acknowledgement in Backtester.
