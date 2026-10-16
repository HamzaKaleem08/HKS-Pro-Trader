"""Causal common-interval replay. No exchange calls and no executable user code."""
from collections import defaultdict, deque
from dataclasses import asdict
from decimal import Decimal, localcontext
from heapq import merge
from itertools import groupby
import time

from .common import INTERVALS, decimal, digest, primitives
from .data import coverage
from .errors import ResourceLimit, ValidationError
from .models import Signal
from .portfolio import Account, ZERO

MAX_TRADES = 10_000
MAX_SECONDS = 30


def _check_signal(signal, bar):
    if not isinstance(signal, Signal) or signal.symbol != bar.symbol or signal.timestamp_ms != bar.end_ms:
        raise ValidationError("strategy returned a signal with invalid symbol or completion timestamp")
    if signal.side not in ("LONG", "SHORT", "NO_SIGNAL") or not isinstance(signal.reason, str) or len(signal.reason) > 240:
        raise ValidationError("invalid signal side/reason")
    if not isinstance(signal.stop_fraction, Decimal) or (signal.target_fraction is not None and not isinstance(signal.target_fraction,Decimal)):
        raise ValidationError("signal stop/target distances must be Decimal values")
    decimal(signal.stop_fraction, "signal stop_fraction", ".0001", ".5")
    if signal.target_fraction is not None:
        decimal(signal.target_fraction, "signal target_fraction", ".0001", "2")
        if signal.side == "SHORT" and signal.target_fraction >= 1:
            raise ValidationError("SHORT target price must be positive")


def _stop_at_open(account, bar, config):
    p = account.positions.get(bar.symbol)
    if p is None or bar.volume <= 0:
        return None
    stop = bar.open <= p.stop if p.side == "LONG" else bar.open >= p.stop
    target = p.target is not None and (bar.open >= p.target if p.side == "LONG" else bar.open <= p.target)
    if stop:
        p.mae = max(p.mae, (p.entry_price - bar.open) if p.side == "LONG" else (bar.open - p.entry_price))
        return account.close(p, bar.open, bar.open_ms, config, "STOP_GAP", (bar.open_ms, bar.open_ms))
    if target:
        # No favorable opening-gap windfall; market-trigger model at target minus adverse slippage.
        return account.close(p, p.target, bar.open_ms, config, "TARGET_GAP_CONSERVATIVE", (bar.open_ms, bar.open_ms))
    return None


def _intrabar(account, bar, config):
    p = account.positions.get(bar.symbol)
    if p is None:
        return None
    is_long = p.side == "LONG"
    stop = bar.low <= p.stop if is_long else bar.high >= p.stop
    target = p.target is not None and (bar.high >= p.target if is_long else bar.low <= p.target)
    if bar.volume <= 0:
        return {"symbol": bar.symbol, "timestamp_ms": bar.end_ms, "reason": "STOP_OR_TARGET_UNFILLED_ZERO_VOLUME"} if stop or target else None
    if stop or target:
        # Unknown path through the candle: stop wins. Excursions bounded to prices
        # certainly reached through the chosen trigger, not later candle extrema.
        raw = p.stop if stop else p.target
        p.mfe = max(p.mfe, (raw - p.entry_price) if is_long else (p.entry_price - raw), ZERO)
        p.mae = max(p.mae, (p.entry_price - raw) if is_long else (raw - p.entry_price), ZERO)
        account.close(p, raw, bar.end_ms, config,
                      "STOP_AMBIGUOUS" if stop and target else ("INITIAL_STOP" if stop else "TARGET"),
                      (bar.open_ms, bar.end_ms), bool(stop and target))
        return None
    p.mfe = max(p.mfe, (bar.high - p.entry_price) if is_long else (p.entry_price - bar.low), ZERO)
    p.mae = max(p.mae, (p.entry_price - bar.low) if is_long else (bar.high - p.entry_price), ZERO)
    return None


def simulate(dataset, strategy, config, symbols=None):
    with localcontext() as context:
        context.prec = 34
        return _simulate(dataset, strategy, config, symbols)


