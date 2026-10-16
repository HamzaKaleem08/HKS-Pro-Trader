"""Computed reports. Aggregate independent wallets are not one account's ROI."""
import csv
from decimal import Decimal, localcontext
import io

from .common import primitives, utc

ZERO = Decimal(0)


def _sum(rows, key):
    return sum((Decimal(str(t[key])) for t in rows), ZERO)


def _performance(trades):
    values = [Decimal(t["net_pnl"]) for t in trades]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    return {"closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
            "breakeven": len(values) - len(wins) - len(losses),
            "win_rate_pct": (Decimal(len(wins)) / len(values) * 100) if values else None,
            "gross_pnl_after_slippage": _sum(trades, "gross_pnl"),
            "fees_closed_trades": _sum(trades, "fees"), "slippage_already_in_pnl": _sum(trades, "slippage_cost"),
            "realized_net_pnl": _sum(trades, "net_pnl"),
            "average_net_win": sum(wins, ZERO) / len(wins) if wins else None,
            "average_net_loss": sum(losses, ZERO) / len(losses) if losses else None,
            "expectancy_closed": sum(values, ZERO) / len(values) if values else None,
            "mean_mfe_pct": _sum(trades, "mfe_pct") / len(trades) if trades else None,
            "mean_mae_pct": _sum(trades, "mae_pct") / len(trades) if trades else None,
            "long_trades": sum(t["side"] == "LONG" for t in trades),
            "short_trades": sum(t["side"] == "SHORT" for t in trades)}


def build_reports(result):
    with localcontext() as ctx:
        ctx.prec = 34
        return _build_reports(result)


def _build_reports(result):
    by_coin = []
    for sym in result["symbols"]:
        trades = [t for t in result["trades"] if t["symbol"] == sym]
        opened = [p for p in result["open_positions"] if p["symbol"] == sym]
        account = result["accounts"].get(sym) if result["config"]["mode"] == "individual" else None
        row = {"symbol": sym, **result["signal_counts"][sym], **_performance(trades),
               "open_trades": len(opened), "unrealized_pnl": _sum(opened, "unrealized_pnl"),
               "open_entry_fees": _sum(opened, "entry_fee"),
               "starting_capital": None if account is None else account["initial_capital"],
               "ending_equity": None if account is None else account["ending_equity"],
               "drawdown": None if account is None else account["max_drawdown"],
               "drawdown_scope": "INDEPENDENT_ACCOUNT" if account else "NOT_AN_INDEPENDENT_SHARED_COIN_WALLET"}
        row["exit_reasons"] = {reason:sum(t["exit_reason"]==reason for t in trades) for reason in sorted({t["exit_reason"] for t in trades})}
        by_coin.append(row)
    start = sum((Decimal(a["initial_capital"]) for a in result["accounts"].values()), ZERO)
    end = sum((Decimal(a["ending_equity"]) for a in result["accounts"].values()), ZERO)
    if result["config"]["mode"] == "shared":
        drawdown = Decimal(result["accounts"]["SHARED"]["max_drawdown"])
    else:
        # Combine contemporaneous independent account values, never transiently mix
        # account updates into a fictitious capital allocation sequence.
        snapshots = {}
        for row in result["equity_curve"]:
            snapshots.setdefault(row["timestamp_ms"], {})[row["account"]] = Decimal(row["equity"])
        current = {name: Decimal(a["initial_capital"]) for name,a in result["accounts"].items()}
        peak, drawdown = start, ZERO
        for ts in sorted(snapshots):
            current.update(snapshots[ts]); value = sum(current.values(), ZERO)
            peak = max(peak, value); drawdown = max(drawdown, peak-value)
    counts = {}
    monthly = {}
    for trade in result["trades"]:
        counts[trade["exit_reason"]] = counts.get(trade["exit_reason"], 0) + 1
        monthly.setdefault(utc(trade["exit_ms"])[:7], []).append(trade)
    total = {**_performance(result["trades"]), "starting_capital": start, "ending_equity": end,
             "net_equity_change": end - start,
             "return_on_total_starting_capital_pct": (end-start)/start*100,
             "capital_scope": "ONE_SHARED_ACCOUNT" if result["config"]["mode"] == "shared" else "SUM_OF_INDEPENDENT_SYMBOL_ACCOUNTS",
             "open_trades": len(result["open_positions"]), "unrealized_pnl": _sum(result["open_positions"],"unrealized_pnl"),
             "open_entry_fees": _sum(result["open_positions"],"entry_fee"),
             "available_cash": sum((Decimal(a["available_cash"]) for a in result["accounts"].values()),ZERO),
             "reserved_capital": sum((Decimal(a["reserved_capital"]) for a in result["accounts"].values()),ZERO),
             "reserved_risk": sum((Decimal(a["reserved_risk"]) for a in result["accounts"].values()),ZERO),
             "max_drawdown": drawdown, "drawdown_scope": "SAMPLED_EQUITY_NOT_TICK_PRECISION",
             "qualified_signals": sum(c["qualified_signals"] for c in result["signal_counts"].values()),
             "rejected_entries": sum(sum(c["rejections"].values()) for c in result["signal_counts"].values()),
             "ambiguous_stop_target": sum(bool(t["ambiguous_stop_target"]) for t in result["trades"])}
    return primitives({"summary": total, "coins": by_coin, "exit_reasons": counts,
                       "monthly_realized_by_exit": [{"month_utc": m, **_performance(rows)} for m,rows in sorted(monthly.items())]})


TRADE_COLUMNS = ("trade_id", "symbol", "side", "state", "entry_utc", "exit_utc", "entry_price", "exit_price",
                 "quantity", "notional", "margin", "risk_budget", "planned_risk", "initial_stop", "stop", "target",
                 "gross_pnl", "fees", "slippage_cost", "net_pnl", "mfe_pct", "mae_pct", "exit_reason",
                 "holding_minutes", "timestamp_precision", "ambiguous_stop_target", "strategy_version")
COIN_COLUMNS = ("symbol", "starting_capital", "qualified_signals", "closed_trades", "open_trades", "long_trades", "short_trades",
                "wins", "losses", "win_rate_pct", "gross_pnl_after_slippage", "fees_closed_trades", "slippage_already_in_pnl",
                "realized_net_pnl", "unrealized_pnl", "open_entry_fees", "ending_equity", "drawdown", "drawdown_scope",
                "mean_mfe_pct","mean_mae_pct","average_net_win","average_net_loss","expectancy_closed","rejections","exit_reasons")


def _safe_cell(value):
    if value is None:
        return ""
    if isinstance(value,(dict,list)):
        from .common import canonical
        value=canonical(value)
    value = str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        try:
            numeric = Decimal(value)
            if not numeric.is_finite(): raise ValueError
        except (ValueError, ArithmeticError):
            value = "'" + value
    return value


def csv_report(result, kind):
    if kind == "trades":
        columns = TRADE_COLUMNS
        rows = [t | {"entry_utc": utc(t["entry_ms"]), "exit_utc": utc(t["exit_ms"]),
                     "holding_minutes": Decimal(t["holding_ms"]) / 60_000} for t in result["trades"]]
    elif kind == "coins":
        columns, rows = COIN_COLUMNS, build_reports(result)["coins"]
    elif kind == "decisions":
        columns = ("signal_ms","symbol","side","outcome","reason","execution_ms","trade_id")
        rows = result["decisions"]
    else:
        raise ValueError("unsupported CSV kind")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output,fieldnames=columns,extrasaction="ignore")
    writer.writeheader()
    for row in rows: writer.writerow({k:_safe_cell(row.get(k)) for k in columns})
    return output.getvalue()
