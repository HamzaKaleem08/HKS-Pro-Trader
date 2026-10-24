"""Independent Bot 2 / MEXC Spot long-only PAPER scanner.

Never sends exchange orders. New b2_* tables only; Bitget Bot 1 remains unchanged.
Entry: original HKS 15m SMC score>=85, LONG signal only.
Initial stop: 2 * original ATR stop; trailing anchor: original 2R, NEVER
2 * the widened stop. Exit: original HKS 1m candle/trailing model.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation

import requests
from flask import jsonify, render_template, request
from sqlalchemy import BigInteger, Column, Integer, Numeric, String, Text, select, func, text, insert, delete
from sqlalchemy.orm import declarative_base

LOG = logging.getLogger("hks.bot2")
ZERO = D("0")
ONE = D("1")
COINS = ("TNKUSDT", "CYSUSDT")
START_BALANCE = D("1000")
SCANNER_LOCK = 47002211
MEXC_BASE = os.environ.get("HKS_BOT2_MEXC_BASE", "https://api.mexc.com").rstrip("/")
# Explicit opt-in after deployment/source validation. Public dashboard still works.
PAPER_ENABLED = os.environ.get("HKS_BOT2_PAPER_ENABLED", "0").strip() == "1"
PAPER_NOTIONAL = D(os.environ.get("HKS_BOT2_NOTIONAL_USDT", "50"))
FEE_RATE = D(os.environ.get("HKS_BOT2_FEE_RATE", "0.001"))  # illustrative side fee, not exchange assertion
MAX_BUY_IMPACT = D(os.environ.get("HKS_BOT2_MAX_BUY_IMPACT", "0.015"))
MAX_SPREAD = D(os.environ.get("HKS_BOT2_MAX_SPREAD", "0.012"))
EXIT_SLIPPAGE = D(os.environ.get("HKS_BOT2_EXIT_SLIPPAGE", "0.003"))
if not (D("5") <= PAPER_NOTIONAL <= D("500")
        and ZERO <= FEE_RATE < D("0.02")
        and ZERO <= MAX_BUY_IMPACT < D("0.10")
        and ZERO <= MAX_SPREAD < D("0.10")
        and ZERO <= EXIT_SLIPPAGE < D("0.10")):
    raise RuntimeError("Invalid HKS Bot2 paper risk parameters")
M1_STEP = 60_000
Q15_STEP = 900_000
H1_STEP = 3_600_000
_runner = threading.Lock()
_start_guard = threading.Lock()
_thread = None


def _now():
    return int(time.time() * 1000)


def _fmt(value, digits=8):
    return None if value is None else f"{D(value):.{digits}f}"


def _num(value):
    n = D(str(value))
    if not n.is_finite():
        raise ValueError("Non-finite market data")
    return n


def _http_get(path, **params):
    # Only public endpoints, no credentials and no placement endpoint.
    response = requests.get(MEXC_BASE + "/api/v3/" + path,
                            params=params, timeout=(4, 9),
                            headers={"User-Agent": "HKS-Bot2-Paper/1.0"})
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("code") not in (None, 200, 0):
        raise ValueError("MEXC API error code " + str(data.get("code")))
    return data


def _bars(symbol, interval, limit, now_ms):
    if symbol not in COINS or interval not in ("1m", "15m", "60m"):
        raise ValueError("Unsupported Bot2 market")
    step = {"1m": M1_STEP, "15m": Q15_STEP, "60m": H1_STEP}[interval]
    raw = _http_get("klines", symbol=symbol, interval=interval, limit=limit)
    if not isinstance(raw, list) or not raw:
        raise ValueError("Missing MEXC candles")
    bars = []
    for k in raw:
        t = int(k[0])
        if t + step > now_ms:
            continue
        o, h, l, c = [_num(k[i]) for i in (1, 2, 3, 4)]
        if not (o > ZERO and l > ZERO and l <= min(o, c, h) and h >= max(o, c)):
            raise ValueError("Invalid MEXC OHLC")
        bars.append({"t": t, "end": t + step, "o": o, "h": h, "l": l, "c": c})
    if not bars or any(b["t"] != a["end"] for a, b in zip(bars, bars[1:])):
        raise ValueError("Missing/noncontiguous MEXC candles")
    return bars


def _book(symbol):
    if symbol not in COINS:
        raise ValueError("Coin not allowlisted")
    raw = _http_get("depth", symbol=symbol, limit=100)
    bids = [(_num(p), _num(q)) for p, q in raw["bids"]]
    asks = [(_num(p), _num(q)) for p, q in raw["asks"]]
    if not bids or not asks or min(bids[0][0], asks[0][0]) <= ZERO:
        raise ValueError("Empty order book")
    if bids[0][0] >= asks[0][0]:
        raise ValueError("Crossed MEXC book")
    return bids, asks


def _buy_quote(asks, notional):
    """Paper BUY using available *current* ask levels, not a made-up mid fill."""
    left = notional
    qty = ZERO
    for price, depth in asks:
        if price <= ZERO or depth <= ZERO:
            continue
        spend = min(left, price * depth)
        qty += spend / price
        left -= spend
        if left < D("0.00000001"):
            break
    if left >= D("0.00000001") or qty <= ZERO:
        raise ValueError("Insufficient spot ask depth")
    return notional / qty, qty



def _sell_quote(bids, qty):
    """Paper manual close at current public bid book depth (not a real sell)."""
    left, proceeds = qty, ZERO
    for price, depth in bids:
        if price <= ZERO or depth <= ZERO:
            continue
        units = min(left, depth)
        proceeds += price * units
        left -= units
        if left < D("0.000000000001"):
            break
    if left >= D("0.000000000001") or proceeds <= ZERO:
        raise ValueError("Insufficient bid-side depth for paper manual close")
    return proceeds / qty


def install_bot2(app, *, Session, engine, Base, db_postgres,
                 evaluate_smc, trail_stop, get_stop_fill,
                 require_cron_token, require_owner, same_origin_post,
                 check_reset_attempt):
    """Register isolated schema, HTTP routes and scanner on existing Flask app."""
    NUM = Numeric(30, 12)

    class B2Wallet(Base):
        __tablename__ = "hks_b2_wallet"
        id = Column(Integer, primary_key=True)
        cash = Column(NUM, nullable=False)

    class B2Coin(Base):
        __tablename__ = "hks_b2_coin"
        symbol = Column(String(26), primary_key=True)
        score = Column(Integer, nullable=False, default=0)
        trade_score = Column(Integer, nullable=False, default=0)
        signal = Column(String(32), nullable=False, default="WAIT")
        last_price = Column(NUM)
        last_bar_end = Column(BigInteger)
        last_decision_end = Column(BigInteger)
        last_exit_15m_end = Column(BigInteger)
        updated_ms = Column(BigInteger)
        error = Column(String(255))

    class B2Position(Base):
        __tablename__ = "hks_b2_position"
        symbol = Column(String(26), primary_key=True)
        direction = Column(String(8), nullable=False, default="LONG")
        score = Column(Integer, nullable=False)
        entry_ms = Column(BigInteger, nullable=False)
        entry_price = Column(NUM, nullable=False)
        qty = Column(NUM, nullable=False)
        margin = Column(NUM, nullable=False)
        entry_fee = Column(NUM, nullable=False)
        initial_stop = Column(NUM, nullable=False)
        stop = Column(NUM, nullable=False)
        reference_distance = Column(NUM, nullable=False)
        mfe_frac = Column(NUM, nullable=False, default=ZERO)
        mae_frac = Column(NUM, nullable=False, default=ZERO)

    class B2Closed(Base):
        __tablename__ = "hks_b2_closed_trade"
        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(26), nullable=False)
        score = Column(Integer, nullable=False)
        entry_ms = Column(BigInteger, nullable=False)
        exit_ms = Column(BigInteger, nullable=False)
        entry_price = Column(NUM, nullable=False)
        exit_price = Column(NUM, nullable=False)
        qty = Column(NUM, nullable=False)
        margin = Column(NUM, nullable=False)
        initial_stop = Column(NUM, nullable=False)
        exit_reason = Column(String(36), nullable=False)
        entry_fee = Column(NUM, nullable=False)
        exit_fee = Column(NUM, nullable=False)
        gross_pnl = Column(NUM, nullable=False)
        net_pnl = Column(NUM, nullable=False)
        mfe_frac = Column(NUM, nullable=False)
        mae_frac = Column(NUM, nullable=False)

    class B2Equity(Base):
        __tablename__ = "hks_b2_equity"
        id = Column(Integer, primary_key=True, autoincrement=True)
        time_ms = Column(BigInteger, nullable=False)
        balance = Column(NUM, nullable=False)

    class B2Bar(Base):
        """Archive only the genuine minute candles seen in forward scans."""
        __tablename__ = "hks_b2_1m_bar"
        symbol = Column(String(26), primary_key=True)
        start_ms = Column(BigInteger, primary_key=True)
        o = Column(NUM, nullable=False)
        h = Column(NUM, nullable=False)
        l = Column(NUM, nullable=False)
        c = Column(NUM, nullable=False)

    class B2Health(Base):
        __tablename__ = "hks_b2_health"
        id = Column(Integer, primary_key=True)
        last_attempt_ms = Column(BigInteger)
        last_success_ms = Column(BigInteger)
        last_duration_ms = Column(BigInteger)
        scan_status = Column(String(24), nullable=False, default="NOT STARTED")
        error = Column(String(255))
        scan_count = Column(Integer, nullable=False, default=0)

    # Never create/alter/drop hks_wallet, hks_position, hks_coin or any Bot 1 table.
    Base.metadata.create_all(engine, tables=[
        B2Wallet.__table__, B2Coin.__table__, B2Position.__table__,
        B2Closed.__table__, B2Equity.__table__, B2Bar.__table__, B2Health.__table__])
    with Session.begin() as db:
        if db.get(B2Wallet, 1) is None:
            db.add(B2Wallet(id=1, cash=START_BALANCE))
            db.add(B2Equity(time_ms=_now(), balance=START_BALANCE))
        for symbol in COINS:
            if db.get(B2Coin, symbol) is None:
                db.add(B2Coin(symbol=symbol, signal="WAIT"))
        if db.get(B2Health, 1) is None:
            db.add(B2Health(id=1))

    def _record_close(db, pos, price, end_ms, reason):
        w = db.get(B2Wallet, 1)
        price = _num(price)
        # Account for approximate spread/slippage on simulated OHLC stop closes.
        # Never represent an OHLC stop as a verified exchange fill.
        gross = (price - pos.entry_price) * pos.qty
        exit_notional = price * pos.qty
        exit_fee = exit_notional * FEE_RATE
        net = gross - exit_fee - pos.entry_fee
        w.cash += exit_notional - exit_fee
        row = B2Closed(symbol=pos.symbol, score=pos.score,
                       entry_ms=pos.entry_ms, exit_ms=end_ms,
                       entry_price=pos.entry_price, exit_price=price,
                       qty=pos.qty, margin=pos.margin, initial_stop=pos.initial_stop,
                       exit_reason=reason, entry_fee=pos.entry_fee,
                       exit_fee=exit_fee, gross_pnl=gross, net_pnl=net,
                       mfe_frac=pos.mfe_frac, mae_frac=pos.mae_frac)
        db.add(row)
        db.flush()
        realized = START_BALANCE + (db.scalar(
            select(func.coalesce(func.sum(B2Closed.net_pnl), ZERO))) or ZERO)
        db.add(B2Equity(time_ms=end_ms, balance=realized))
        coin = db.get(B2Coin, pos.symbol)
        coin.last_exit_15m_end = ((end_ms + Q15_STEP - 1) // Q15_STEP) * Q15_STEP
        coin.signal = reason
        db.delete(pos)
        return row

    def _mark(pos, bar):
        pos.mfe_frac = max(pos.mfe_frac, (bar["h"] - pos.entry_price) / pos.entry_price, ZERO)
        pos.mae_frac = max(pos.mae_frac, (pos.entry_price - bar["l"]) / pos.entry_price, ZERO)

    def _process_position(db, pos, minute_bars):
        for bar in minute_bars:
            if bar["end"] <= pos.entry_ms:
                continue
            if bar["t"] < pos.entry_ms < bar["end"]:
                continue
            _mark(pos, bar)
            fill = get_stop_fill(pos, bar)
            if fill is not None:
                # Research estimated exit; adverse slippage allowance. Entry
                # already uses real public MEXC ask-depth weighted price.
                conservative = fill * (ONE - EXIT_SLIPPAGE)
                return _record_close(db, pos, conservative, bar["end"],
                    "TRAILING SL" if pos.stop != pos.initial_stop else "INITIAL SL")
            # Exact *original* HKS trailing formula, next completed 1m bar effective.
            trail_stop(pos, bar["h"])
        return None

    def _enter(db, coin, score, original_stop_fraction, now_ms, asks, bids):
        if not PAPER_ENABLED:
            coin.signal = "SIGNAL / PAPER OFF"
            return False
        if db.get(B2Position, coin.symbol) is not None:
            return False
        wallet = db.get(B2Wallet, 1)
        # 1x spot collateral, no borrowing or leverage, same-size per trade.
        notional = min(PAPER_NOTIONAL, wallet.cash / (ONE + FEE_RATE))
        if notional < D("5"):
            coin.signal = "INSUFFICIENT PAPER CASH"
            return False
        bid, ask = bids[0][0], asks[0][0]
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        if spread > MAX_SPREAD:
            coin.signal = "SKIP WIDE SPREAD"
            return False
        try:
            entry, qty = _buy_quote(asks, notional)
        except ValueError:
            coin.signal = "SKIP LOW LIQUIDITY"
            return False
        if entry / mid - ONE > MAX_BUY_IMPACT:
            coin.signal = "SKIP BUY IMPACT"
            return False
        fee = notional * FEE_RATE
        if wallet.cash < notional + fee:
            return False
        # Approved: 200% original ATR stop. Trailing reference *not* widened.
        initial = entry * (ONE - D("2") * original_stop_fraction)
        anchor = entry * original_stop_fraction * D("2")
        if initial <= ZERO or anchor <= ZERO:
            coin.signal = "INVALID STOP"
            return False
        db.add(B2Position(symbol=coin.symbol, direction="LONG", score=score,
                entry_ms=now_ms, entry_price=entry, qty=qty,
                margin=notional, entry_fee=fee, initial_stop=initial, stop=initial,
                reference_distance=anchor, mfe_frac=ZERO, mae_frac=ZERO))
        wallet.cash -= notional + fee
        coin.signal = "OPEN LONG PAPER"
        return True

    def _scan_one(symbol, now_ms):
        """Exchange I/O entirely outside DB transaction. Return per-coin status."""
        minute = _bars(symbol, "1m", 500, now_ms)
        last_end = minute[-1]["end"]
        with Session() as db:
            state = db.get(B2Coin, symbol)
            saved_end = state.last_bar_end
            pending_position = db.get(B2Position, symbol) is not None
            prev_decision = state.last_decision_end
        if now_ms - last_end > 180_000:
            raise ValueError("MEXC minute feed stale")
        if saved_end and last_end - saved_end < 0:
            raise ValueError("Candle time moved backwards")
        # No skipped 1m candles with an OPEN position (critical stop safety).
        # Flat positions may resynchronize from genuine available minute bars.
        resync = bool(saved_end and last_end - saved_end > 499 * M1_STEP)
        if resync and pending_position:
            raise ValueError("STOP: OPEN POSITION candle gap over 499m; manual review")
        replay_anchor = None if resync else saved_end
        future = [x for x in minute if replay_anchor is None or x["end"] > replay_anchor]
        if replay_anchor and future and future[0]["t"] != replay_anchor:
            raise ValueError("Missing 1m candles since previous scan")
        # One 15m decision at the CURRENT completed boundary only. No retro-entry.
        needs_decision = last_end % Q15_STEP == 0 and last_end != prev_decision
        q15 = hour = decision = None
        if needs_decision:
            q15 = _bars(symbol, "15m", 35, now_ms)
            hour = _bars(symbol, "60m", 25, now_ms)
            # During a partial 1h, latest hour must be fully completed.
            if len(q15) < 26 or len(hour) < 21 or q15[-1]["end"] != last_end:
                raise ValueError("SMC warmup / completed 15m candle missing")
            decision = evaluate_smc(q15, hour, last_end)
        # Fetch depth for fresh indicative price and for new entry. Never
        # fall back to Bitget prices or stale archived candles.
        bids, asks = _book(symbol)
        mark_bid = bids[0][0]
        if mark_bid <= ZERO:
            raise ValueError("No MEXC bid")
        with Session.begin() as db:
            coin = db.get(B2Coin, symbol)
            old = coin.last_bar_end
            if old != saved_end:
                # Another same-symbol scan already applied the candles.
                return {"symbol": symbol, "status": "raced"}
            coin.last_price = mark_bid
            coin.updated_ms = now_ms
            coin.error = None
            pos = db.get(B2Position, symbol)
            if pos is not None and future:
                _process_position(db, pos, future)
            if future:
                # Bulk store public authentic bars, minimizing free-tier DB trips.
                # Safe flat-coin resync avoids duplicate archive primary keys.
                inserts = future
                if resync:
                    existing = set(db.scalars(select(B2Bar.start_ms).where(
                        B2Bar.symbol == symbol,
                        B2Bar.start_ms >= future[0]["t"],
                        B2Bar.start_ms <= future[-1]["t"])).all())
                    inserts = [bar for bar in future if bar["t"] not in existing]
                if inserts:
                    db.execute(insert(B2Bar), [{"symbol": symbol,
                        "start_ms": bar["t"], "o": bar["o"],
                        "h": bar["h"], "l": bar["l"], "c": bar["c"]} for bar in inserts])
            coin.last_bar_end = last_end
            if decision is not None and coin.last_decision_end != last_end:
                coin.last_decision_end = last_end
                coin.score = decision["display"]
                coin.trade_score = decision["trade_score"]
                original = decision["original"]
                coin.signal = "WATCH LONG" if original == "LONG" else (
                    "SHORT FILTERED" if original == "SHORT" else "NO SWEEP")
                if (original == "LONG" and decision["trade_score"] >= 85
                        and db.get(B2Position, symbol) is None
                        and coin.last_exit_15m_end != last_end):
                    _enter(db, coin, decision["trade_score"],
                           decision["stop_fraction"], now_ms, asks, bids)
            return {"symbol": symbol, "status": "ok", "new_bars": len(future),
                    "decision": bool(decision)}

    def scan_once():
        """Independent status, own PG advisory lock; never blocks Bot1 locks."""
        if not _runner.acquire(blocking=False):
            return {"status": "busy"}
        connection = None
        started = _now()
        try:
            if db_postgres:
                connection = engine.connect()
                locked = connection.execute(text("SELECT pg_try_advisory_lock(:id)"),
                                            {"id": SCANNER_LOCK}).scalar()
                if not locked:
                    return {"status": "busy"}
            with Session.begin() as db:
                st = db.get(B2Health, 1)
                if st.last_attempt_ms and started - st.last_attempt_ms < 40_000:
                    return {"status": "skipped"}
                st.last_attempt_ms = started
            outcomes, errors = [], {}
            for symbol in COINS:
                try:
                    outcomes.append(_scan_one(symbol, started))
                except Exception as exc:
                    LOG.exception("Bot2 paper scanner %s failed", symbol)
                    errors[symbol] = str(exc)[:180]
                    with Session.begin() as db:
                        coin = db.get(B2Coin, symbol)
                        coin.error = errors[symbol]
                        coin.signal = "FEED ERROR / PAUSED"
            finished = _now()
            with Session.begin() as db:
                st = db.get(B2Health, 1)
                st.scan_count = len(outcomes)
                st.last_duration_ms = finished - started
                st.error = "; ".join(f"{k}: {v}" for k, v in errors.items())[:255] if errors else None
                st.scan_status = "PARTIAL" if errors else "OK"
                if not errors:
                    st.last_success_ms = finished
            return {"status": "partial" if errors else "ok",
                    "processed": len(outcomes), "errors": errors, "coins": outcomes}
        except Exception as exc:
            LOG.exception("Bot2 failed; Bot1 unaffected")
            with Session.begin() as db:
                st = db.get(B2Health, 1)
                st.scan_status = "ERROR"
                st.error = str(exc)[:255]
            return {"status": "error", "reason": str(exc)[:180]}
        finally:
            if connection is not None:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:id)"),
                                       {"id": SCANNER_LOCK})
                finally:
                    connection.close()
            _runner.release()

    def _automatic_loop():
        previous_minute = None
        while True:
            minute = int(time.time() // 60)
            if minute != previous_minute:
                previous_minute = minute
                try:
                    scan_once()
                except Exception:
                    LOG.exception("Bot2 best-effort background scan failed")
            time.sleep(2)

    def _ensure_loop():
        global _thread
        if not PAPER_ENABLED:
            return
        # Serverless never keeps a reliable Python thread; use cron endpoint.
        if os.environ.get("VERCEL", "").lower() in ("1", "true"):
            return
        with _start_guard:
            if _thread is None or not _thread.is_alive():
                _thread = threading.Thread(target=_automatic_loop,
                                           name="hks-bot2-mexc-paper", daemon=True)
                _thread.start()

    @app.before_request
    def _bot2_background_on_visit():
        # Protected cron must run request-bound without a competing auto scan.
        # /wake and Bot1 /api/cron remain fully Bot1-owned.
        if request.path not in ("/api/bot2/cron", "/bot2/wake", "/wake", "/api/cron"):
            _ensure_loop()

    @app.get("/bot2/wake")
    @app.get("/api/bot2/cron")
    def bot2_cron():
        """Simple external minute cron: public GET, no key or custom header.

        Same request-bound model as Bot 1 /wake. Only this Bot 2 scheduler
        endpoint is public; owner actions and Bot 1 /api/cron keep their
        existing protections. The scanner still uses cross-instance locking
        plus a 40-second database throttle to prevent duplicate paper trades.
        """
        if not PAPER_ENABLED:
            return jsonify({"status": "disabled", "message":
                "Bot 2 paper mode is not enabled on this deployment"}), 503
        result = scan_once()
        status = result["status"]
        return jsonify({"ok": status == "ok", "scan_status": status,
                        "scanned": result.get("processed", 0),
                        "errors": result.get("errors", {}),
                        "check": "/api/bot2/state"}), (
                            200 if status == "ok"
                            else 202 if status in ("busy", "skipped")
                            else 503)

    @app.post("/api/bot2/position/<symbol>/close")
    def bot2_manual_close(symbol):
        same_origin_post()
        denied = require_owner()
        if denied is not None:
            return denied
        symbol = symbol.upper()
        if symbol not in COINS:
            return jsonify({"error": "Bot 2 coin not found"}), 404
        if not _runner.acquire(blocking=False):
            return jsonify({"error": "Bot 2 scanner active; retry shortly"}), 409
        connection = None
        try:
            if db_postgres:
                connection = engine.connect()
                if not connection.execute(text("SELECT pg_try_advisory_lock(:id)"),
                                          {"id": SCANNER_LOCK}).scalar():
                    return jsonify({"error": "Another Bot 2 scan is active"}), 409
            # Do not fabricate an exchange sell: bid-depth at request time.
            bids, _asks = _book(symbol)
            with Session.begin() as db:
                pos = db.get(B2Position, symbol)
                if pos is None:
                    return jsonify({"error": "No open Bot 2 position"}), 404
                exit_price = _sell_quote(bids, pos.qty)
                trade = _record_close(db, pos, exit_price, _now(), "MANUAL PAPER CLOSE")
                response = {"ok": True, "symbol": symbol,
                            "exit_price": _fmt(exit_price),
                            "net_pnl": _fmt(trade.net_pnl, 4)}
            return jsonify(response)
        except (ValueError, requests.RequestException) as exc:
            LOG.warning("Bot2 manual paper close unavailable: %s", exc)
            return jsonify({"error": "MEXC book unavailable; position unchanged"}), 503
        finally:
            if connection is not None:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:id)"),
                                       {"id": SCANNER_LOCK})
                finally:
                    connection.close()
            _runner.release()

    @app.get("/api/bot2/history")
    def bot2_history():
        """Full owner-independent history, same read-only behavior as Bot 1."""
        try:
            limit = max(1, min(int(request.args.get("limit", "100")), 500))
        except (TypeError, ValueError):
            limit = 100
        with Session() as db:
            trades = db.scalars(select(B2Closed).order_by(B2Closed.id.desc()).limit(limit)).all()
            return jsonify({"trades": [{
                "id": t.id, "symbol": t.symbol, "score": t.score,
                "side": "LONG", "mode": "NORMAL",
                "entry_ms": t.entry_ms, "exit_ms": t.exit_ms,
                "duration_ms": max(0, t.exit_ms - t.entry_ms),
                "entry": _fmt(t.entry_price), "exit": _fmt(t.exit_price),
                "stop": _fmt(t.initial_stop), "qty": _fmt(t.qty, 8),
                "capital_used": _fmt(t.margin, 2),
                "reason": t.exit_reason,
                "fees": _fmt(t.entry_fee + t.exit_fee, 4),
                "gross": _fmt(t.gross_pnl, 4),
                "entry_fee": _fmt(t.entry_fee, 4),
                "exit_fee": _fmt(t.exit_fee, 4),
                "net": _fmt(t.net_pnl, 4),
                "net_pct": _fmt(t.net_pnl / t.margin * 100, 2) if t.margin else None,
                "mfe_pct": _fmt(t.mfe_frac * 100, 2),
                "mae_pct": _fmt(t.mae_frac * 100, 2)
            } for t in trades]})

    @app.get("/api/bot2/equity")
    def bot2_equity():
        with Session() as db:
            points = db.scalars(select(B2Equity).order_by(B2Equity.id)).all()
            return jsonify({"points": [
                {"t": p.time_ms, "balance": _fmt(p.balance, 2)}
                for p in points]})

    @app.post("/api/bot2/reset")
    def bot2_reset():
        """Owner-authorized Bot 2 ONLY reset. No Bot 1 tables are modified."""
        same_origin_post()
        denial = require_owner()
        if denial is not None:
            return denial
        if len(os.environ.get("HKS_RESET_PASSWORD", "")) < 6:
            return jsonify({"error": "Reset password not configured"}), 503
        body = request.get_json(silent=True) or {}
        if body.get("confirm") != "RESET 1K":
            return jsonify({"error": "Type RESET 1K to confirm"}), 400
        allowed, error, code = check_reset_attempt(body.get("password", ""))
        if not allowed:
            return jsonify({"error": error}), code
        if not _runner.acquire(blocking=False):
            return jsonify({"error": "Bot 2 scanner busy; retry"}), 409
        connection = None
        try:
            if db_postgres:
                connection = engine.connect()
                if not connection.execute(text("SELECT pg_try_advisory_lock(:id)"),
                                          {"id": SCANNER_LOCK}).scalar():
                    return jsonify({"error": "Bot 2 scanner busy on another instance"}), 409
            with Session.begin() as db:
                db.execute(delete(B2Closed))
                db.execute(delete(B2Position))
                db.execute(delete(B2Equity))
                db.get(B2Wallet, 1).cash = START_BALANCE
                db.add(B2Equity(time_ms=_now(), balance=START_BALANCE))
                # Keep real 1m archive, scanner health and trade-score information.
                for symbol in COINS:
                    coin = db.get(B2Coin, symbol)
                    if coin and coin.signal in ("OPEN LONG PAPER", "TRAILING SL", "INITIAL SL"):
                        coin.signal = "WAIT"
            LOG.warning("Owner reset Bot 2 paper wallet only")
            return jsonify({"ok": True, "bot": 2})
        finally:
            if connection is not None:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:id)"),
                                       {"id": SCANNER_LOCK})
                finally:
                    connection.close()
            _runner.release()

    @app.get("/api/bot2/state")
    def bot2_state():
        tick = _now()
        with Session() as db:
            wallet = db.get(B2Wallet, 1)
            health = db.get(B2Health, 1)
            coins = [db.get(B2Coin, symbol) for symbol in COINS]
            positions = db.scalars(select(B2Position)).all()
            recent = db.scalars(select(B2Closed).order_by(B2Closed.id.desc()).limit(30)).all()
            count_wins = db.scalar(select(func.count()).select_from(B2Closed).where(B2Closed.net_pnl > ZERO)) or 0
            count_losses = db.scalar(select(func.count()).select_from(B2Closed).where(B2Closed.net_pnl <= ZERO)) or 0
            realized = START_BALANCE + (db.scalar(
                select(func.coalesce(func.sum(B2Closed.net_pnl), ZERO))) or ZERO)
            points = db.scalars(select(B2Equity).order_by(B2Equity.id.desc()).limit(150)).all()
            mark = {c.symbol: c.last_price for c in coins if c.last_price is not None}
            # Current spot value is the bid quote, not market mid.
            active = []
            cash = wallet.cash
            unreal = ZERO
            for p in positions:
                current = mark.get(p.symbol)
                value = current if current is not None else p.entry_price
                pnl = (value - p.entry_price) * p.qty
                cash += p.qty * value
                unreal += pnl
                active.append({"symbol": p.symbol, "direction": "LONG",
                    "entry": _fmt(p.entry_price), "stop": _fmt(p.stop),
                    "initial_stop": _fmt(p.initial_stop),
                    "qty": _fmt(p.qty), "notional": _fmt(p.margin, 2),
                    "pnl_gross": _fmt(pnl, 4), "score": p.score,
                    "mfe_pct": _fmt(p.mfe_frac * 100, 2),
                    "mae_pct": _fmt(p.mae_frac * 100, 2)})
            result_coins = [{"symbol": c.symbol, "price_bid": _fmt(c.last_price),
                "score": c.score, "trade_score": c.trade_score,
                "signal": c.signal, "updated": c.updated_ms,
                "quote_stale": not c.updated_ms or tick - c.updated_ms > 120_000,
                "error": c.error, "open": any(p.symbol == c.symbol for p in positions)}
                for c in coins]
            health_age = tick - health.last_success_ms if health.last_success_ms else None
            return jsonify({"bot": "BOT 2", "exchange": "MEXC Spot", "paper_enabled": PAPER_ENABLED,
                "coins": result_coins, "score_min": 85, "long_only": True,
                "initial_sl_multiplier": 2, "trailing": "ORIGINAL 100% ATR 2R",
                "tp": "UNCHANGED", "start_balance": "1000.00",
                "realized_balance": _fmt(realized, 2),
                "available_cash": _fmt(wallet.cash, 2), "equity": _fmt(cash, 2),
                "unrealized_gross": _fmt(unreal, 4),
                "open_positions": active, "wins": count_wins, "losses": count_losses,
                "recent": [{"id": t.id, "symbol": t.symbol,
                    "score": t.score, "entry": _fmt(t.entry_price),
                    "exit": _fmt(t.exit_price), "entry_ms": t.entry_ms,
                    "exit_ms": t.exit_ms, "stop": _fmt(t.initial_stop),
                    "reason": t.exit_reason, "pnl": _fmt(t.net_pnl, 4),
                    "fees": _fmt(t.entry_fee + t.exit_fee, 4)}
                    for t in recent],
                "equity_history": [{"t": x.time_ms, "balance": _fmt(x.balance, 2)}
                                   for x in reversed(points)],
                "scanner": {"status": ("DISABLED" if not PAPER_ENABLED else
                    "NOT STARTED" if not health.last_attempt_ms else
                    "OFFLINE" if health_age is not None and health_age > 180_000 else health.scan_status),
                    "last_attempt": health.last_attempt_ms,
                    "last_success": health.last_success_ms,
                    "last_duration_ms": health.last_duration_ms,
                    "processed": health.scan_count, "error": health.error},
                "assumptions": {"entry": "MEXC ask depth paper average; book liquidity gate",
                    "exit": "MEXC genuine completed 1m OHLC stop minus assumed slippage",
                    "fee_side_pct": _fmt(FEE_RATE * 100, 3),
                    "exit_slippage_pct": _fmt(EXIT_SLIPPAGE * 100, 3),
                    "trade_notional_usdt": _fmt(PAPER_NOTIONAL, 2),
                    "orders": "PAPER ONLY. No orders sent to MEXC."}})

    @app.get("/bot2")
    def bot2_page():
        return render_template("bot2.html",
                               reset_ready=len(os.environ.get("HKS_RESET_PASSWORD", "")) >= 6,
                               sqlite_mode=not db_postgres)

    app.extensions["hks_bot2"] = {
        "scan_once": scan_once, "enter": _enter, "scan_symbol": _scan_one,
        "process_position": _process_position, "models": {
            "wallet": B2Wallet, "coin": B2Coin, "position": B2Position,
            "trade": B2Closed, "bar": B2Bar, "health": B2Health},
        "config": {"coins": COINS, "min_score": 85, "paper_enabled": PAPER_ENABLED}}
