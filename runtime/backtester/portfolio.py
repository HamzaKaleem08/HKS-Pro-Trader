"""Fully collateralized spot / diagnostic 1x linear-PnL accounting."""
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .common import digest
from .models import Position

ZERO = Decimal(0)
ONE = Decimal(1)
TENK = Decimal(10000)


@dataclass
class Account:
    name: str
    initial: Decimal
    market: str
    cash: Decimal
    positions: dict = field(default_factory=dict)
    closed: list = field(default_factory=list)
    marks: dict = field(default_factory=dict)
    peak_equity: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    max_drawdown_fraction: Decimal = ZERO

    def equity(self):
        if self.market == "SPOT":
            return self.cash + sum((p.quantity * self.marks[p.symbol] for p in self.positions.values()), ZERO)
        return self.cash + sum((p.margin + self.unrealized(p) for p in self.positions.values()), ZERO)

    def unrealized(self, p):
        return (self.marks[p.symbol] - p.entry_price) * p.quantity * (1 if p.side == "LONG" else -1)

    def reserved(self):
        return sum((p.margin for p in self.positions.values()), ZERO)

    def reserved_risk(self):
        return sum((p.planned_risk for p in self.positions.values()), ZERO)

    def observe_equity(self, ts):
        eq = self.equity()
        self.peak_equity = max(self.peak_equity, eq)
        dd = self.peak_equity - eq
        self.max_drawdown = max(self.max_drawdown, dd)
        if self.peak_equity > 0:
            self.max_drawdown_fraction = max(self.max_drawdown_fraction, dd / self.peak_equity)
        return {"timestamp_ms": ts, "account": self.name, "cash": self.cash,
                "reserved_capital": self.reserved(), "reserved_risk": self.reserved_risk(),
                "unrealized_pnl": sum((self.unrealized(p) for p in self.positions.values()), ZERO),
                "equity": eq, "drawdown": dd}

    def enter(self, signal, bar, config, strategy_version):
        if signal.symbol in self.positions:
            return None, "POSITION_ALREADY_OPEN"
        if len(self.positions) >= config.max_positions:
            return None, "MAX_CONCURRENT_POSITIONS"
        if self.market == "SPOT" and signal.side == "SHORT":
            return None, "SPOT_SHORT_UNSUPPORTED"
        eq = self.equity()
        if eq <= 0:
            return None, "NONPOSITIVE_EQUITY"
        sign = 1 if signal.side == "LONG" else -1
        price = bar.open * (ONE + sign * config.slippage_bps / TENK)
        budget = eq * config.risk_fraction
        distance = price * signal.stop_fraction
        stop_rule=getattr(signal,'stop_rule',None)
        target_rule=getattr(signal,'target_rule',None)
        if stop_rule:
            kind,value=stop_rule
            distance=price*value if kind=='fraction' else (value if kind=='distance' else sign*(price-value))
            if not price*Decimal('.0001')<=distance<=price*Decimal('.5'):
                return None,'PYTHON_STOP_INVALID_AT_ACTUAL_FILL'
        desired = budget / distance if config.sizing == "risk" else config.fixed_notional / price
        # Fixed precision is a simulator lot convention, NOT an exchange filter.
        quantity = min(desired, eq * config.allocation_fraction / price)
        quantity = (quantity // Decimal("0.00000001")) * Decimal("0.00000001")
        if quantity <= 0:
            return None, "SIZE_ROUNDS_TO_ZERO"
        notional = quantity * price
        fee = notional * config.fee_bps / TENK
        planned = distance * quantity
        if planned > budget + Decimal("1e-25"):
            return None, "PER_TRADE_RISK_LIMIT"
        if self.reserved_risk() + planned > eq * config.max_total_risk_fraction:
            return None, "AGGREGATE_RISK_LIMIT"
        if notional + fee > self.cash:
            return None, "INSUFFICIENT_AVAILABLE_FUNDS"
        stop = price - sign * distance
        target = None if signal.target_fraction is None else price * (ONE + sign * signal.target_fraction)
        if target_rule:
            kind,value=target_rule
            target=price*(ONE+sign*value) if kind=='fraction' else (price+sign*value if kind=='distance' else value)
            if target<=0 or sign*(target-price)<=0:return None,'PYTHON_TARGET_INVALID_AT_ACTUAL_FILL'
        trade_id = digest([self.name, signal.symbol, signal.timestamp_ms, signal.side, strategy_version])
        p = Position(trade_id, self.name, signal.symbol, signal.side, signal.timestamp_ms,
                     bar.open_ms, bar.open, price, quantity, notional, notional, budget, planned,
                     stop, stop, target, fee, strategy_version, signal.reason,
                     entry_slippage=abs(price - bar.open) * quantity)
        self.cash -= notional + fee
        self.positions[p.symbol] = p
        return p, "ACCEPTED"

    def close(self, p, raw_price, ts, config, reason, fill_window, ambiguity=False):
        sign = 1 if p.side == "LONG" else -1
        price = raw_price * (ONE - sign * config.slippage_bps / TENK)
        gross = sign * (price - p.entry_price) * p.quantity
        exit_fee = price * p.quantity * config.fee_bps / TENK
        self.cash += (price * p.quantity if self.market == "SPOT" else p.margin + gross) - exit_fee
        row = asdict(p)
        row.update({"state": "CLOSED", "exit_ms": ts, "exit_raw": raw_price, "exit_price": price,
                    "exit_reason": reason, "gross_pnl": gross, "entry_fee": p.entry_fee,
                    "exit_fee": exit_fee, "fees": p.entry_fee + exit_fee,
                    "net_pnl": gross - p.entry_fee - exit_fee,
                    "slippage_cost": p.entry_slippage + abs(raw_price - price) * p.quantity,
                    "gross_before_slippage": sign * (raw_price - p.entry_raw) * p.quantity,
                    "mfe_pct": p.mfe / p.entry_price * 100,
                    "mae_pct": p.mae / p.entry_price * 100,
                    "holding_ms": ts - p.entry_ms,
                    "fill_window_start_ms": fill_window[0], "fill_window_end_ms": fill_window[1],
                    "timestamp_precision": ("CANDLE_CLOSE_PROXY" if reason == "END_OF_TEST_EXPLICIT" else
                                            ("MODEL_BAR_OPEN" if fill_window[0] == fill_window[1] else "CANDLE_INTERVAL_ONLY")),
                    "excursion_precision": "CONSERVATIVE_BOUND_ON_EXIT_CANDLE",
                    "ambiguous_stop_target": ambiguity,
                    "funding": None if self.market != "SPOT" else ZERO})
        if hasattr(self,'finalize_trade'):row=self.finalize_trade(p,row)
        self.closed.append(row)
        del self.positions[p.symbol]
        return row

    def reconcile(self):
        """Independent reconstruction from immutable entries/closed records."""
        closed_net = self.closed.net_total if hasattr(self.closed,'net_total') else sum((t["net_pnl"] for t in self.closed), ZERO)
        open_fees = sum((p.entry_fee for p in self.positions.values()), ZERO)
        expected_cash = self.initial + closed_net - self.reserved() - open_fees
        expected_equity = self.initial + closed_net - open_fees + sum((self.unrealized(p) for p in self.positions.values()), ZERO)
        return {"expected_cash": expected_cash, "actual_cash": self.cash,
                "cash_residual": self.cash - expected_cash,
                "expected_equity": expected_equity, "actual_equity": self.equity(),
                "equity_residual": self.equity() - expected_equity}
