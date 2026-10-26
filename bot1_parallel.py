"""Isolated Bot 1 NORMAL/REVERSE simulation ledger.

No imports from the running app; never touches Bot 2 or legacy hks_* financial tables.
The feature must stay disabled until the owner has saved screenshots and approved a reset.
"""
from decimal import Decimal as D
from sqlalchemy import BigInteger, Column, Integer, Numeric, String, ForeignKey, func, select
from sqlalchemy.orm import declarative_base

BaseParallel = declarative_base()
NUM = Numeric(30, 12)
ZERO = D("0")
ONE = D("1")
STRATEGY_SEED = D("1000")
COLLATERAL_SEED = D("2000")
MODES = ("NORMAL", "REVERSE")


class ModeWallet(BaseParallel):
    __tablename__ = "b1_mode_wallet"
    mode = Column(String(8), primary_key=True)
    cash = Column(NUM, nullable=False)


class ModePosition(BaseParallel):
    __tablename__ = "b1_mode_position"
    mode = Column(String(8), primary_key=True)
    symbol = Column(String(26), primary_key=True)
    direction = Column(String(8), nullable=False)
    original_signal = Column(String(8), nullable=False)
    score = Column(Integer, nullable=False)
    entry_ms = Column(BigInteger, nullable=False)
    entry_price = Column(NUM, nullable=False)
    qty = Column(NUM, nullable=False)
    stop = Column(NUM, nullable=False)
    initial_stop = Column(NUM, nullable=False)
    margin = Column(NUM, nullable=False)
    entry_fee = Column(NUM, nullable=False)
    mfe_frac = Column(NUM, nullable=False, default=ZERO)
    mae_frac = Column(NUM, nullable=False, default=ZERO)
    reference_distance = Column(NUM, nullable=False)


class ModeTrade(BaseParallel):
    __tablename__ = "b1_mode_trade"
    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String(8), nullable=False, index=True)
    symbol = Column(String(26), nullable=False)
    direction = Column(String(8), nullable=False)
    original_signal = Column(String(8), nullable=False)
    score = Column(Integer, nullable=False)
    entry_ms = Column(BigInteger, nullable=False)
    exit_ms = Column(BigInteger, nullable=False)
    entry_price = Column(NUM, nullable=False)
    exit_price = Column(NUM, nullable=False)
    qty = Column(NUM, nullable=False)
    initial_stop = Column(NUM, nullable=False)
    exit_reason = Column(String(32), nullable=False)
    entry_fee = Column(NUM, nullable=False)
    exit_fee = Column(NUM, nullable=False)
    gross_pnl = Column(NUM, nullable=False)
    net_pnl = Column(NUM, nullable=False)
    mfe_frac = Column(NUM, nullable=False)
    mae_frac = Column(NUM, nullable=False)


class ModeEquity(BaseParallel):
    __tablename__ = "b1_mode_equity"
    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String(8), nullable=False, index=True)
    time_ms = Column(BigInteger, nullable=False)
    balance = Column(NUM, nullable=False)  # $1k strategy equity, NEVER $2k collateral
    trade_id = Column(Integer, ForeignKey("b1_mode_trade.id"), nullable=True)


class ModeExit(BaseParallel):
    __tablename__ = "b1_mode_exit"
    mode = Column(String(8), primary_key=True)
    symbol = Column(String(26), primary_key=True)
    last_exit_15m_end = Column(BigInteger, nullable=False)


class ModeDecision(BaseParallel):
    __tablename__ = "b1_mode_decision"
    symbol = Column(String(26), primary_key=True)
    mode = Column(String(8), primary_key=True)
    decision_ms = Column(BigInteger, primary_key=True)
    status = Column(String(16), nullable=False)  # OPEN / CAP / CASH / ALREADY_OPEN
    score = Column(Integer, nullable=False)


def bootstrap(engine, Session, now_ms):
    """New isolated tables. Call only when the feature is explicitly enabled."""
    BaseParallel.metadata.create_all(engine)
    with Session.begin() as db:
        for mode in MODES:
            if db.get(ModeWallet, mode) is None:
                db.add(ModeWallet(mode=mode, cash=COLLATERAL_SEED))
                db.add(ModeEquity(mode=mode, time_ms=now_ms, balance=STRATEGY_SEED))


def mode_positions(db, mode):
    return list(db.scalars(select(ModePosition).where(ModePosition.mode == mode)))


def realized_equity(db, mode):
    pnl = db.scalar(select(func.coalesce(func.sum(ModeTrade.net_pnl), ZERO)).where(ModeTrade.mode == mode))
    return STRATEGY_SEED + (pnl or ZERO)


def strategy_equity(db, mode, prices):
    result = realized_equity(db, mode)
    unrealized = ZERO
    for p in mode_positions(db, mode):
        px = prices.get(p.symbol, p.entry_price)
        signed = ONE if p.direction == "LONG" else -ONE
        pnl = signed * (px - p.entry_price) * p.qty
        unrealized += pnl
    return result + unrealized, unrealized


