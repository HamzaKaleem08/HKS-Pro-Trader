from dataclasses import dataclass
from decimal import Decimal

from .common import decimal, digest, integer, timestamp
from .errors import ValidationError


@dataclass(frozen=True)
class RunConfig:
    start_ms: int
    end_ms: int
    mode: str = "individual"
    initial_capital: Decimal = Decimal("1000")
    sizing: str = "risk"
    risk_fraction: Decimal = Decimal("0.01")
    allocation_fraction: Decimal = Decimal("0.25")
    fixed_notional: Decimal = Decimal("100")
    max_total_risk_fraction: Decimal = Decimal("0.05")
    max_positions: int = 3
    fee_bps: Decimal = Decimal("10")
    slippage_bps: Decimal = Decimal("2")
    end_policy: str = "KEEP_OPEN"
    allow_uncertified_futures: bool = False

    def __post_init__(self):
        for name in ("start_ms", "end_ms"):
            object.__setattr__(self, name, timestamp(getattr(self, name)))
        if self.end_ms <= self.start_ms:
            raise ValidationError("end must be after start; requested intervals are never shortened")
        if self.mode not in ("individual", "shared"):
            raise ValidationError("mode must be individual or shared")
        if self.sizing not in ("risk", "fixed_notional"):
            raise ValidationError("unsupported sizing mode")
        if self.end_policy not in ("KEEP_OPEN", "CLOSE_AT_LAST_CLOSE"):
            raise ValidationError("invalid end policy")
        if type(self.allow_uncertified_futures) is not bool:
            raise ValidationError("allow_uncertified_futures must be an explicit boolean")
        bounds = {"initial_capital": ("1", "1000000000"), "risk_fraction": (".0001", ".1"),
                  "allocation_fraction": (".0001", "1"), "fixed_notional": (".01", "1000000000"),
                  "max_total_risk_fraction": (".0001", "1"), "fee_bps": ("0", "100"), "slippage_bps": ("0", "100")}
        for name, (lo, hi) in bounds.items():
            object.__setattr__(self, name, decimal(getattr(self, name), name, lo, hi))
        integer(self.max_positions, "max_positions", 1, 20)

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) - cls.__dataclass_fields__.keys():
            raise ValidationError("unknown run configuration fields")
        if "start_ms" not in raw or "end_ms" not in raw:
            raise ValidationError("start_ms and end_ms UTC boundaries required")
        return cls(**raw)

    @property
    def content_hash(self):
        return digest(self)