def _simulate(dataset, strategy, config, symbols):
    started = time.monotonic()
    if dataset.market == "USDT_LINEAR_PERPETUAL" and not config.allow_uncertified_futures:
        raise ValidationError("Futures funding/filters/liquidation are unavailable; explicit allow_uncertified_futures=true required for DIAGNOSTIC price replay")
    selected = sorted(dataset.candles if symbols is None else symbols)
    if not selected or len(selected) != len(set(selected)) or set(selected) - dataset.candles.keys():
        raise ValidationError("select distinct available symbols")
    interval = INTERVALS[dataset.interval]
    if config.start_ms % interval or config.end_ms % interval:
        raise ValidationError("requested UTC boundaries must align with the candle interval")
    if not isinstance(strategy.warmup_bars, int) or not 1 <= strategy.warmup_bars <= 501:
        raise ValidationError("strategy warmup bound exceeded")
    warmup_start = config.start_ms - strategy.warmup_bars * interval
    for sym in selected:
        rows = dataset.candles[sym]
        if rows[0].open_ms > warmup_start or rows[-1].end_ms < config.end_ms:
            raise ValidationError(f"{sym}: requested period plus {strategy.warmup_bars} warm-up candles unavailable; no silent shortening")
    names = selected if config.mode == "individual" else ["SHARED"]
    accounts = {n: Account(n, config.initial_capital, dataset.market, config.initial_capital,
                           peak_equity=config.initial_capital) for n in names}
    histories = {s: deque(maxlen=strategy.warmup_bars) for s in selected}
    pending, seen, last_bars = {}, set(), {}
    journal, equity, warnings = [], [], list(dataset.warnings)
    counts = {s: {"evaluations": 0, "no_signal": 0, "qualified_signals": 0, "rejections": {}} for s in selected}
    position_count = 0

    def account_for(sym):
        return accounts[sym if config.mode == "individual" else "SHARED"]

    def decision(signal, outcome, reason, **extra):
        if outcome == "REJECTED":
            d = counts[signal.symbol]["rejections"]
            d[reason] = d.get(reason, 0) + 1
        journal.append({"signal_ms": signal.timestamp_ms, "symbol": signal.symbol,
                        "side": signal.side, "signal_reason": signal.reason,
                        "outcome": outcome, "reason": reason, **extra})

    streams = ((b for b in dataset.candles[s] if warmup_start <= b.open_ms < config.end_ms) for s in selected)
    events = merge(*streams, key=lambda b: (b.open_ms, b.symbol))
    for ts, values in groupby(events, key=lambda b: b.open_ms):
        if time.monotonic() - started > MAX_SECONDS:
            raise ResourceLimit("30-second replay wall budget exceeded; result discarded")
        bars = sorted(values, key=lambda b: b.symbol)
        # Every account sees only contemporaneously known opens during allocation.
        for b in bars:
            account_for(b.symbol).marks[b.symbol] = b.open
        for b in bars:
            _stop_at_open(account_for(b.symbol), b, config)
        if ts >= config.start_ms:
            equity.extend(a.observe_equity(ts) for a in accounts.values())
        attempted = []
        for b in bars:
            a = account_for(b.symbol)
            signal = pending.pop(b.symbol, None)
            if signal is not None:
                if ts != signal.timestamp_ms:
                    raise ValidationError("next available bar is not contiguous with signal")
                entry_equity = a.equity()
                p, reason = a.enter(signal, b, config, strategy.version_id)
                if p is None:
                    decision(signal, "REJECTED", reason, execution_ms=ts)
                else:
                    attempted.append((a,b,signal,p,entry_equity,a.cash,a.reserved()))
        # Current candle volume is only known at completion. A zero-volume
        # attempted fill is cancelled AFTER simultaneous orders have reserved
        # funds, never used as future knowledge to free cash for another symbol.
        for a,b,signal,p,entry_equity,cash_after,reserved in attempted:
            if b.volume <= 0:
                a.cash += p.margin + p.entry_fee
                del a.positions[p.symbol]
                decision(signal,"REJECTED","ENTRY_UNFILLED_ZERO_VOLUME",execution_ms=b.end_ms,order_submitted_ms=ts)
                continue
            position_count += 1
            if position_count > MAX_TRADES:
                raise ResourceLimit("10,000-entry replay bound exceeded; no partial result")
            decision(signal, "ENTERED", "ACCEPTED", execution_ms=ts, trade_id=p.trade_id,
                     equity_before=entry_equity,cash_after=cash_after,reserved_capital=reserved,
                     quantity=p.quantity,planned_risk=p.planned_risk,risk_budget=p.risk_budget)
        for b in bars:
            note = _intrabar(account_for(b.symbol), b, config)
            if note:
                warnings.append(f"{b.symbol} {b.end_ms}: {note['reason']}")
        for b in bars:
            account_for(b.symbol).marks[b.symbol] = b.close
            last_bars[b.symbol] = b
        end = ts + interval
        if end >= config.start_ms:
            equity.extend(a.observe_equity(end) for a in accounts.values())
        for b in bars:
            h = histories[b.symbol]
            h.append(b)
            if b.end_ms < config.start_ms or len(h) < strategy.warmup_bars:
                continue
            signal = strategy.evaluate(tuple(h))
            _check_signal(signal, b)
            counts[b.symbol]["evaluations"] += 1
            if signal.side == "NO_SIGNAL":
                counts[b.symbol]["no_signal"] += 1
                continue
            counts[b.symbol]["qualified_signals"] += 1
            key = (signal.symbol, signal.timestamp_ms)
            if key in seen:
                decision(signal, "REJECTED", "DUPLICATE_SIGNAL_CANDLE")
                continue
            seen.add(key)
            if b.end_ms >= config.end_ms:
                decision(signal, "REJECTED", "NO_NEXT_BAR_INSIDE_TEST")
            else:
                pending[b.symbol] = signal

    if config.end_policy == "CLOSE_AT_LAST_CLOSE":
        for a in accounts.values():
            for p in list(a.positions.values()):
                last = last_bars[p.symbol]
                if last.volume <= 0:
                    warnings.append(f"{p.symbol}: requested end close unfilled due to zero recorded volume; remains OPEN")
                    continue
                a.close(p, a.marks[p.symbol], config.end_ms, config, "END_OF_TEST_EXPLICIT", (config.end_ms, config.end_ms))
            equity.append(a.observe_equity(config.end_ms))
    reconciliation = {n: a.reconcile() for n, a in accounts.items()}
    if any(abs(r[k]) > Decimal("1e-20") for r in reconciliation.values() for k in ("cash_residual", "equity_residual")):
        raise ArithmeticError("wallet reconciliation failed")
    result = {"schema_version": 1, "engine_version": "OFFLINE_REPLAY_V1",
              "label": "SYNTHETIC ENGINE VERIFICATION" if dataset.synthetic else "DECLARED HISTORICAL PRICE REPLAY — NOT CERTIFIED EXECUTION",
              "strategy_parity": "HKS NORMAL/REVERSE NOT VERIFIED",
              "strategy_version": strategy.version_id, "strategy_hash": strategy.content_hash,
              "dataset_hash": dataset.content_hash, "input_hashes": dataset.input_hashes,
              "dataset_id": dataset.dataset_id, "exchange": dataset.exchange, "market": dataset.market,
              "source": dataset.source, "retrieved_at": dataset.retrieved_at, "synthetic": dataset.synthetic,
              "config": asdict(config), "symbols": selected,
              "coverage": [c for c in coverage(dataset) if c["symbol"] in selected],
              "decisions": sorted(journal,key=lambda d:(d["signal_ms"],d["symbol"])), "signal_counts": counts,
              "trades": sorted([t for a in accounts.values() for t in a.closed], key=lambda t: (t["exit_ms"], t["symbol"], t["trade_id"])),
              "open_positions": [asdict(p) | {"mark_price": a.marks[p.symbol], "unrealized_pnl": a.unrealized(p)}
                                 for a in accounts.values() for p in a.positions.values()],
              "accounts": {n: {"initial_capital": a.initial, "available_cash": a.cash,
                                "reserved_capital": a.reserved(), "reserved_risk": a.reserved_risk(),
                                "ending_equity": a.equity(), "max_drawdown": a.max_drawdown,
                                "max_drawdown_fraction": a.max_drawdown_fraction} for n, a in accounts.items()},
              "equity_curve": equity, "reconciliation": reconciliation,
              "warnings": sorted(set(warnings + [
                  "Illustrative SMA/static-stop rules only; authentic Normal/Reverse and original trailing parity NOT VERIFIED.",
                  "Fees/slippage are supplied assumptions. Slippage is already included in fill PnL: do NOT subtract it again.",
                  "Quantity rounds down to 1e-8 simulator units; this is NOT a historical exchange lot/tick filter.",
                  "OHLC path unknown: stop before target; stop/target fills use interval-only timestamps; MFE/MAE on exit candles are conservative observed bounds.",
                  "Same-time orders: gap exits, then alphabetic symbol entries, then intrabar exits. Same-bar intrabar proceeds cannot fund simultaneous entries.",
                  "Zero-volume attempted entries cancel at candle completion; simultaneous orders cannot use the subsequently released reservation.",
                  "Drawdown is sampled at common candle closes/opening gaps, not tick-level intrabar drawdown.",
                  "Positive recorded candle volume does not prove your order could fill. No order-book or latency certification.",
                  "No scaling, partial exits, trailing, liquidations, funding, live strategy activation or exchange orders implemented."
              ]))}
    result = primitives(result)
    result["result_hash"] = digest(result)
    return result