def open_position(db, mode, symbol, original, score, stop_fraction, quote, now_ms,
                  fee_rate, risk_fraction, cash_fraction, max_positions):
    """Risk uses ONLY the $1k strategy ledger; $1k buffer cannot inflate sizing."""
    if mode not in MODES or original not in ("LONG", "SHORT"):
        return None, "BAD_SIGNAL"
    if db.get(ModePosition, (mode, symbol)) is not None:
        return None, "ALREADY_OPEN"
    existing = mode_positions(db, mode)
    if len(existing) >= max_positions:
        return None, "CAP"
    wallet = db.get(ModeWallet, mode)
    if wallet is None or quote <= ZERO or stop_fraction <= ZERO:
        return None, "INVALID"
    equity, _ = strategy_equity(db, mode, {p.symbol: p.entry_price for p in existing})
    if equity <= ZERO or wallet.cash <= ZERO:
        return None, "EQUITY"
    # MAX_POSITION_CASH_FRACTION applied to the strategy ledger, not $2k cash.
    # Buffer only releases collateral friction; it does not double target risk.
    reference_cash = max(ZERO, realized_equity(db, mode))
    notional = min(equity * risk_fraction / stop_fraction,
                   reference_cash * cash_fraction / (ONE + fee_rate))
    if notional <= D("5"):
        return None, "SIZE"
    fee = notional * fee_rate
    if wallet.cash < notional + fee:
        return None, "CASH"
    direction = original if mode == "NORMAL" else ("SHORT" if original == "LONG" else "LONG")
    stop = quote * (ONE - stop_fraction if direction == "LONG" else ONE + stop_fraction)
    position = ModePosition(mode=mode, symbol=symbol, direction=direction,
        original_signal=original, score=score, entry_ms=now_ms,
        entry_price=quote, qty=notional / quote, stop=stop, initial_stop=stop,
        margin=notional, entry_fee=fee, mfe_frac=ZERO, mae_frac=ZERO,
        reference_distance=abs(quote-stop)*2)
    wallet.cash -= notional + fee
    db.add(position)
    return position, "OPEN"


def close_position(db, pos, fill, fill_ms, reason, fee_rate):
    wallet = db.get(ModeWallet, pos.mode)
    signed = ONE if pos.direction == "LONG" else -ONE
    gross = signed * (fill-pos.entry_price) * pos.qty
    exit_fee = abs(fill*pos.qty)*fee_rate
    net = gross-pos.entry_fee-exit_fee
    wallet.cash += pos.margin+gross-exit_fee
    trade = ModeTrade(mode=pos.mode, symbol=pos.symbol, direction=pos.direction,
        original_signal=pos.original_signal, score=pos.score,
        entry_ms=pos.entry_ms, exit_ms=fill_ms, entry_price=pos.entry_price,
        exit_price=fill, qty=pos.qty, initial_stop=pos.initial_stop,
        exit_reason=reason, entry_fee=pos.entry_fee, exit_fee=exit_fee,
        gross_pnl=gross, net_pnl=net, mfe_frac=pos.mfe_frac, mae_frac=pos.mae_frac)
    db.add(trade)
    db.flush()
    db.add(ModeEquity(mode=pos.mode, time_ms=fill_ms,
                      balance=realized_equity(db, pos.mode), trade_id=trade.id))
    exit_key=(pos.mode,pos.symbol)
    previous=db.get(ModeExit,exit_key)
    exit_end=((fill_ms+899999)//900000)*900000
    if previous:
        previous.last_exit_15m_end=exit_end
    else:
        db.add(ModeExit(mode=pos.mode,symbol=pos.symbol,last_exit_15m_end=exit_end))
    db.delete(pos)
    return trade


def check_position(db, pos, minute_bars, fee_rate, mark_excursion,
                   get_stop_fill, trail_stop):
    """Exactly the existing bar causality: check old SL before moving trailing SL."""
    for bar in minute_bars:
        if bar["end"] <= pos.entry_ms:
            continue
        if bar["t"] < pos.entry_ms < bar["end"]:
            continue
        mark_excursion(pos, bar)
        fill=get_stop_fill(pos,bar)
        if fill is not None:
            return close_position(db,pos,fill,bar["end"],
               "TRAILING SL HIT" if pos.stop != pos.initial_stop else "INITIAL SL HIT",
               fee_rate)
        trail_stop(pos,bar["h"] if pos.direction == "LONG" else bar["l"])
    return None


def open_pair(db, coin, evaluation, quote, now_ms, fee_rate, risk_fraction,
              cash_fraction, max_positions):
    """One completed signal yields 1 atomic NORMAL attempt and 1 REVERSE attempt."""
    results={}
    for mode in MODES:
        prior=db.get(ModeExit,(mode,coin.symbol))
        key=(coin.symbol,mode,now_ms)
        if prior and prior.last_exit_15m_end == evaluation["end_ms"]:
            status="COOLDOWN"
            pos=None
        else:
            pos,status=open_position(db,mode,coin.symbol,evaluation["original"],
                    evaluation["trade_score"],evaluation["stop_fraction"],quote,
                    now_ms,fee_rate,risk_fraction,cash_fraction,max_positions)
        db.add(ModeDecision(symbol=coin.symbol, mode=mode, decision_ms=now_ms,
                            status=status, score=evaluation["trade_score"]))
        results[mode]=(pos,status)
    return results


def reset_parallel(db, at_ms):
    """Destructive reset intended ONLY for separate owner-confirmed UI action."""
    from sqlalchemy import delete
    for table in (ModeDecision,ModeExit,ModeEquity,ModeTrade,ModePosition):
        db.execute(delete(table))
    for mode in MODES:
        wallet=db.get(ModeWallet,mode)
        if wallet is None:
            db.add(ModeWallet(mode=mode,cash=COLLATERAL_SEED))
        else:
            wallet.cash=COLLATERAL_SEED
        db.add(ModeEquity(mode=mode,time_ms=at_ms,balance=STRATEGY_SEED))
