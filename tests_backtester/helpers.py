from decimal import Decimal as D
from pathlib import Path
import csv
import hashlib
import json

from backtester.common import digest, timestamp
from backtester.models import Candle, Dataset, Signal

T = timestamp("2025-11-01T00:00:00Z")
M = 60_000


def candles(sym="BTCUSDT", prices=None):
    prices = prices or [(100, 101, 99, 100)] * 6
    return tuple(Candle(sym, T+i*M, M, *(D(str(x)) for x in values[:4]), D(str(values[4] if len(values)>4 else 100)))
                 for i, values in enumerate(prices))


def dataset(mapping=None, market="SPOT"):
    mapping = mapping or {"BTCUSDT": candles()}
    return Dataset("fixture", "SYNTHETIC", market, "1m", True, "DETERMINISTIC TEST FIXTURE",
                   "2025-12-01T00:00:00Z", mapping, {}, digest(mapping), ())


class Scripted:
    """Synthetic test decisions only, never selectable by web users."""
    warmup_bars = 1
    version_id = "SYNTHETIC_SIGNAL_FIXTURE_V1"
    content_hash = "test-fixture-only"

    def __init__(self, signals=None, stop="0.1", target=None):
        self.signals = signals if signals is not None else {("BTCUSDT", T+M): "LONG"}
        self.stop = D(stop)
        self.target = None if target is None else D(target)

    def evaluate(self, history):
        bar = history[-1]
        return Signal(bar.symbol, bar.end_ms, self.signals.get((bar.symbol, bar.end_ms), "NO_SIGNAL"),
                      "SYNTHETIC SCRIPTED SIGNAL", self.stop, self.target)


def write_bundle(root, mapping=None, market="SPOT"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    mapping = mapping or {"BTCUSDT": candles()}
    files = []
    for sym, rows in mapping.items():
        name = sym + ".csv"
        p = root / name
        with p.open("w",newline="") as f:
            w = csv.writer(f)
            w.writerow(["open_time","open","high","low","close","volume"])
            for c in rows: w.writerow([c.open_ms,c.open,c.high,c.low,c.close,c.volume])
        files.append({"symbol":sym,"file":name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest = {"schema_version":1,"dataset_id":"fixture", "exchange":"SYNTHETIC", "market":market,
                "interval":"1m", "synthetic":True,"source":"synthetic fixture, not exchange history",
                "retrieved_at":"2025-12-01T00:00:00Z","files":files}
    (root/"manifest.json").write_text(json.dumps(manifest))
    return manifest
