"""Bounded local CSV intake. File hashes prove bytes, not exchange authenticity."""
import csv
import hashlib
import json
from pathlib import Path
import time

from .common import INTERVALS, decimal, digest, identifier, symbol, timestamp
from .errors import ResourceLimit, ValidationError
from .models import Candle, Dataset

MAX_ROWS = 200_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SYMBOLS = 20
FIELDS = ("open_time", "open", "high", "low", "close", "volume")


def confined(root, filename):
    if not isinstance(filename, str) or Path(filename).name != filename or len(filename) > 100:
        raise ValidationError("dataset files must be simple filenames")
    root = Path(root).resolve()
    path = root / filename
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise ValidationError("dataset file is unavailable or unsafe")
    return path


def read_candles(path, sym, interval, *, as_of_ms=None, row_limit=MAX_ROWS):
    try:
        return _read_candles(path,sym,interval,as_of_ms=as_of_ms,row_limit=row_limit)
    except (csv.Error, UnicodeError):
        raise ValidationError("invalid CSV encoding or oversized/malformed field") from None


def _read_candles(path, sym, interval, *, as_of_ms=None, row_limit=MAX_ROWS):
    sym = symbol(sym)
    if interval not in INTERVALS:
        raise ValidationError("unsupported candle interval; use 1m, 5m, 15m or 1h")
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ResourceLimit("CSV exceeds the 16 MiB file bound")
    interval_ms = INTERVALS[interval]
    as_of_ms = int(time.time() * 1000) if as_of_ms is None else as_of_ms
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValidationError("CSV header must be: " + ",".join(FIELDS))
        for line, row in enumerate(reader, 2):
            if len(rows) >= row_limit:
                raise ResourceLimit("dataset exceeds the 200,000 candle bound")
            if None in row or any(v is None for v in row.values()):
                raise ValidationError(f"{sym} CSV row {line}: wrong column count")
            raw_time = row["open_time"]
            ts = timestamp(int(raw_time) if raw_time.isascii() and raw_time.isdigit() else raw_time)
            if ts % interval_ms:
                raise ValidationError(f"{sym} row {line}: UTC interval misalignment")
            if ts + interval_ms > as_of_ms:
                raise ValidationError(f"{sym} row {line}: incomplete/future candle")
            if rows and ts != rows[-1].end_ms:
                kind = "duplicate/out-of-order" if ts <= rows[-1].open_ms else "gap"
                raise ValidationError(f"{sym} row {line}: {kind}; missing candles are never filled")
            o, h, lo, c = (decimal(row[k], k, "0.000000000001") for k in FIELDS[1:5])
            v = decimal(row["volume"], "volume", 0)
            if h < max(o, c) or lo > min(o, c) or h < lo:
                raise ValidationError(f"{sym} row {line}: inconsistent OHLC")
            rows.append(Candle(sym, ts, interval_ms, o, h, lo, c, v))
    if not rows:
        raise ValidationError(f"{sym}: empty dataset")
    return tuple(rows)


def load_dataset(root, *, as_of_ms=None):
    root = Path(root)
    manifest_path = confined(root, "manifest.json")
    if manifest_path.stat().st_size > 64 * 1024:
        raise ResourceLimit("manifest exceeds 64 KiB")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (ValueError, UnicodeError):
        raise ValidationError("invalid dataset manifest JSON") from None
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1:
        raise ValidationError("dataset manifest schema_version must be 1")
    dataset_id = identifier(manifest.get("dataset_id"))
    market = manifest.get("market")
    interval = manifest.get("interval")
    if market not in ("SPOT", "USDT_LINEAR_PERPETUAL") or interval not in INTERVALS:
        raise ValidationError("explicit supported market and interval required")
    if type(manifest.get("synthetic")) is not bool:
        raise ValidationError("synthetic must be an explicit boolean")
    for name in ("exchange", "source"):
        if not isinstance(manifest.get(name), str) or not 1 <= len(manifest[name]) <= 1000:
            raise ValidationError(f"dataset {name} required")
    if manifest.get("retrieved_at") is not None:
        timestamp(manifest["retrieved_at"])
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_SYMBOLS:
        raise ValidationError("manifest must contain 1–20 symbol CSVs")
    candles, hashes, count, size = {}, {}, 0, 0
    for item in files:
        if not isinstance(item, dict):
            raise ValidationError("invalid manifest file entry")
        sym = symbol(item.get("symbol"))
        if sym in candles:
            raise ValidationError("duplicate manifest symbol")
        path = confined(root, item.get("file"))
        size += path.stat().st_size
        if size > MAX_TOTAL_BYTES:
            raise ResourceLimit("dataset exceeds 32 MiB")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != item.get("sha256"):
            raise ValidationError(f"{sym}: input SHA-256 mismatch")
        values = read_candles(path, sym, interval, as_of_ms=as_of_ms, row_limit=MAX_ROWS - count)
        count += len(values)
        candles[sym], hashes[item["file"]] = values, sha
    hashes["manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    warnings = ["CSV source identity is declared by the supplier; local SHA-256 is not independent exchange provenance.",
                "Historical tick/lot/notional filters and order-book liquidity are not supplied or certified."]
    if manifest.get("retrieved_at") is None:
        warnings.append("Original network retrieval timestamp is unknown; no receipt timestamp was reconstructed.")
    if market == "USDT_LINEAR_PERPETUAL":
        warnings.append("DIAGNOSTIC linear-Futures price replay at 1x collateral only: funding, mark-price liquidation, maintenance margin and historical leverage tiers are NOT modeled.")
    return Dataset(dataset_id, manifest["exchange"], market, interval, manifest["synthetic"],
                   manifest["source"], manifest.get("retrieved_at"), candles, hashes,
                   digest({"hashes": hashes, "market": market, "interval": interval}), tuple(warnings))


def coverage(dataset):
    return [{"symbol": s, "candles": len(rows), "first_open_ms": rows[0].open_ms,
             "last_complete_ms": rows[-1].end_ms, "missing_intervals": 0,
             "duplicate_timestamps": 0, "interval": dataset.interval}
            for s, rows in sorted(dataset.candles.items())]
