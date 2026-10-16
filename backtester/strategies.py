"""Structured, non-executable strategy definitions. No legacy equivalence claim."""
from dataclasses import dataclass
from decimal import Decimal

from .common import decimal, digest, integer
from .errors import ValidationError
from .models import Signal


def validate_definition(raw):
    allowed = {"schema_version", "kind", "name", "fast", "slow", "stop_fraction", "target_fraction", "direction"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValidationError("unknown strategy fields; executable code is not accepted")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1 or raw.get("kind") != "DEMO_SMA_CROSS":
        raise ValidationError("only explicitly illustrative DEMO_SMA_CROSS schema 1 is supported; Normal/Reverse parity NOT VERIFIED")
    name = raw.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise ValidationError("strategy name required (1–80 printable characters)")
    fast = integer(raw.get("fast"), "fast", 2, 100)
    slow = integer(raw.get("slow"), "slow", fast + 1, 500)
    stop = decimal(raw.get("stop_fraction"), "stop_fraction", ".0001", ".5")
    target = raw.get("target_fraction")
    target = None if target is None else decimal(target, "target_fraction", ".0001", "2")
    if raw.get("direction") not in ("LONG_ONLY", "BOTH"):
        raise ValidationError("direction must be LONG_ONLY or BOTH")
    if raw["direction"] == "BOTH" and target is not None and target >= 1:
        raise ValidationError("SHORT reference target must remain a positive price (fraction below 1)")
    return {"schema_version": 1, "kind": "DEMO_SMA_CROSS", "name": name, "fast": fast, "slow": slow,
            "stop_fraction": str(stop), "target_fraction": None if target is None else str(target),
            "direction": raw["direction"]}


@dataclass(frozen=True)
class DemoSMA:
    fast: int
    slow: int
    stop: Decimal
    target: Decimal | None
    direction: str
    content_hash: str

    @property
    def warmup_bars(self):
        return self.slow + 1

    @property
    def version_id(self):
        return "DEMO_SMA_CROSS_" + self.content_hash

    def evaluate(self, history):
        bar = history[-1]
        if len(history) < self.warmup_bars:
            return Signal(bar.symbol, bar.end_ms, "NO_SIGNAL", "WARMUP", self.stop, self.target)
        values = [c.close for c in history]
        previous_fast = sum(values[-self.fast - 1:-1]) / self.fast
        previous_slow = sum(values[-self.slow - 1:-1]) / self.slow
        current_fast = sum(values[-self.fast:]) / self.fast
        current_slow = sum(values[-self.slow:]) / self.slow
        side = "NO_SIGNAL"
        if previous_fast <= previous_slow and current_fast > current_slow:
            side = "LONG"
        elif previous_fast >= previous_slow and current_fast < current_slow and self.direction == "BOTH":
            side = "SHORT"
        return Signal(bar.symbol, bar.end_ms, side, "ILLUSTRATIVE_SMA_CROSS" if side != "NO_SIGNAL" else "NO_CROSS", self.stop, self.target)


def build_strategy(definition):
    d = validate_definition(definition)
    return DemoSMA(d["fast"], d["slow"], Decimal(d["stop_fraction"]),
                   None if d["target_fraction"] is None else Decimal(d["target_fraction"]),
                   d["direction"], digest(d))


DEMO_DEFINITION = {"schema_version": 1, "kind": "DEMO_SMA_CROSS", "name": "Illustrative SMA cross — NOT HKS Normal/Reverse",
                   "fast": 5, "slow": 20, "stop_fraction": "0.02", "target_fraction": "0.04", "direction": "LONG_ONLY"}
