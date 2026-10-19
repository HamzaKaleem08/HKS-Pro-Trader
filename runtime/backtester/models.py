from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Candle:
    symbol: str
    open_ms: int
    interval_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def end_ms(self):
        """Exclusive completion boundary, not a fabricated tick timestamp."""
        return self.open_ms + self.interval_ms


@dataclass(frozen=True)
class Signal:
    symbol: str
    timestamp_ms: int
    side: str  # LONG, SHORT, or NO_SIGNAL
    reason: str
    stop_fraction: Decimal
    target_fraction: Decimal | None = None


class SignalStrategy(Protocol):
    warmup_bars: int
    version_id: str
    content_hash: str

    def evaluate(self, history: Sequence[Candle]) -> Signal: ...


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    exchange: str
    market: str
    interval: str
    synthetic: bool
    source: str
    retrieved_at: str | None
    candles: dict[str, tuple[Candle, ...]]
    input_hashes: dict[str, str]
    content_hash: str
    warnings: tuple[str, ...] = ()


@dataclass
class Position:
    trade_id: str
    account: str
    symbol: str
    side: str
    signal_ms: int
    entry_ms: int
    entry_raw: Decimal
    entry_price: Decimal
    quantity: Decimal
    notional: Decimal
    margin: Decimal
    risk_budget: Decimal
    planned_risk: Decimal
    initial_stop: Decimal
    stop: Decimal
    target: Decimal | None
    entry_fee: Decimal
    strategy_version: str
    entry_reason: str
    mfe: Decimal = Decimal(0)
    mae: Decimal = Decimal(0)
    entry_slippage: Decimal = Decimal(0)
    state: str = "OPEN"
