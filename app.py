"""HKS Pro Trader — stand-alone Vercel PAPER-ONLY signal/position dashboard.

Original SMC/ATR scoring source: examples/hks_legacy_smc_reverse.py
from HKS-Pro-Trader, pinned eac066e4... (2026-10-20).
This is a NEW lightweight paper implementation, NOT the original live financial
kernel. Read README before connecting a persistent wallet / deploying.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from zoneinfo import ZoneInfo

import requests
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, render_template_string, request
from sqlalchemy import (BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String,
                        Text, create_engine, delete, func, select, text)
from sqlalchemy.orm import declarative_base, sessionmaker
from bot1_parallel import (
    MODES as B1_MODES, ModeWallet, ModePosition, ModeTrade, ModeEquity,
    ModeExit, ModeDecision, bootstrap as b1_bootstrap,
    mode_positions as b1_mode_positions, realized_equity as b1_realized_equity,
    strategy_equity as b1_strategy_equity, open_pair as b1_open_pair,
    check_position as b1_check_position, close_position as b1_close_position,
    reset_parallel as b1_reset_parallel,
)

LOG = logging.getLogger("hks")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

D = Decimal
ZERO = D("0")
ONE = D("1")
START_BALANCE = D("1000")
# Explicitly gated until owner saves old-history screenshots and approves cutover.
BOT1_PARALLEL_ENABLED = os.getenv("HKS_BOT1_PARALLEL_ENABLED", "0").lower() in ("1", "true")
RISK_FRACTION = D("0.01")
MAX_POSITIONS = 5
# Conservative 1x collateral model. Never silently enable leverage.
MAX_POSITION_CASH_FRACTION = D("0.3333333333")
FEE_RATE = D(os.getenv("PAPER_FEE_RATE", "0.0004"))  # illustrated paper fee, NOT a quoted exchange fill
if not ZERO <= FEE_RATE < D("0.02"):
    raise RuntimeError("PAPER_FEE_RATE must be between 0 and 0.02")
SYMBOL_COUNT = max(1, min(100, int(os.getenv("HKS_SYMBOL_COUNT", "70"))))
# Default 70 dynamic coins as owner-approved; override via env if capacity requires.
CANDLE_BASE = os.getenv("BITGET_FUTURES_BASE", "https://api.bitget.com").rstrip("/")
_bitget_rate_lock = threading.Lock()
_bitget_next_time = 0.0
REQUEST_TIMEOUT = (4, 9)
SESSION_WINDOW = (("London", ZoneInfo("Europe/London"), 8, 16),
                  ("New York", ZoneInfo("America/New_York"), 8, 17))
# Stable-coin/fiat bases and synthetic/leveraged base tickers are excluded.
EXCLUDE_BASE = frozenset("USDT USDC FDUSD TUSD BUSD DAI USDD USDP PYUSD USD1 RLUSD FRAX LUSD EURC AEUR UST USTC USD EUR GBP BRL TRY JPY ARS BIDR IDRT NGN AUD ZAR VAI XAUT PAXG".split())
EXCLUDE_SUFFIX = ("DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,22}USDT$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192
# Public PAPER demo UI: no account login. Reset 1K and scanner cron each use private server-side secrets.
# Neither secret is shipped to HTML, committed to GitHub, or passed in a URL.

ON_VERCEL = os.getenv("VERCEL", "").lower() in ("1", "true")
raw_db = os.getenv("DATABASE_URL", "").strip()
if raw_db.startswith("postgres://"):
    raw_db = "postgresql+psycopg://" + raw_db.removeprefix("postgres://")
elif raw_db.startswith("postgresql://"):
    raw_db = "postgresql+psycopg://" + raw_db.removeprefix("postgresql://")
if not raw_db:
    raw_db = "sqlite:///hks_paper_demo.sqlite3"  # local development only; not durable on serverless
    if ON_VERCEL:
        raise RuntimeError("Persistent DATABASE_URL required in hosted deployment. Refusing ephemeral SQLite to preserve paper wallet/trades.")
    LOG.warning("Local SQLite fallback is for development only; hosted Vercel requires DATABASE_URL.")
DB_POSTGRES = raw_db.startswith("postgresql+")
engine = create_engine(raw_db, pool_pre_ping=True, future=True,
                       connect_args={} if DB_POSTGRES else {"timeout": 30, "check_same_thread": False})
Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()
NUM = Numeric(30, 12)


class Wallet(Base):
    __tablename__ = "hks_wallet"
    id = Column(Integer, primary_key=True)
    cash = Column(NUM, nullable=False)


class GlobalMode(Base):
    """One shared saved default; bulk switching resets all per-coin choices."""
    __tablename__ = "hks_global_mode"
    id = Column(Integer, primary_key=True)
    mode = Column(String(8), nullable=False, default="NORMAL")


class Coin(Base):
    __tablename__ = "hks_coin"
    symbol = Column(String(26), primary_key=True)
    mode = Column(String(8), nullable=False, default="NORMAL")
    score = Column(Integer, nullable=False, default=0)  # DISPLAY score, independent of trade eligibility
    trade_score = Column(Integer, nullable=False, default=0)
    last_price = Column(NUM)
    daily_open = Column(NUM)
    daily_date = Column(String(10))
    last_bar_end = Column(BigInteger)
    last_decision_end = Column(BigInteger)
    last_exit_15m_end = Column(BigInteger)
    signal = Column(String(16), nullable=False, default="WAIT")
    updated_ms = Column(BigInteger)
    error = Column(String(255))


class Position(Base):
    __tablename__ = "hks_position"
    symbol = Column(String(26), primary_key=True)
    direction = Column(String(8), nullable=False)
    mode = Column(String(8), nullable=False)
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


class ClosedTrade(Base):
    __tablename__ = "hks_closed_trade"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(26), nullable=False)
    direction = Column(String(8), nullable=False)
    mode = Column(String(8), nullable=False)
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


class EquityPoint(Base):
    __tablename__ = "hks_equity_point"
    id = Column(Integer, primary_key=True, autoincrement=True)
    time_ms = Column(BigInteger, nullable=False)
    balance = Column(NUM, nullable=False)  # closed-trade realized equity, not locked available cash
    trade_id = Column(Integer, ForeignKey("hks_closed_trade.id"), nullable=True)


class ResetGuard(Base):
    """Persistent rate limit across serverless instances for Reset 1K guesses."""
    __tablename__ = "hks_reset_guard"
    id = Column(Integer, primary_key=True)
    window_start_ms = Column(BigInteger, nullable=False, default=0)
    failed_attempts = Column(Integer, nullable=False, default=0)
    lock_until_ms = Column(BigInteger, nullable=False, default=0)


class OwnerSession(Base):
    """Revocable persistent owner login; only a SHA-256 token digest is stored."""
    __tablename__ = "hks_owner_session"
    token_hash = Column(String(64), primary_key=True)
    created_ms = Column(BigInteger, nullable=False)


class QuoteHealth(Base):
    """Independent market-price feed health; never changes trading decisions."""
    __tablename__ = "hks_quote_health"
    id = Column(Integer, primary_key=True)
    last_success_ms = Column(BigInteger)
    last_attempt_ms = Column(BigInteger)
    source = Column(String(24))
    last_error = Column(String(300))
    consecutive_failures = Column(Integer, nullable=False, default=0)


class CronHealth(Base):
    """Persist evidence of actual cron-request trade processing (not just wake HTTP 200)."""
    __tablename__ = "hks_cron_health"
    id = Column(Integer, primary_key=True)
    last_request_ms = Column(BigInteger)
    last_finish_ms = Column(BigInteger)
    last_scan_status = Column(String(24))
    last_scan_count = Column(Integer, nullable=False, default=0)
    last_scan_error_count = Column(Integer, nullable=False, default=0)
    last_duration_ms = Column(BigInteger)
    last_error = Column(String(512))


class BotState(Base):
    __tablename__ = "hks_bot_state"
    id = Column(Integer, primary_key=True)
    last_attempt_ms = Column(BigInteger)
    last_success_ms = Column(BigInteger)
    last_error = Column(String(512))
    last_symbol_count = Column(Integer, nullable=False, default=0)
    last_error_count = Column(Integer, nullable=False, default=0)
    last_market_refresh_ms = Column(BigInteger)
    market_symbols = Column(Text, nullable=False, default="")


Base.metadata.create_all(engine)

# Older draft versions used 32-bit INTEGER for Unix millisecond timestamps.
# Convert only known HKS timestamp columns to BIGINT on an existing PostgreSQL
# demo schema, without touching any financial rows or unrelated tables.
if DB_POSTGRES:
    allowed_timestamp_fields = {
        "hks_coin": {"last_bar_end", "last_decision_end", "last_exit_15m_end", "updated_ms"},
        "hks_position": {"entry_ms"},
        "hks_closed_trade": {"entry_ms", "exit_ms"},
        "hks_equity_point": {"time_ms"},
        "hks_reset_guard": {"window_start_ms", "lock_until_ms"},
        "hks_bot_state": {"last_attempt_ms", "last_success_ms", "last_market_refresh_ms"},
    }
    with engine.begin() as cn:
        old_ints = cn.execute(text("""SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND data_type = 'integer'
              AND table_name LIKE 'hks_%'""")).all()
        for table_name, column_name in old_ints:
            if column_name in allowed_timestamp_fields.get(table_name, set()):
                cn.execute(text(f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" TYPE BIGINT'))

with Session.begin() as db:
    if db.get(Wallet, 1) is None:
        db.add(Wallet(id=1, cash=START_BALANCE))
        db.add(EquityPoint(time_ms=int(time.time() * 1000), balance=START_BALANCE))
    if db.get(BotState, 1) is None:
        db.add(BotState(id=1, market_symbols=""))
    if db.get(ResetGuard, 1) is None:
        db.add(ResetGuard(id=1, window_start_ms=0, failed_attempts=0, lock_until_ms=0))
    # Upgrade existing data without overriding any existing per-coin choices.
    if db.get(GlobalMode, 1) is None:
        db.add(GlobalMode(id=1, mode="NORMAL"))
    if db.get(QuoteHealth, 1) is None:
        db.add(QuoteHealth(id=1, consecutive_failures=0))
    if db.get(CronHealth, 1) is None:
        db.add(CronHealth(id=1, last_scan_status="NOT STARTED"))

# Isolated b1_* tables are never initialized unless the feature is enabled.
# No legacy financial rows are modified by initialization.
if BOT1_PARALLEL_ENABLED:
    b1_bootstrap(engine, Session, int(time.time() * 1000))


class PriceError(Exception):
    pass


def utc_ms():
    return int(time.time() * 1000)


def api(path, **params):
    """Normalize Bitget v3 USDT-FUTURES market data to HKS's existing formats."""
    global _bitget_next_time
    if path in ("ticker/24hr", "ticker/price"):
        endpoint = "tickers"
        route = "/api/v3/market/tickers"
        args = {"category": "USDT-FUTURES"}
    elif path == "klines":
        endpoint = "candles"
        interval = params.get("interval")
        if interval == "1d":
            # Unlike Bitget's v3 1D, the classic 1Dutc granularity explicitly
            # opens each daily candle at 00:00 UTC, as HKS expects.
            route = "/api/v2/mix/market/candles"
            args = {"symbol": params["symbol"], "productType": "USDT-FUTURES",
                    "granularity": "1Dutc", "limit": str(params["limit"])}
        else:
            mapped = {"1m": "1m", "15m": "15m", "1h": "1H"}.get(interval)
            if not mapped:
                raise PriceError("Unsupported candle interval")
            route = "/api/v3/market/candles"
            args = {"category": "USDT-FUTURES", "symbol": params["symbol"],
                    "interval": mapped, "limit": str(params["limit"])}
    else:
        raise PriceError("Unsupported market endpoint")
    # Below provider limit of 20 requests per second per IP, within one instance.
    with _bitget_rate_lock:
        now = time.monotonic()
        if now < _bitget_next_time:
            time.sleep(_bitget_next_time - now)
        _bitget_next_time = time.monotonic() + 0.08
    try:
        response = requests.get(f"{CANDLE_BASE}{route}",
                                params=args, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": "HKS-Paper-Demo/1"})
        response.raise_for_status()
        payload = response.json()
        if (not isinstance(payload, dict) or payload.get("code") != "00000"
                or not isinstance(payload.get("data"), list)):
            raise PriceError(f"Bitget {endpoint} returned an invalid API response")
        data = payload["data"]
        if path == "ticker/24hr":
            return [{"symbol": item["symbol"], "lastPrice": item["lastPrice"],
                     "quoteVolume": item["turnover24h"]} for item in data]
        if path == "ticker/price":
            return [{"symbol": item["symbol"], "price": item["lastPrice"]} for item in data]
        # Bitget rows are timestamp/open/high/low/close/volume/turnover.
        return sorted(data, key=lambda row: int(row[0]))
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "unknown"
        raise PriceError(f"Bitget USDT Futures {endpoint} returned HTTP {code}") from exc
    except (ValueError, KeyError, TypeError, IndexError, requests.RequestException) as exc:
        raise PriceError(f"Bitget USDT Futures {endpoint} unavailable or malformed ({type(exc).__name__})") from exc


def num(value):
    x = D(str(value))
    if not x.is_finite():
        raise PriceError("Non-finite market value")
    return x


def fmt(value, places=8):
    if value is None:
        return None
    return float(round(num(value), places))


def market_tickers():
    raw = api("ticker/24hr")
    if not isinstance(raw, list):
        raise PriceError("Unexpected 24h ticker format")
    result = {}
    for obj in raw:
        symbol = str(obj.get("symbol", ""))
        if not SYMBOL_RE.fullmatch(symbol):
            continue
        base = symbol[:-4]
        if base in EXCLUDE_BASE or base.endswith(EXCLUDE_SUFFIX):
            continue
        try:
            last = num(obj["lastPrice"])
            volume = num(obj["quoteVolume"])
            if last > ZERO and volume > ZERO:
                result[symbol] = {"price": last, "volume": volume}
        except (KeyError, ArithmeticError, ValueError, PriceError):
            continue
    if not result:
        raise PriceError("No valid Bitget USDT Futures tickers")
    return result


def market_prices():
    """Single Bitget USDT Futures bulk-price snapshot, never synthesized from stale prices.

    Separate from SMC candle evaluation: 2-second price updates must not
    trigger extra entries or partial-candle trade decisions.
    """
    raw = api("ticker/price")
    if not isinstance(raw, list):
        raise PriceError("Unexpected bulk price format")
    result = {}
    for item in raw:
        symbol = str(item.get("symbol", ""))
        if not SYMBOL_RE.fullmatch(symbol):
            continue
        try:
            price = num(item["price"])
            if price > ZERO:
                result[symbol] = price
        except (KeyError, ValueError, ArithmeticError, PriceError):
            continue
    if not result:
        raise PriceError("No valid USD-M bulk prices")
    return result


def record_quote_failure(exc):
    """Persistent diagnostics across Vercel function invocations; never affects wallet."""
    try:
        with Session.begin() as db:
            h = db.get(QuoteHealth, 1)
            if h is not None:
                h.last_attempt_ms = utc_ms()
                h.consecutive_failures = (h.consecutive_failures or 0) + 1
                h.last_error = str(exc)[:300]
    except Exception:
        LOG.exception("Quote diagnostic persistence unavailable")


def refresh_live_prices():
    """Update saved quotes for the selected 50 and existing open paper trades.

    Uses one aggregate network request, regardless of coin count. A quote
    tick never alters a position, realized funds, trade score or signals.
    """
    with Session() as db:
        st = db.get(BotState, 1)
        symbols = set(st.market_symbols.split(",")) if st.market_symbols else set()
        symbols.discard("")
        symbols.update(db.scalars(select(Position.symbol)).all())
    if not symbols:
        return 0  # Deep scan publishes the Top 50 before quote stream starts.
    # Both quote paths use the same public Bitget tickers endpoint.
    # Never invent prices if the exchange data is unavailable.
    source = "ticker/price"
    try:
        latest = market_prices()
    except PriceError as first_error:
        source = "ticker/24hr"
        try:
            latest = {symbol: row["price"] for symbol, row in market_tickers().items()}
        except PriceError as backup_error:
            raise PriceError(f"Primary bulk quotes failed ({first_error}); 24h fallback failed ({backup_error})") from backup_error
    tick = utc_ms()
    updated = 0
    with Session.begin() as db:
        # The strategy scanner updates the SAME hks_coin records. Never let
        # independent function invocations / two-second quote threads write those
        # rows concurrently: PostgreSQL row-order inversions caused 40P01
        # deadlocks and a misleading DELAYED / ERRORS scanner status.
        # Missing one ephemeral quote tick is safer than delaying a trade.
        if not coin_write_lock(db, nonblocking=True):
            return 0
        for symbol in sorted(symbols):
            price = latest.get(symbol)
            if price is None:
                continue
            coin = db.get(Coin, symbol)
            if coin is not None:
                coin.last_price = price
                coin.updated_ms = tick
                updated += 1
        if updated:
            h = db.get(QuoteHealth, 1)
            if h is not None:
                h.last_attempt_ms = tick
                h.last_success_ms = tick
                h.last_error = None
                h.source = source
                h.consecutive_failures = 0
    return updated


def session_bonus(close_ms):
    instant = datetime.fromtimestamp(close_ms / 1000, tz=timezone.utc)
    active = []
    for name, zone, start, end in SESSION_WINDOW:
        local = instant.astimezone(zone)
        if start <= local.hour < end and local.weekday() < 5:
            active.append(name)
    # London/NY overlap still gets ONE +10 bonus.
    return (10 if active else 0), "+".join(active) or "None"


def candles(symbol, interval, limit, now_ms):
    raw = api("klines", symbol=symbol, interval=interval, limit=limit)
    if not isinstance(raw, list):
        raise PriceError("Invalid kline response")
    step = {"1m": 60000, "15m": 900000, "1h": 3600000, "1d": 86400000}[interval]
    result = []
    for item in raw:
        open_ms = int(item[0])
        if open_ms + step > now_ms:
            continue  # completed bars ONLY
        lo, hi, op, cl = num(item[3]), num(item[2]), num(item[1]), num(item[4])
        if min(op, cl, lo) <= 0 or hi < max(op, cl, lo):
            raise PriceError("Invalid OHLC bar")
        result.append({"t": open_ms, "end": open_ms + step,
                       "o": op, "h": hi, "l": lo, "c": cl})
    if any(b["t"] != a["end"] for a, b in zip(result, result[1:])):
        raise PriceError("Historical bar gaps")
    return result


def daily_open(symbol, date_utc, now_ms):
    # Today's 1d bar is intentionally INCOMPLETE; open is immutable from day start.
    raw = api("klines", symbol=symbol, interval="1d", limit=2)
    start = int(datetime.fromisoformat(date_utc).replace(tzinfo=timezone.utc).timestamp() * 1000)
    for item in raw:
        if int(item[0]) == start:
            price = num(item[1])
            if price > ZERO:
                return price
    raise PriceError("UTC daily open not available")


def evaluate_smc(bars, hourly, close_ms):
    """Faithful entry scoring from owner's pinned Python, with explicitly changed sessions.

    Display-only scoring when no sweep: 10 for established HTF context and 10
    for active London/NY session. These alone NEVER authorize a trade.
    """
    if len(bars) < 26 or len(hourly) < 21:
        raise PriceError("15m/1h warmup insufficient")
    b = bars[-1]
    if b["end"] != close_ms:
        raise PriceError("15m decision candle stale")
    if hourly[-1]["end"] > close_ms:
        raise PriceError("Future 1h candle detected")
    swing_high = max(c["h"] for c in bars[-25:-5])
    swing_low = min(c["l"] for c in bars[-25:-5])
    bull_sweep = b["l"] < swing_low and b["c"] > swing_low
    bear_sweep = b["h"] > swing_high and b["c"] < swing_high
    bonus, sess = session_bonus(close_ms)
    sma21 = sum((c["c"] for c in hourly[-21:]), ZERO) / D(21)
    htf_bias = "LONG" if hourly[-1]["c"] > sma21 else "SHORT"
    # No sweep -> original strategy has no candidate direction. For the UI ONLY,
    # compare 15m close versus 15m SMA21 to completed 1h bias. No entry uses it.
    local_sma21 = sum((c["c"] for c in bars[-21:]), ZERO) / D(21)
    local_bias = "LONG" if b["c"] > local_sma21 else "SHORT"
    display = (10 if local_bias == htf_bias else 0) + bonus
    if not (bull_sweep or bear_sweep):
        return {"display": display, "trade_score": 0, "original": None,
                "stop_fraction": None, "session": sess, "htf": htf_bias}
    original = "LONG" if bull_sweep else "SHORT"  # dual-sweep LONG precedence
    bull_mss = any(x["c"] > swing_high for x in bars[-4:-1])
    bear_mss = any(x["c"] < swing_low for x in bars[-4:-1])
    bull_fvg = b["l"] > bars[-3]["h"]
    bear_fvg = b["h"] < bars[-3]["l"]
    score = 35
    if (bull_sweep and bull_mss) or (bear_sweep and bear_mss):
        score += 30
    if (bull_sweep and bull_fvg) or (bear_sweep and bear_fvg):
        score += 15
    if original == htf_bias:
        score += 10
    score += bonus
    atr = sum((max(bars[i]["h"] - bars[i]["l"],
                   abs(bars[i]["h"] - bars[i - 1]["c"]),
                   abs(bars[i]["l"] - bars[i - 1]["c"]))
               for i in range(len(bars) - 14, len(bars))), ZERO) / D(14)
    stop_fraction = max(D("0.008"), min(D("0.03"), atr / b["c"] * D("1.5")))
    return {"display": score, "trade_score": score, "original": original,
            "stop_fraction": stop_fraction, "session": sess, "htf": htf_bias}


def mark_excursion(pos, bar):
    """1m OHLC price excursion estimate. Intrabar order of high/low is unknown."""
    if pos.direction == "LONG":
        favor = (bar["h"] - pos.entry_price) / pos.entry_price
        adverse = (pos.entry_price - bar["l"]) / pos.entry_price
    else:
        favor = (pos.entry_price - bar["l"]) / pos.entry_price
        adverse = (bar["h"] - pos.entry_price) / pos.entry_price
    pos.mfe_frac = max(pos.mfe_frac, favor, ZERO)
    pos.mae_frac = max(pos.mae_frac, adverse, ZERO)


def get_stop_fill(pos, bar):
    if pos.direction == "LONG" and bar["l"] <= pos.stop:
        return min(pos.stop, bar["o"])  # adverse opening gap, if any
    if pos.direction == "SHORT" and bar["h"] >= pos.stop:
        return max(pos.stop, bar["o"])
    return None


def close_position(db, pos, fill, fill_ms, reason):
    w = db.get(Wallet, 1)
    signed = ONE if pos.direction == "LONG" else -ONE
    gross = signed * (fill - pos.entry_price) * pos.qty
    exit_fee = abs(fill * pos.qty) * FEE_RATE
    net = gross - pos.entry_fee - exit_fee
    w.cash = w.cash + pos.margin + gross - exit_fee
    trade = ClosedTrade(symbol=pos.symbol, direction=pos.direction, mode=pos.mode,
                        original_signal=pos.original_signal, score=pos.score,
                        entry_ms=pos.entry_ms, exit_ms=fill_ms,
                        entry_price=pos.entry_price, exit_price=fill,
                        qty=pos.qty, initial_stop=pos.initial_stop,
                        exit_reason=reason, entry_fee=pos.entry_fee,
                        exit_fee=exit_fee, gross_pnl=gross, net_pnl=net,
                        mfe_frac=pos.mfe_frac, mae_frac=pos.mae_frac)
    db.add(trade)
    db.flush()
    # Realized-equity curve: baseline $1k plus cumulative CLOSED-trade NET results.
    realized = START_BALANCE + (db.execute(select(func.coalesce(func.sum(ClosedTrade.net_pnl), 0))).scalar_one() or ZERO)
    db.add(EquityPoint(time_ms=fill_ms, balance=realized, trade_id=trade.id))
    coin = db.get(Coin, pos.symbol)
    if coin:
        coin.last_exit_15m_end = ((fill_ms + 899999) // 900000) * 900000
    db.delete(pos)
    return trade


def trail_stop(pos, favorable_price):
    """Tighten SL using a favorable price touch and the virtual 2R reference.

    Progress 40% -> locked progress 10%; 80% -> 70%; above 80%,
    maintain a 10-percentage-point gap. Between 40 and 80 use linear
    interpolation. Stop never loosens and does not represent a TP exit.
    """
    distance = pos.reference_distance
    if distance <= ZERO:
        return False
    sign = ONE if pos.direction == "LONG" else -ONE
    progress = sign * (favorable_price - pos.entry_price) / distance * 100
    if progress < D(40):
        return False
    if progress <= D(80):
        locked = D(10) + (progress - D(40)) * D("1.5")
    else:
        locked = progress - D(10)
    proposed = (pos.entry_price + sign * distance * locked / 100).quantize(
        D("0.000000000000000001"), rounding=ROUND_HALF_EVEN)
    next_stop = max(pos.stop, proposed) if pos.direction == "LONG" else min(pos.stop, proposed)
    if next_stop == pos.stop:
        return False
    pos.stop = next_stop
    return True


def check_position(db, pos, minute_bars):
    """Process each completed 1m bar chronologically for stops AND trailing.

    Always test the stop that was in force before that bar first. If not
    stopped, a favorable HIGH (long) or LOW (short) crossing a threshold
    tightens the stop, effective from the next processed 1m bar. A completed
    OHLC candle cannot tell whether its high or low happened first; therefore
    NEVER backdate a fill using the newly tightened stop in that same bar.
    This is once-per-minute paper modeling, not instantaneous tick execution.
    """
    for bar in minute_bars:
        if bar["end"] <= pos.entry_ms:
            continue  # no fills or trailing before entry
        if bar["t"] < pos.entry_ms < bar["end"]:
            # Intraminute entry: pre-entry high/low cannot be attributed.
            continue
        mark_excursion(pos, bar)
        stop_fill = get_stop_fill(pos, bar)
        if stop_fill is not None:
            trade = close_position(db, pos, stop_fill, bar["end"],
                                   "TRAILING SL HIT" if pos.stop != pos.initial_stop else "INITIAL SL HIT")
            db.flush()
            return trade
        favorable = bar["h"] if pos.direction == "LONG" else bar["l"]
        trail_stop(pos, favorable)
    return None


def account_equity(db, prices):
    wallet = db.get(Wallet, 1)
    total = wallet.cash
    upnl = ZERO
    for p in db.scalars(select(Position)).all():
        mark = prices.get(p.symbol, p.entry_price)
        signed = ONE if p.direction == "LONG" else -ONE
        unrealized = signed * (mark - p.entry_price) * p.qty
        total += p.margin + unrealized
        upnl += unrealized
    return total, upnl


def open_position(db, coin, original, score, stop_fraction, quote, now_ms):
    if db.get(Position, coin.symbol) is not None:
        return None
    if db.scalar(select(func.count()).select_from(Position)) >= MAX_POSITIONS:
        return None
    w = db.get(Wallet, 1)
    prices = {p.symbol: p.entry_price for p in db.scalars(select(Position)).all()}
    equity, _ = account_equity(db, prices)
    side = original if coin.mode == "NORMAL" else ("SHORT" if original == "LONG" else "LONG")
    target_risk = max(equity, ZERO) * RISK_FRACTION
    if quote <= ZERO or stop_fraction <= ZERO or w.cash <= ZERO:
        return None
    # Explicit conservative synthetic 1x paper futures collateral model.
    notional = min(target_risk / stop_fraction,
                   w.cash * MAX_POSITION_CASH_FRACTION / (ONE + FEE_RATE))
    if notional <= D("5"):
        return None
    qty = notional / quote
    margin = notional
    fee = notional * FEE_RATE
    if w.cash < margin + fee:
        return None
    initial_stop = quote * (ONE - stop_fraction if side == "LONG" else ONE + stop_fraction)
    pos = Position(symbol=coin.symbol, direction=side, mode=coin.mode,
                   original_signal=original, score=score, entry_ms=now_ms,
                   entry_price=quote, qty=qty, stop=initial_stop,
                   initial_stop=initial_stop, margin=margin, entry_fee=fee,
                   mfe_frac=ZERO, mae_frac=ZERO,
                   reference_distance=abs(quote - initial_stop) * 2)
    w.cash -= (margin + fee)
    db.add(pos)
    coin.signal = f"OPEN {side}"
    return pos


def init_coin(db, symbol):
    coin = db.get(Coin, symbol)
    if coin is None:
        defaults = db.get(GlobalMode, 1)
        coin = Coin(symbol=symbol, mode=(defaults.mode if defaults else "NORMAL"),
                    score=0, trade_score=0, signal="WAIT")
        db.add(coin)
    return coin


def fetch_symbol(symbol, now_ms, needs_decision, needs_daily):
    minute = candles(symbol, "1m", 200, now_ms)
    if not minute:
        raise PriceError("No completed 1m bar")
    data = {"symbol": symbol, "minute": minute}
    if needs_decision and minute[-1]["end"] % 900000 == 0:
        data["quarter"] = candles(symbol, "15m", 35, now_ms)
        data["hour"] = candles(symbol, "1h", 25, now_ms)
    if needs_daily:
        today = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date().isoformat()
        data["daily"] = daily_open(symbol, today, now_ms)
    return data


_runner_mutex = threading.Lock()  # local SQLite dev mode only; use Postgres in production
REFRESH_MARKETS_MS = 60 * 60 * 1000
ADVISORY_LOCK_ID = 47002161
# A separate transaction-scoped, cross-worker lock for ALL hks_coin writes.
# Unlike the scanner-wide advisory lock, this is held only during short DB
# write transactions. The price loop uses TRY-lock and skips busy quote ticks.
COIN_WRITE_LOCK_ID = 47002162


def coin_write_lock(db, *, nonblocking=False):
    """Serialize coin writes across quote thread, scanner and UI actions.

    Transaction-scoped so Postgres releases it automatically on commit or
    rollback; no network I/O may happen after acquiring it. SQLite dev mode
    has no Postgres advisory locks and is unchanged.
    """
    if not DB_POSTGRES:
        return True
    if nonblocking:
        return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"),
                               {"key": COIN_WRITE_LOCK_ID}).scalar())
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
               {"key": COIN_WRITE_LOCK_ID})
    return True


def acquire_pg_lock():
    conn = engine.connect()
    locked = conn.execute(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": ADVISORY_LOCK_ID}).scalar()
    if not locked:
        conn.close()
        return None
    return conn


def release_pg_lock(conn):
    if conn is not None:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": ADVISORY_LOCK_ID})
        finally:
            conn.close()


def scan_once():
    """One protected, idempotent scan shared by automatic loop and external cron."""
    if not _runner_mutex.acquire(blocking=False):
        return {"status": "busy", "message": "Another local scan active"}
    pg_lock = None
    try:
        if DB_POSTGRES:
            pg_lock = acquire_pg_lock()
            if pg_lock is None:
                return {"status": "busy", "message": "Another instance scanning"}
        now_ms = utc_ms()
        with Session.begin() as db:
            status = db.get(BotState, 1)
            if status.last_attempt_ms and now_ms - status.last_attempt_ms < 40_000:
                return {"status": "skipped", "message": "This minute was already scanned"}
            status.last_attempt_ms = now_ms
            previous = status.market_symbols.split(",") if status.market_symbols else []
            refresh = not previous or not status.last_market_refresh_ms or now_ms - status.last_market_refresh_ms > REFRESH_MARKETS_MS
            known = {c.symbol: c for c in db.scalars(select(Coin)).all()}
            holdings = ({p.symbol for p in db.scalars(select(ModePosition)).all()}
                        if BOT1_PARALLEL_ENABLED else
                        {p.symbol for p in db.scalars(select(Position)).all()})
        tickers = market_tickers()
        if refresh:
            top = [s for s, _ in sorted(tickers.items(), key=lambda x: x[1]["volume"], reverse=True)[:SYMBOL_COUNT]]
            # Drop delisted symbols, but retain open positions in scan scheduling.
        else:
            top = [x for x in previous if x in tickers]
            if len(top) < SYMBOL_COUNT:
                top.extend(x for x, _ in sorted(tickers.items(), key=lambda x: x[1]["volume"], reverse=True)
                           if x not in top)  # truncated below
            top = top[:SYMBOL_COUNT]
        # Publish the selected coin list and prices with one write transaction.
        # Prefetch once: db.get() for 70 new symbols would issue 70 remote SQL
        # round trips on Aiven even though all coins have just been selected.
        with Session.begin() as db:
            coin_write_lock(db)
            state = db.get(BotState, 1)
            state.market_symbols = ",".join(top)
            if refresh:
                state.last_market_refresh_ms = now_ms
            cached_coins = {row.symbol: row for row in db.scalars(select(Coin)).all()}
            saved_global = db.get(GlobalMode, 1)
            initial_mode = saved_global.mode if saved_global else "NORMAL"
            for symbol in top:
                coin = cached_coins.get(symbol)
                if coin is None:
                    coin = Coin(symbol=symbol, mode=initial_mode, score=0,
                                trade_score=0, signal="WAIT")
                    db.add(coin)
                    cached_coins[symbol] = coin
                coin.last_price = tickers[symbol]["price"]
        symbols = list(dict.fromkeys(top + sorted(holdings)))
        utc_day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date().isoformat()
        need = {s: (known.get(s) is None or known[s].daily_date != utc_day) for s in symbols}
        # Each REST request happens outside the DB write transaction.
        gathered, errors = {}, {}
        # Most calls are network-bound. Parallel fetch limits the time the
        # external cron request must stay alive (cron-job.org free: 30 seconds).
        # This is a performance setting, NOT a trading-strategy change.
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(fetch_symbol, symbol, now_ms, True, need[symbol]): symbol
                       for symbol in symbols}
            for fut in as_completed(futures):
                symbol = futures[fut]
                try:
                    gathered[symbol] = fut.result()
                except Exception as exc:
                    errors[symbol] = str(exc)[:200]
        # Apply completed market data in ONE SQL transaction for the normal
        # successful path. Aiven free tier showed ~1.37s per transaction.
        # Per-coin commits took ~150s for 70 coins despite ~23s API warmup.
        # Keep DB network I/O outside the market-data parallel fetch.
        #
        # On any unexpected batch exception, the entire transaction rolls
        # back and the ORIGINAL isolated per-symbol path below retries,
        # preserving its failure isolation and wallet/SL accounting.
        processed = 0
        try:
            with Session.begin() as db:
                coin_write_lock(db)
                db_coins = {c.symbol: c for c in db.scalars(select(Coin)).all()}
                db_positions = ({(p.mode, p.symbol): p for p in db.scalars(select(ModePosition)).all()}
                                if BOT1_PARALLEL_ENABLED else
                                {p.symbol: p for p in db.scalars(select(Position)).all()})
                saved_global = db.get(GlobalMode, 1)
                default_mode = saved_global.mode if saved_global else "NORMAL"
                for symbol in symbols:
                    coin = db_coins.get(symbol)
                    if coin is None:
                        coin = Coin(symbol=symbol, mode=default_mode, score=0,
                                    trade_score=0, signal="WAIT")
                        db.add(coin)
                        db_coins[symbol] = coin
                    if symbol not in gathered:
                        coin.error = errors.get(symbol, "missing market data")
                        continue

                    data = gathered[symbol]
                    coin.error = None
                    if symbol in tickers:
                        coin.last_price = tickers[symbol]["price"]
                    if "daily" in data:
                        coin.daily_open = data["daily"]
                        coin.daily_date = utc_day

                    bars = data["minute"]
                    last_bar = bars[-1]
                    old_end = coin.last_bar_end
                    if old_end and last_bar["end"] - old_end > 199 * 60_000:
                        if (any(p.symbol == symbol for p in db_positions.values())
                                if BOT1_PARALLEL_ENABLED else symbol in db_positions):
                            coin.error = "SCANNER GAP >199m with OPEN POSITION: manual review required; trading paused"
                            coin.signal = "PAUSED"
                            errors[symbol] = coin.error
                            continue
                        old_end = None
                        coin.last_bar_end = None
                        coin.last_decision_end = None
                    future_bars = [b for b in bars if not old_end or b["end"] > old_end]
                    if old_end and future_bars and future_bars[0]["t"] != old_end:
                        raise PriceError("1m history gap: position unchanged")

                    trail_moved = False
                    if BOT1_PARALLEL_ENABLED:
                        for mode in B1_MODES:
                            pos = db_positions.get((mode, symbol))
                            if pos is not None and future_bars:
                                old_stop = pos.stop
                                closed = b1_check_position(
                                    db, pos, future_bars, FEE_RATE,
                                    mark_excursion, get_stop_fill, trail_stop)
                                if closed is not None:
                                    db_positions.pop((mode, symbol), None)
                                else:
                                    trail_moved |= pos.stop != old_stop
                    else:
                        pos = db_positions.get(symbol)
                        if pos is not None and future_bars:
                            prior_stop = pos.stop
                            closed = check_position(db, pos, future_bars)
                            if closed is not None:
                                db_positions.pop(symbol, None)
                            else:
                                trail_moved = pos.stop != prior_stop

                    coin.last_bar_end = last_bar["end"]
                    coin.updated_ms = now_ms
                    if (last_bar["end"] % 900000 == 0 and "quarter" in data
                            and "hour" in data and coin.last_decision_end != last_bar["end"]):
                        evaluation = evaluate_smc(data["quarter"], data["hour"], last_bar["end"])
                        coin.score = evaluation["display"]
                        coin.trade_score = evaluation["trade_score"]
                        coin.signal = "WATCH" if evaluation["original"] else "NO SWEEP"
                        coin.last_decision_end = last_bar["end"]
                        if BOT1_PARALLEL_ENABLED:
                            if (symbol in top and evaluation["original"]
                                    and evaluation["trade_score"] >= 75):
                                quote = tickers[symbol]["price"] if symbol in tickers else last_bar["c"]
                                paired = b1_open_pair(
                                    db, coin, dict(evaluation, end_ms=last_bar["end"]),
                                    quote, now_ms, FEE_RATE, RISK_FRACTION,
                                    MAX_POSITION_CASH_FRACTION, MAX_POSITIONS)
                                for mode, (new_pos, status) in paired.items():
                                    if new_pos is not None:
                                        db_positions[(mode, symbol)] = new_pos
                                    LOG.info("Bot1 %s %s %s: %s", symbol, mode,
                                             evaluation["original"], status)
                                coin.signal = "PAIR " + evaluation["original"]
                        else:
                            pos = db_positions.get(symbol)
                            if (pos is None and symbol in top and evaluation["original"]
                                    and evaluation["trade_score"] >= 75
                                    and coin.last_exit_15m_end != last_bar["end"]):
                                quote = tickers[symbol]["price"] if symbol in tickers else last_bar["c"]
                                opened = open_position(db, coin, evaluation["original"],
                                                       evaluation["trade_score"],
                                                       evaluation["stop_fraction"], quote, now_ms)
                                if opened:
                                    db_positions[symbol] = opened
                                    LOG.info("Paper entry %s / %s / %s", symbol, coin.mode, coin.signal)
                    if trail_moved:
                        coin.signal = "TRAILING"
                    processed += 1
        except Exception:
            LOG.exception("Batch scan processing failed: rollback complete; using original isolated per-symbol fallback")
            processed = 0
            for symbol in symbols:
                if symbol not in gathered:
                    with Session.begin() as db:
                        coin_write_lock(db)
                        c = init_coin(db, symbol)
                        c.error = errors.get(symbol, "missing market data")
                    continue
                data = gathered[symbol]
                try:
                    with Session.begin() as db:
                        coin_write_lock(db)
                        coin = init_coin(db, symbol)
                        coin.error = None
                        if symbol in tickers:
                            coin.last_price = tickers[symbol]["price"]
                        if "daily" in data:
                            coin.daily_open = data["daily"]
                            coin.daily_date = utc_day
                        bars = data["minute"]
                        last_bar = bars[-1]
                        old_end = coin.last_bar_end
                        # Never fabricate missing history when a scanner was offline >200 minutes.
                        if old_end and last_bar["end"] - old_end > 199 * 60_000:
                            if (db.scalar(select(ModePosition.symbol).where(ModePosition.symbol == symbol).limit(1))
                                    if BOT1_PARALLEL_ENABLED else db.get(Position, symbol)) is not None:
                                coin.error = "SCANNER GAP >199m with OPEN POSITION: manual review required; trading paused"
                                coin.signal = "PAUSED"
                                errors[symbol] = coin.error
                                continue
                            # Safe resync if and ONLY IF no paper position exists.
                            # Do not create stale historical entries for missed 15m periods.
                            old_end = None
                            coin.last_bar_end = None
                            coin.last_decision_end = None
                        future_bars = [b for b in bars if not old_end or b["end"] > old_end]
                        if old_end and future_bars and future_bars[0]["t"] != old_end:
                            raise PriceError("1m history gap: position unchanged")
                        trail_moved = False
                        if BOT1_PARALLEL_ENABLED:
                            for mode in B1_MODES:
                                pos = db.get(ModePosition, (mode, symbol))
                                if pos is not None and future_bars:
                                    old_stop = pos.stop
                                    closed = b1_check_position(
                                        db, pos, future_bars, FEE_RATE,
                                        mark_excursion, get_stop_fill, trail_stop)
                                    trail_moved |= (closed is None and pos.stop != old_stop)
                        else:
                            pos = db.get(Position, symbol)
                            if pos is not None and future_bars:
                                prior_stop = pos.stop
                                check_position(db, pos, future_bars)
                                trail_moved = (db.get(Position, symbol) is not None and pos.stop != prior_stop)
                        coin.last_bar_end = last_bar["end"]
                        coin.updated_ms = now_ms
                        if last_bar["end"] % 900000 == 0 and "quarter" in data and "hour" in data and coin.last_decision_end != last_bar["end"]:
                            evaluation = evaluate_smc(data["quarter"], data["hour"], last_bar["end"])
                            coin.score = evaluation["display"]
                            coin.trade_score = evaluation["trade_score"]
                            coin.signal = "WATCH" if evaluation["original"] else "NO SWEEP"
                            coin.last_decision_end = last_bar["end"]
                            if BOT1_PARALLEL_ENABLED:
                                if symbol in top and evaluation["original"] and evaluation["trade_score"] >= 75:
                                    quote = tickers[symbol]["price"] if symbol in tickers else last_bar["c"]
                                    paired = b1_open_pair(
                                        db, coin, dict(evaluation, end_ms=last_bar["end"]),
                                        quote, now_ms, FEE_RATE, RISK_FRACTION,
                                        MAX_POSITION_CASH_FRACTION, MAX_POSITIONS)
                                    coin.signal = "PAIR " + evaluation["original"]
                            else:
                                pos = db.get(Position, symbol)
                                if (pos is None and symbol in top and evaluation["original"]
                                    and evaluation["trade_score"] >= 75
                                    and coin.last_exit_15m_end != last_bar["end"]):
                                    quote = tickers[symbol]["price"] if symbol in tickers else last_bar["c"]
                                    if open_position(db, coin, evaluation["original"],
                                                     evaluation["trade_score"],
                                                     evaluation["stop_fraction"], quote, now_ms):
                                        LOG.info("Paper entry %s / %s / %s", symbol, coin.mode, coin.signal)
                        if trail_moved:
                            coin.signal = "TRAILING"
                    processed += 1
                except Exception as exc:
                    errors[symbol] = str(exc)[:200]
                    LOG.exception("Scanner symbol %s failed", symbol)
                    with Session.begin() as db:
                        coin_write_lock(db)
                        init_coin(db, symbol).error = errors[symbol]
        with Session.begin() as db:
            st = db.get(BotState, 1)
            st.last_symbol_count = processed
            st.last_error_count = len(errors)
            st.last_error = "; ".join(f"{k}:{v}" for k, v in list(errors.items())[:2])[:512] if errors else None
            st.market_symbols = ",".join(top)
            if refresh:
                st.last_market_refresh_ms = now_ms
            if not errors and processed == len(symbols):
                st.last_success_ms = utc_ms()
        return {"status": "ok" if not errors else "partial", "scanned": processed,
                "dynamic_coins": len(top), "errors": errors}
    except Exception as exc:
        LOG.exception("Scanner failed")
        with Session.begin() as db:
            st = db.get(BotState, 1)
            st.last_error = str(exc)[:512]
            st.last_error_count = max(st.last_error_count, 1)
        return {"status": "error", "reason": str(exc)[:200]}
    finally:
        release_pg_lock(pg_lock)
        _runner_mutex.release()


# Serverless functions may be suspended between requests; an external cron /wake call can
# restart it. Both background loops are best-effort while the server is alive.
# Quotes refresh every ~2 seconds using ONE market-wide endpoint request.
# Heavy 1m candle accounting / 15m SMC decisions remain minute-boundary only.
# Running full 50-coin historical candle scans every 2 seconds would generate
# excessive exchange calls and would not change completed-candle signals.
_LIVE_QUOTE_INTERVAL_SECONDS = 2.0
_AUTOSCAN_INTERVAL_SECONDS = 2.0  # check for new completed minute, not full scan
_autoscan_start_lock = threading.Lock()
_autoscan_thread = None
_live_quote_thread = None


def cron_controls_scanning(now_ms=None):
    """Prefer the durable external scheduler when it is actively checking in.

    This prevents browser/status/healthcheck-launched auto workers from
    racing the HTTP /wake scan on different instances. In the absence
    of a cron heartbeat for >150 seconds, automatic scanning still works on
    a live instance.  NO wallet, order or strategy data are modified here.
    """
    if now_ms is None:
        now_ms = utc_ms()
    try:
        with Session() as db:
            row = db.get(CronHealth, 1)
            last = row.last_request_ms if row else None
            return bool(last and 0 <= now_ms - last <= 150_000)
    except Exception:
        LOG.exception("Cron heartbeat check failed (scanner DB lock remains active)")
        return False


def _automatic_scan_loop():
    previous_minute = None
    while True:
        minute = int(time.time() // 60)
        if minute != previous_minute:
            previous_minute = minute
            try:
                if cron_controls_scanning():
                    LOG.info("Skipping background scan this minute: /wake Cron is active")
                else:
                    result = scan_once()
                    LOG.info("Completed-candle background scan: %s", result.get("status", "unknown"))
            except Exception:
                LOG.exception("Completed-candle scanner failed; retry next minute")
        time.sleep(_AUTOSCAN_INTERVAL_SECONDS)


def _live_quote_loop():
    # Slow or unavailable market data must never be represented as live.
    # Advance the next tick from the previous attempt, preventing a tight
    # retry loop when the exchange/API is down.
    while True:
        begun = time.monotonic()
        try:
            refresh_live_prices()
        except Exception as exc:
            LOG.warning("Live-price refresh unavailable: %s", str(exc)[:180])
            record_quote_failure(exc)
        time.sleep(max(0.1, _LIVE_QUOTE_INTERVAL_SECONDS - (time.monotonic() - begun)))


def _ensure_automatic_scanner():
    global _autoscan_thread, _live_quote_thread
    with _autoscan_start_lock:
        if _autoscan_thread is None or not _autoscan_thread.is_alive():
            _autoscan_thread = threading.Thread(
                target=_automatic_scan_loop, name="hks-completed-candle-scan", daemon=True)
            _autoscan_thread.start()
        if _live_quote_thread is None or not _live_quote_thread.is_alive():
            _live_quote_thread = threading.Thread(
                target=_live_quote_loop, name="hks-2second-quotes", daemon=True)
            _live_quote_thread.start()


@app.before_request
def _start_scanner_on_visit():
    # Invalid/unauthenticated cron probes should not launch new scanner loops.
    # A normal dashboard visit starts scanning immediately without a cron hit.
    # /wake now performs a direct, request-bound scan so it does NOT depend on
    # daemon threads surviving serverless suspension. Avoid racing a
    # newly spawned background scan against its own cron request.
    if ON_VERCEL:
        # Serverless requests cannot guarantee persistent worker threads. The
        # request-bound /wake endpoint performs background 1m scanning.
        # While the UI is open, its regular /api/state polling refreshes
        # latest quotes synchronously without relying on process-local threads.
        if request.path == "/api/state":
            try:
                refresh_live_prices()
            except Exception as exc:
                LOG.warning("Serverless live quotes unavailable: %s", str(exc)[:180])
                record_quote_failure(exc)
        return
    if request.path not in ("/api/cron", "/wake"):
        _ensure_automatic_scanner()


# On a persistent local process, dashboard HTTP reads persisted prices; on Vercel,
# /api/state refreshes quotes on demand while the browser is open.
# External /wake remains responsible for closed-minute scan/trading.


def view_trade(t):
    # In this 1x paper model, original invested capital equals entry notional.
    # Deriving it from persisted entry/qty also works for legacy closed trades.
    capital = t.entry_price * t.qty
    net_pct = (t.net_pnl / capital * 100) if capital > ZERO else None
    # Old "STOP" rows never recorded whether trailing was active; do not guess.
    reason = "STOP (LEGACY / UNCLASSIFIED)" if t.exit_reason == "STOP" else t.exit_reason
    return {"id": t.id, "symbol": t.symbol, "side": t.direction, "mode": t.mode,
            "original_signal": t.original_signal, "score": t.score,
            "entry_ms": t.entry_ms, "exit_ms": t.exit_ms,
            "entry": fmt(t.entry_price), "exit": fmt(t.exit_price),
            "qty": fmt(t.qty), "capital_used": fmt(capital, 4),
            "net_pct": fmt(net_pct, 3), "duration_ms": max(0, t.exit_ms - t.entry_ms),
            "stop": fmt(t.initial_stop), "reason": reason,
            "gross": fmt(t.gross_pnl, 4), "entry_fee": fmt(t.entry_fee, 5),
            "exit_fee": fmt(t.exit_fee, 5), "fees": fmt(t.entry_fee + t.exit_fee, 5),
            "net": fmt(t.net_pnl, 4), "mfe_pct": fmt(t.mfe_frac * 100, 3),
            "mae_pct": fmt(t.mae_frac * 100, 3),
            "mfe_usd": fmt(t.mfe_frac * t.entry_price * t.qty, 3),
            "mae_usd": fmt(t.mae_frac * t.entry_price * t.qty, 3)}


def same_origin_post():
    """Reject browser cross-site form/fetch posts; not intended as API authentication."""
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    source = origin or referer
    parsed = urlsplit(source) if source else None
    if not parsed or parsed.netloc.lower() != request.host.lower() or parsed.scheme not in ("http", "https"):
        abort(403)


def reset_password_ok(submitted):
    """Use only HKS_RESET_PASSWORD. Never log or return submitted value."""
    expected = os.environ.get("HKS_RESET_PASSWORD", "")
    return len(expected) >= 6 and hmac.compare_digest(str(submitted), expected)


def check_reset_attempt(submitted):
    """Return (allowed, failure_message, http_status). Five misses lock 15 minutes."""
    now = utc_ms()
    correct = reset_password_ok(submitted)
    with Session.begin() as db:
        guard = db.execute(select(ResetGuard).where(ResetGuard.id == 1).with_for_update()).scalar_one()
        if now < guard.lock_until_ms:
            return False, "Too many reset attempts. Try again later.", 429
        if not guard.window_start_ms or now - guard.window_start_ms >= 15 * 60_000:
            guard.window_start_ms = now
            guard.failed_attempts = 0
        if not correct:
            guard.failed_attempts += 1
            if guard.failed_attempts >= 5:
                guard.lock_until_ms = now + 15 * 60_000
            return False, "Incorrect reset password", 403
        guard.failed_attempts = 0
        guard.window_start_ms = now
        guard.lock_until_ms = 0
    return True, None, 200


@app.after_request
def safe_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp



# Owner session is deliberately independent of Reset 1K confirmation.
# The same existing private password authenticates once, and stays server-side.
OWNER_COOKIE = "hks_owner"
OWNER_COOKIE_AGE = 400 * 24 * 60 * 60  # Rolling browser max-age; extended on site re-open.


def owner_logged_in():
    token = request.cookies.get(OWNER_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
        return False
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with Session() as db:
        return db.get(OwnerSession, token_hash) is not None


def require_owner():
    if not owner_logged_in():
        return jsonify({"error": "Owner Login required. Please unlock the dashboard first."}), 401
    return None


def set_owner_cookie(response, token):
    response.set_cookie(OWNER_COOKIE, token, max_age=OWNER_COOKIE_AGE,
                        httponly=True, secure=(ON_VERCEL or request.is_secure),
                        samesite="Strict", path="/")
    return response


@app.post("/api/owner/login")
def owner_login():
    same_origin_post()
    if len(os.environ.get("HKS_RESET_PASSWORD", "")) < 6:
        return jsonify({"error": "Owner password is not configured"}), 503
    submitted = (request.get_json(silent=True) or {}).get("password", "")
    allowed, error, code = check_reset_attempt(submitted)
    if not allowed:
        return jsonify({"error": error}), code
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with Session.begin() as db:
        db.add(OwnerSession(token_hash=digest, created_ms=utc_ms()))
    return set_owner_cookie(jsonify({"ok": True, "owner": True}), token)


@app.post("/api/owner/logout")
def owner_logout():
    same_origin_post()
    token = request.cookies.get(OWNER_COOKIE, "")
    if re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
        with Session.begin() as db:
            record = db.get(OwnerSession, hashlib.sha256(token.encode("ascii")).hexdigest())
            if record is not None:
                db.delete(record)
    response = jsonify({"ok": True, "owner": False})
    response.delete_cookie(OWNER_COOKIE, path="/", secure=(ON_VERCEL or request.is_secure), samesite="Strict", httponly=True)
    return response


@app.get("/api/owner/status")
def owner_status():
    logged = owner_logged_in()
    response = jsonify({"owner": logged})
    # Rolling cookie persists across restarts and browser reopenings until Logout,
    # subject to browser cookie expiry/clearing and owner-password rotation policy.
    if logged:
        set_owner_cookie(response, request.cookies[OWNER_COOKIE])
    return response


@app.get("/")
def page():
    return render_template_string(DASHBOARD_HTML, reset_ready=len(os.environ.get("HKS_RESET_PASSWORD", "")) >= 6,
                                  fee_rate=str(FEE_RATE), sqlite_mode=not DB_POSTGRES,
                                  parallel_enabled=BOT1_PARALLEL_ENABLED)


@app.post("/api/mode/all")
def set_global_mode():
    """Atomically set the default and every known coin for NEW entries only.

    Existing positions and closed trades are not modified; newly discovered
    symbols inherit the saved default until a coin-specific override is chosen.
    """
    same_origin_post()
    denial = require_owner()
    if denial is not None:
        return denial
    if BOT1_PARALLEL_ENABLED:
        return jsonify({"error": "Both modes run in parallel; global switching disabled"}), 409
    obj = request.get_json(silent=True) or {}
    mode = str(obj.get("mode", "")).upper()
    if mode not in {"NORMAL", "REVERSE"}:
        return jsonify({"error": "Mode must be NORMAL or REVERSE"}), 400
    if obj.get("confirm") != "ALL COINS":
        return jsonify({"error": "Confirm global change with ALL COINS"}), 400
    with Session.begin() as db:
        coin_write_lock(db)
        settings = db.get(GlobalMode, 1)
        if settings is None:
            settings = GlobalMode(id=1, mode=mode)
            db.add(settings)
        else:
            settings.mode = mode
        # The same transaction resets prior per-coin overrides; nothing touches
        # open positions, their entry mode or the original trading rule.
        changed = db.query(Coin).update({Coin.mode: mode}, synchronize_session=False)
    return jsonify({"ok": True, "global_mode": mode, "coins_updated": changed,
                    "affects": "new entries only"})


@app.post("/api/mode/<symbol>")
def set_mode(symbol):
    same_origin_post()
    denial = require_owner()
    if denial is not None:
        return denial
    if BOT1_PARALLEL_ENABLED:
        return jsonify({"error": "Both directions are always active"}), 409
    if not SYMBOL_RE.fullmatch(symbol):
        abort(400)
    mode = str((request.get_json(silent=True) or {}).get("mode", "")).upper()
    if mode not in {"NORMAL", "REVERSE"}:
        abort(400)
    with Session.begin() as db:
        coin_write_lock(db)
        c = init_coin(db, symbol)
        c.mode = mode
    # An existing open position retains its ENTRY mode; future trades use new mode.
    return jsonify({"ok": True, "symbol": symbol, "mode": mode})


@app.post("/api/reset")
def reset_wallet():
    same_origin_post()
    denial = require_owner()
    if denial is not None:
        return denial
    if len(os.environ.get("HKS_RESET_PASSWORD", "")) < 6:
        return jsonify({"error": "Reset disabled until HKS_RESET_PASSWORD is configured in Vercel Environment Variables"}), 503
    obj = request.get_json(silent=True) or {}
    confirm_text = "RESET BOTH" if BOT1_PARALLEL_ENABLED else "RESET 1K"
    if obj.get("confirm") != confirm_text:
        return jsonify({"error": "Type " + confirm_text + " to confirm"}), 400
    allowed, error, status = check_reset_attempt(obj.get("password", ""))
    if not allowed:
        return jsonify({"error": error}), status
    if not _runner_mutex.acquire(blocking=False):
        return jsonify({"error": "Scanner running; retry after scan"}), 409
    pg_lock = None
    try:
        if DB_POSTGRES:
            pg_lock = acquire_pg_lock()
            if pg_lock is None:
                return jsonify({"error": "Scanner running on another instance"}), 409
        with Session.begin() as db:
            coin_write_lock(db)
            if BOT1_PARALLEL_ENABLED:
                b1_reset_parallel(db, utc_ms())
            db.execute(delete(EquityPoint))
            db.execute(delete(ClosedTrade))
            db.execute(delete(Position))
            # Account reset must NOT erase market score, candle/SMC state,
            # dynamic coin selection, scanner health, or user-selected modes.
            # Only obsolete position indicators need clearing after positions vanish.
            db.query(Coin).filter(
                (Coin.signal.like("OPEN%")) | (Coin.signal == "TRAILING")
            ).update({Coin.signal: "WAIT"}, synchronize_session=False)
            db.get(Wallet, 1).cash = START_BALANCE
            db.add(EquityPoint(time_ms=utc_ms(), balance=START_BALANCE))
        LOG.warning("Owner manually reset complete paper account to $1000")
        return jsonify({"ok": True})
    finally:
        release_pg_lock(pg_lock)
        _runner_mutex.release()


@app.post("/api/position/<symbol>/close")
def manual_close_position(symbol):
    """Owner-confirmed, fresh-quote PAPER close of an existing position only.

    Reuses the existing private Reset password AND its persistent attempt guard,
    rather than adding an unprotected action to the public dashboard. No
    Binance orders are placed. The scanner-wide lock serializes close/scan.
    """
    same_origin_post()
    denial = require_owner()
    if denial is not None:
        return denial
    if not SYMBOL_RE.fullmatch(symbol):
        abort(400)
    mode = str((request.get_json(silent=True) or {}).get("mode", "NORMAL")).upper()
    if BOT1_PARALLEL_ENABLED and mode not in B1_MODES:
        return jsonify({"error": "Mode must be NORMAL or REVERSE"}), 400
    if not _runner_mutex.acquire(blocking=False):
        return jsonify({"error": "Scanner busy; retry after current scan"}), 409
    pg_lock = None
    try:
        if DB_POSTGRES:
            pg_lock = acquire_pg_lock()
            if pg_lock is None:
                return jsonify({"error": "Scanner active on another instance; retry shortly"}), 409
        with Session() as db:
            if (db.get(ModePosition, (mode, symbol)) if BOT1_PARALLEL_ENABLED else db.get(Position, symbol)) is None:
                return jsonify({"error": "This position is no longer open"}), 409
        # Retrieve a fresh, real exchange quote. Cached dashboard prices are
        # intentionally NOT used to create a potentially stale paper fill.
        try:
            try:
                latest = market_prices()
                source = "ticker/price"
            except PriceError:
                latest = {s: row["price"] for s, row in market_tickers().items()}
                source = "ticker/24hr"
            fill = latest.get(symbol)
            if fill is None or fill <= ZERO:
                raise PriceError("No fresh valid quote for this position")
        except PriceError as exc:
            return jsonify({"error": f"Manual close not executed: {exc}"}), 503
        closed_at = utc_ms()
        with Session.begin() as db:
            coin_write_lock(db)
            pos = (db.get(ModePosition, (mode, symbol)) if BOT1_PARALLEL_ENABLED else db.get(Position, symbol))
            if pos is None:
                return jsonify({"error": "Position already closed; no change made"}), 409
            # Include this confirmed mark in the directional excursion estimates.
            mark_excursion(pos, {"h": fill, "l": fill})
            trade = (b1_close_position(db, pos, fill, closed_at, "MANUAL CLOSE", FEE_RATE)
                     if BOT1_PARALLEL_ENABLED else close_position(db, pos, fill, closed_at, "MANUAL CLOSE"))
            trade_id = trade.id
            net = fmt(trade.net_pnl, 4)
        LOG.info("Owner closed paper position %s manually; trade id %s", symbol, trade_id)
        return jsonify({"ok": True, "symbol": symbol, "mode": mode, "trade_id": trade_id,
                        "reason": "MANUAL CLOSE", "exit_price": fmt(fill),
                        "net_pnl": net, "price_source": source})
    finally:
        release_pg_lock(pg_lock)
        _runner_mutex.release()


def require_cron_token():
    """Only external cron with X-Cron-Key may start the scanner.

    A missing/short secret fails CLOSED, and no token is accepted in a query URL.
    Never expose this server-side secret in dashboard JavaScript.
    """
    expected = os.environ.get("HKS_CRON_TOKEN", "")
    if len(expected) < 24:
        return jsonify({"error": "Cron disabled until HKS_CRON_TOKEN is configured"}), 503
    supplied = request.headers.get("X-Cron-Key", "")
    if not hmac.compare_digest(supplied, expected):
        return jsonify({"error": "Unauthorized cron request"}), 403
    return None


@app.get("/api/cron")
def cron():
    denied = require_cron_token()
    if denied is not None:
        return denied
    answer = scan_once()
    return jsonify(answer), 200 if answer["status"] in {"ok", "partial", "busy", "skipped"} else 503


@app.get("/api/state")
def state():
    now = utc_ms()
    mode = str(request.args.get("mode", "NORMAL")).upper()
    if BOT1_PARALLEL_ENABLED and mode not in B1_MODES:
        return jsonify({"error": "Unknown mode"}), 400
    with Session() as db:
        st = db.get(BotState, 1)
        # No network I/O in dashboard polling. Prices are saved by scan_once.
        # A scanner error/stoppage marks quotes stale without fabricating values.
        # Quote freshness is independent of the once-per-minute strategy scanner.
        # Do not label cached snapshots live after the quote thread stops.
        stale = True
        quotes = {}
        wallet = (db.get(ModeWallet, mode) if BOT1_PARALLEL_ENABLED else db.get(Wallet, 1))
        dynamic = [x for x in st.market_symbols.split(",") if x][:SYMBOL_COUNT]
        coins = {c.symbol: c for c in db.scalars(select(Coin)).all()}
        positions = (b1_mode_positions(db, mode) if BOT1_PARALLEL_ENABLED else db.scalars(select(Position)).all())
        feed = db.get(QuoteHealth, 1)
        cron_health = db.get(CronHealth, 1)
        # An actual successful quote-stream write, NOT a slower 1m candle scan,
        # is required to claim live 2-second pricing.
        last_quote_ms = feed.last_success_ms if feed else None
        quote_age_s = (now - last_quote_ms) / 1000 if last_quote_ms else None
        stale = quote_age_s is None or quote_age_s > 10
        prices = {p.symbol: coins[p.symbol].last_price
                  for p in positions if p.symbol in coins and coins[p.symbol].last_price is not None}
        equity, unreal = (b1_strategy_equity(db, mode, prices) if BOT1_PARALLEL_ENABLED else account_equity(db, prices))
        outcome = []
        for symbol in dynamic:
            c = coins.get(symbol)
            px = quotes[symbol]["price"] if symbol in quotes else (c.last_price if c else None)
            daily = c.daily_open if c else None
            today = datetime.fromtimestamp(now / 1000, timezone.utc).date().isoformat()
            pct = ((px / daily) - ONE) * 100 if px and daily and daily > ZERO and c.daily_date == today else None
            outcome.append({"symbol": symbol, "mode": "BOTH" if BOT1_PARALLEL_ENABLED else (c.mode if c else "NORMAL"),
                            "price": fmt(px), "change": fmt(pct, 3),
                            "score": c.score if c else 0,
                            "trade_score": c.trade_score if c else 0,
                            "signal": c.signal if c else "WAIT",
                            "updated": c.updated_ms if c else None,
                            "error": c.error if c else None,
                            "open": any(p.symbol == symbol for p in positions)})
        trades = (db.scalars(select(ModeTrade).where(ModeTrade.mode == mode).order_by(ModeTrade.id.desc()).limit(10)).all()
                  if BOT1_PARALLEL_ENABLED else db.scalars(select(ClosedTrade).order_by(ClosedTrade.id.desc()).limit(10)).all())
        win_count = ((db.scalar(select(func.count()).select_from(ModeTrade).where(ModeTrade.mode == mode, ModeTrade.net_pnl > ZERO)) or 0)
                     if BOT1_PARALLEL_ENABLED else (db.scalar(select(func.count()).select_from(ClosedTrade).where(ClosedTrade.net_pnl > ZERO)) or 0))
        loss_count = ((db.scalar(select(func.count()).select_from(ModeTrade).where(ModeTrade.mode == mode, ModeTrade.net_pnl < ZERO)) or 0)
                     if BOT1_PARALLEL_ENABLED else (db.scalar(select(func.count()).select_from(ClosedTrade).where(ClosedTrade.net_pnl < ZERO)) or 0))
        flat_count = ((db.scalar(select(func.count()).select_from(ModeTrade).where(ModeTrade.mode == mode, ModeTrade.net_pnl == ZERO)) or 0)
                     if BOT1_PARALLEL_ENABLED else (db.scalar(select(func.count()).select_from(ClosedTrade).where(ClosedTrade.net_pnl == ZERO)) or 0))
        points = (db.scalars(select(ModeEquity).where(ModeEquity.mode == mode).order_by(ModeEquity.id.desc()).limit(350)).all()
                  if BOT1_PARALLEL_ENABLED else db.scalars(select(EquityPoint).order_by(EquityPoint.id.desc()).limit(350)).all())
        running_age = (now - st.last_success_ms) // 1000 if st.last_success_ms else None
        if running_age is None:
            if st.last_attempt_ms is None:
                health = "NOT STARTED"
            elif st.last_error_count or st.last_error:
                health = "DELAYED / ERRORS"
            elif now - st.last_attempt_ms <= 120_000:
                health = "STARTING"
            else:
                health = "OFFLINE"
        elif running_age > 180:
            health = "OFFLINE"
        elif running_age > 100 or st.last_error_count:
            health = "DELAYED / ERRORS"
        else:
            health = "RUNNING"
        open_list = []
        for p in positions:
            current = prices.get(p.symbol, p.entry_price)
            upnl = (current - p.entry_price) * p.qty * (ONE if p.direction == "LONG" else -ONE)
            open_list.append({"symbol": p.symbol, "side": p.direction, "mode": p.mode,
                              "entry": fmt(p.entry_price), "stop": fmt(p.stop),
                              "qty": fmt(p.qty), "capital_used": fmt(p.margin, 4),
                              "pnl": fmt(upnl, 4), "score": p.score,
                              "mfe_pct": fmt(p.mfe_frac * 100, 2),
                              "mae_pct": fmt(p.mae_frac * 100, 2)})
        realized = (b1_realized_equity(db, mode) if BOT1_PARALLEL_ENABLED else
                    START_BALANCE + (db.scalar(select(func.coalesce(func.sum(ClosedTrade.net_pnl), 0))) or ZERO))
        mode_summaries = {}
        mode_equity_points = {}
        if BOT1_PARALLEL_ENABLED:
            for m in B1_MODES:
                w = db.get(ModeWallet, m)
                m_pos = b1_mode_positions(db, m)
                m_prices = {p.symbol: coins[p.symbol].last_price for p in m_pos
                            if p.symbol in coins and coins[p.symbol].last_price is not None}
                m_equity, m_upnl = b1_strategy_equity(db, m, m_prices)
                m_points = db.scalars(select(ModeEquity).where(ModeEquity.mode == m)
                              .order_by(ModeEquity.id.desc()).limit(350)).all()
                mode_equity_points[m] = [{"t": q.time_ms, "balance": fmt(q.balance, 4)}
                                          for q in reversed(m_points)]
                mode_summaries[m] = {
                    "balance": fmt(b1_realized_equity(db, m), 4),
                    "equity": fmt(m_equity, 4),
                    "available_cash": fmt(w.cash, 4),
                    "unrealized": fmt(m_upnl, 4),
                    "open": len(m_pos),
                }

        saved_global = db.get(GlobalMode, 1)
        return jsonify({"now": now, "parallel": BOT1_PARALLEL_ENABLED,
                        "view_mode": mode, "mode_summaries": mode_summaries,
                        "mode_equity_points": mode_equity_points,
                        "global_mode": "BOTH" if BOT1_PARALLEL_ENABLED else (saved_global.mode if saved_global else "NORMAL"), "max_positions": MAX_POSITIONS, "market_stale": stale,
                        "quotes_age_s": round(quote_age_s, 1) if quote_age_s is not None else None,
                        "quote_target_s": 2, "strategy_timeframe": "15m",
                        "quote_feed": {"source": feed.source if feed else None,
                                       "last_success": last_quote_ms,
                                       "last_attempt": feed.last_attempt_ms if feed else None,
                                       "last_error": feed.last_error if feed else None,
                                       "consecutive_failures": feed.consecutive_failures if feed else 0},
                        "persisted_db": DB_POSTGRES,
                        "coin_count": len(outcome), "coins": outcome,
                        "balance": fmt(realized, 4), "available_cash": fmt(wallet.cash, 4),
                        "equity": fmt(equity, 4), "unrealized": fmt(unreal, 4),
                        "wins": win_count, "losses": loss_count, "flats": flat_count,
                        "open_positions": open_list,
                        "recent": [view_trade(t) for t in trades],
                        "equity_points": [{"t": p.time_ms, "balance": fmt(p.balance, 4)} for p in reversed(points)],
                        "cron_execution": ({"last_request": cron_health.last_request_ms,
                                            "last_finished": cron_health.last_finish_ms,
                                            "result": cron_health.last_scan_status,
                                            "scanned": cron_health.last_scan_count,
                                            "errors": cron_health.last_scan_error_count,
                                            "duration_ms": cron_health.last_duration_ms,
                                            "last_error": cron_health.last_error}
                                           if cron_health else None),
                        "scanner": {"status": health, "age_s": running_age,
                                    "last_success": st.last_success_ms,
                                    "last_attempt": st.last_attempt_ms,
                                    "last_error": st.last_error,
                                    "errors": st.last_error_count,
                                    "processed": st.last_symbol_count},
                        "fee_rate": fmt(FEE_RATE)})


@app.get("/api/equity")
def equity_history():
    """Full recorded closed-trade equity history for the optional All view.
    Only persisted hks_equity_point balances are exposed; no interpolated data.
    """
    with Session() as db:
        mode = str(request.args.get("mode", "NORMAL")).upper()
        if BOT1_PARALLEL_ENABLED and mode not in B1_MODES:
            return jsonify({"error": "Unknown mode"}), 400
        points = (db.scalars(select(ModeEquity).where(ModeEquity.mode == mode)
                  .order_by(ModeEquity.id.asc())).all()
                  if BOT1_PARALLEL_ENABLED else
                  db.scalars(select(EquityPoint).order_by(EquityPoint.id.asc())).all())
        return jsonify({"points": [{"t": p.time_ms, "balance": fmt(p.balance, 4)}
                                   for p in points]})


@app.get("/api/history")
def history():
    try:
        limit = max(1, min(500, int(request.args.get("limit", "100"))))
    except ValueError:
        abort(400)
    with Session() as db:
        mode = str(request.args.get("mode", "NORMAL")).upper()
        if BOT1_PARALLEL_ENABLED and mode not in B1_MODES:
            return jsonify({"error": "Unknown mode"}), 400
        trades = (db.scalars(select(ModeTrade).where(ModeTrade.mode == mode)
                  .order_by(ModeTrade.id.desc()).limit(limit)).all()
                  if BOT1_PARALLEL_ENABLED else
                  db.scalars(select(ClosedTrade).order_by(ClosedTrade.id.desc()).limit(limit)).all())
        return jsonify({"trades": [view_trade(t) for t in trades]})


@app.get("/healthz")
def healthz():
    # Lightweight liveness and keep-awake ping. Before-request automatically
    # starts the scanner loop only on a non-serverless local worker.
    # This is not a direct trade command and needs no secret/header.
    with Session() as db:
        db.execute(select(Wallet.id).limit(1)).first()
    return jsonify({"http": "ok", "scanner": "asynchronous; see /api/state"})


@app.get("/wake")
def wake():
    """External cron performs a real scanner pass IN THIS HTTP REQUEST.

    This differs from an async keepalive: a reported `ok` means scan_once()
    returned after processing completed candles / stops / potential entries.
    Browser-open background loops remain as a convenience, NOT the only
    mechanism for trading when the browser is closed.

    Cron-job.org free limits requests to 30s; a slow/full scan may time out.
    Do not claim 24/7 or every-minute execution without deployed evidence.
    Cross-instance PG advisory locks and per-minute DB throttle in scan_once()
    guard double execution when /wake and browser loops overlap.
    """
    started = utc_ms()
    # Never write the cron's private header to logs or responses.
    with Session.begin() as db:
        h = db.get(CronHealth, 1)
        h.last_request_ms = started
    try:
        result = scan_once()
    except Exception as exc:
        LOG.exception("Request-bound cron scan failed")
        result = {"status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}
    status = result.get("status", "error")
    count = int(result.get("scanned", 0))
    errors = result.get("errors") or {}
    error_count = len(errors) if isinstance(errors, dict) else (1 if status == "error" else 0)
    finished = utc_ms()
    with Session.begin() as db:
        h = db.get(CronHealth, 1)
        h.last_finish_ms = finished
        h.last_scan_status = status.upper()
        h.last_scan_count = count
        h.last_scan_error_count = error_count
        h.last_duration_ms = finished - started
        h.last_error = str(result.get("reason") or "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:2]))[:512] if status in ("error", "partial") else None
    # busy/skipped are not proof of a completed trade-processing pass;
    # successful/partial statuses are distinguishable in response + /api/state.
    http = 200 if status == "ok" else (202 if status in ("busy", "skipped") else 503)
    return jsonify({"ok": status == "ok", "scan_status": status,
                    "scanned": count, "errors": error_count,
                    "duration_ms": finished-started,
                    "check": "/api/state"}), http


# Dashboard HTML is imported at file end and kept in app.py for paste-only deployment.

DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#101423"><title>HKS Pro Trader | Paper Engine</title>
<link rel="icon" type="image/svg+xml" sizes="any" href="/static/hks-favicon.svg">
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Arial,sans-serif;color-scheme:dark;--bg:#090d19;--panel:#12192b;--panel2:#1a2338;--line:#2a3550;--text:#f4f7ff;--muted:#94a3bb;--green:#45dda5;--red:#ff6d8f;--gold:#f8c976;--blue:#789cff;--shadow:0 18px 60px #0004}
body.light{color-scheme:light;--bg:#edf2f9;--panel:#fff;--panel2:#f5f7fc;--line:#dce4f1;--text:#182338;--muted:#64748b;--green:#067951;--red:#d62850;--gold:#a76a05;--blue:#335dd5;--shadow:0 18px 50px #30436016}
*{box-sizing:border-box}body{background:var(--bg);color:var(--text);margin:0;min-height:100vh}button,input,select{font:inherit}button{cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible,input:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
a{color:var(--blue)}.shell{max-width:1580px;margin:auto;padding:26px clamp(12px,3vw,35px) 55px}
.top{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:24px;flex-wrap:wrap}.brand{display:flex;align-items:center;gap:13px}.brandmark{width:48px;height:48px;flex:none;display:grid;place-items:center;border-radius:13px;overflow:hidden;background:#081320;box-shadow:0 4px 22px #f8c9762c}.brandmark img{display:block;width:100%;height:100%;object-fit:contain}.brandname{font-size:22px;letter-spacing:.2px;font-weight:850;line-height:1.1}.brandline{font-size:11px;color:var(--muted);letter-spacing:2.1px;margin-top:5px}.actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.pill,.btn{border:1px solid var(--line);background:var(--panel);border-radius:11px;color:var(--text);padding:10px 12px;font-size:12px;font-weight:650}.btn:hover{border-color:var(--blue)}.btn.primary{background:linear-gradient(115deg,#eac575,#ca9349);color:#171c2a;border:0}.btn.danger{color:var(--red)}.dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:var(--muted);margin-right:6px}.dot.ok{background:var(--green);box-shadow:0 0 0 4px #45dda515}.dot.fail{background:var(--red)}.dot.warn{background:var(--gold)}
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:13px}.panel,.stat{background:var(--panel);border:1px solid var(--line);border-radius:17px;box-shadow:var(--shadow)}.stat{padding:18px 17px;min-height:112px}.caption{font-size:11px;letter-spacing:.3px;color:var(--muted);font-weight:650;text-transform:uppercase}.value{font-size:clamp(19px,2.3vw,28px);font-weight:820;letter-spacing:-.8px;margin-top:18px;white-space:nowrap}.positive{color:var(--green)!important}.negative{color:var(--red)!important}.muted{color:var(--muted)}.gold{color:var(--gold)}.small{font-size:11px}.notice{padding:12px 16px;border:1px solid #eeb85766;color:var(--gold);background:#d4a44312;border-radius:12px;margin-bottom:15px;font-size:12px}
.main{display:grid;grid-template-columns:1fr;gap:15px;margin-top:16px}.side-stack{display:flex;flex-direction:column;gap:15px}.side-stack .graph{height:220px}.panel{padding:17px}.heading{font-weight:760;font-size:14px;display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;gap:8px}.sub{font-size:11px;color:var(--muted);font-weight:400}.graph{height:246px;width:100%;display:block}.graph text{fill:var(--muted);font-size:11px}.timeframe{display:flex;gap:5px}.timeframe button,.mode-switch button{background:var(--panel2);color:var(--muted);border:1px solid var(--line);font-size:11px;padding:6px 9px;border-radius:7px}.timeframe button.selected,.mode-switch button.selected{color:var(--text);border-color:var(--blue);background:color-mix(in srgb,var(--blue) 12%,var(--panel2))}.grid-market{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px;max-height:680px;overflow-y:auto;padding:2px 4px 3px 1px}.coin{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px;cursor:pointer;transition:border-color .18s,transform .15s}.coin:hover,.coin.active{border-color:var(--blue);transform:translateY(-1px)}.coin-top{display:flex;align-items:center;gap:10px}.coin img,.coin .fallback{width:31px;height:31px;flex:none;border-radius:50%}.coin img{object-fit:contain;background:transparent}.coin .fallback{display:grid;place-items:center;font-size:14px;letter-spacing:.1px;color:#182339;font-weight:900;border:1px solid #9d6a2866;background:linear-gradient(135deg,#ffe4a3,#dc9d49);box-shadow:inset 0 1px 2px #fff8,0 2px 7px #0002}.coin .fallback:nth-child(2){user-select:none}.coin-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.coin-top>div:nth-child(3){min-width:0}.coin-logo[hidden]{display:none}.coin .fallback[hidden]{display:none!important}.coin-name{font-weight:780;font-size:13px}.coin-tag{font-size:10px;color:var(--muted);margin-top:3px}.coin-price{margin-left:auto;text-align:right;font-weight:750;font-size:13px}.coin-change{font-size:10px;margin-top:3px;font-weight:760}.coin-score{display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--line);margin-top:12px;padding-top:10px;gap:5px}.score{font-size:20px;font-weight:850}.mode-switch{display:flex;gap:3px}.mode-switch button{padding:5px 7px}.global-switch{display:flex;gap:2px;padding:3px;border:1px solid var(--line);background:var(--panel);border-radius:11px;align-items:center}.global-switch .global-label{color:var(--muted);font-size:11px;font-weight:700;padding:0 7px}.global-switch button{border:0;border-radius:8px;padding:8px 10px;background:transparent;color:var(--muted);font-size:12px;font-weight:750}.global-switch button.selected{background:var(--blue);color:#fff}.coin-error{font-size:10px;color:var(--red);margin-top:6px;word-break:break-word}.equity-toolbar{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin:-4px 0 9px}.equity-range{display:flex;align-items:center;background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:2px;gap:2px}.equity-range button{font-size:11px;font-weight:750;background:transparent;color:var(--muted);border:0;border-radius:7px;padding:6px 10px}.equity-range button.selected{background:var(--blue);color:#fff}.equity-range button:focus-visible{outline:2px solid var(--blue);outline-offset:1px}.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.search{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 11px;width:140px;max-width:100%;font-size:12px}.market-header{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:13px;flex-wrap:wrap}.market-header .heading{margin:0}.chartbox{min-height:400px;height:490px;background:var(--panel2);border-radius:12px;overflow:hidden;position:relative}.chartbox .waiting{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:12px}.chartbox iframe{border:0}.rows{margin-top:16px;display:grid;grid-template-columns:1.2fr 1fr;gap:15px}.tablewrap{width:100%;overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}th{color:var(--muted);font-size:10px;font-weight:650;text-align:left;border-bottom:1px solid var(--line);padding:12px 8px}td{padding:12px 8px;border-bottom:1px solid var(--line)}tr:last-child td{border:0}tbody tr{cursor:pointer}tbody tr:hover{background:var(--panel2)}.empty{text-align:center;color:var(--muted);padding:28px;font-size:12px}.footer{font-size:11px;text-align:center;color:var(--muted);margin:26px 0}.tag{border-radius:6px;padding:3px 6px;background:var(--panel2);font-size:10px;font-weight:700}.modalbg{display:none;position:fixed;inset:0;background:#040918b9;z-index:100;justify-content:center;align-items:center;padding:16px}.modalbg.on{display:flex}.modal{border:1px solid var(--line);border-radius:16px;padding:24px;background:var(--panel);max-width:480px;max-height:90vh;overflow:auto;width:100%;box-shadow:0 40px 110px #0008}.modal h3{margin:0 0 18px}.modal.history-modal{max-width:min(96vw,1320px)}.history-modal .tablewrap table{min-width:1120px}.field{display:block;margin-bottom:14px;font-size:12px;color:var(--muted)}.field input{display:block;margin-top:7px;width:100%;color:var(--text);padding:12px;border:1px solid var(--line);border-radius:9px;background:var(--panel2)}.formactions{display:flex;justify-content:flex-end;gap:7px}.details{display:grid;grid-template-columns:1fr 1fr;gap:15px 10px}.details .value{font-size:14px;margin-top:5px;white-space:normal}.statusline{font-size:11px;color:var(--muted);margin-top:7px}.sync{font-size:11px;color:var(--muted)}@media(max-width:1050px){.stats{grid-template-columns:repeat(3,1fr)}.main,.rows{grid-template-columns:1fr}.chartbox{height:410px}}@media(max-width:560px){.shell{padding:14px 10px 34px}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{min-height:95px;padding:13px}.value{font-size:20px;margin-top:12px}.brandname{font-size:18px}.panel{padding:13px}.grid-market{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.coin{padding:9px}.coin img,.coin .fallback{width:25px;height:25px}.coin-price{font-size:11px}.coin-name{font-size:11px}.mode-switch button{font-size:10px;padding:5px}.chartbox{height:355px}.graph{height:220px}}
/* Bot navigation + controls: 2 intentional rows, never mixed randomly with brand. */
.top{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:13px 14px;margin-bottom:19px}
.market-switch{display:flex;gap:3px;align-items:center;padding:4px;border:1px solid var(--line);border-radius:11px;background:var(--panel)}
.market-switch a{display:inline-flex;align-items:center;justify-content:center;min-width:100px;padding:9px 14px;border-radius:8px;font-size:12px;font-weight:780;color:var(--muted);text-decoration:none;text-align:center}
.market-switch a.selected{background:linear-gradient(115deg,#eac575,#ca9349);color:#171c2a}
.actions{grid-column:1/-1;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.actions .reset-primary{margin-left:auto}
@media(max-width:680px){.top{grid-template-columns:1fr}.market-switch{justify-self:start}.actions{grid-column:1;gap:7px}.actions .reset-primary{margin-left:0}}
</style>
</head>
<body><div class="shell">
<header class="top"><div class="brand"><div class="brandmark"><img src="/static/hks-modern-chart.svg" width="48" height="48" alt="HKS Modern Chart logo"></div><div><div class="brandname">HKS <span class="gold">Pro Trader</span></div><div class="brandline">LIGHTWEIGHT PAPER ENGINE · BOT 1</div></div></div><nav class="market-switch" aria-label="Trading dashboard"><a class="selected" href="/" aria-current="page">Future</a><a href="/bot2">Spot</a></nav><div class="actions"><button class="btn" id="owner-button" onclick="toggleOwner()">Owner Login</button><span class="pill" id="scanner-pill"><i class="dot"></i><span>Scanner: Checking…</span></span><div class="global-switch" role="group" aria-label="{% if parallel_enabled %}Portfolio view{% else %}Global strategy mode{% endif %}"><span class="global-label">{% if parallel_enabled %}PORTFOLIO{% else %}ALL COINS{% endif %}</span><button type="button" id="global-normal" class="selected" onclick="changeGlobalMode('NORMAL')">Normal</button><button type="button" id="global-reverse" onclick="changeGlobalMode('REVERSE')">Reverse</button></div><button class="btn" id="theme-btn" onclick="toggleTheme()">☼ Light Mode</button><button class="btn" onclick="showHistory()">Trade History</button><button class="btn reset-primary" onclick="openTools()">Reset 1K</button></div></header>
{% if sqlite_mode %}<div class="notice">⚠ Running on local SQLite. For Vercel, configure a persistent PostgreSQL DATABASE_URL before relying on saved trades, wallet or modes.</div>{% endif %}
{% if not reset_ready %}<div class="notice">⚠ Reset 1K is disabled until HKS_RESET_PASSWORD is stored in Vercel Environment Variables.</div>{% endif %}
<div class="statusline" style="margin:-12px 0 14px">{% if parallel_enabled %}Every qualified 15m signal runs NORMAL and REVERSE simultaneously with separate risk, wallets, positions and history. Select a portfolio to review. Each uses $1,000 strategy equity and $2,000 virtual collateral.{% else %}Global Normal/Reverse applies to all new entries. Per-coin custom mode remains available; changing Global mode resets those custom choices. Open positions keep their original direction.{% endif %}</div>
{% if parallel_enabled %}
<div class="stats" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-bottom:15px">
 <div class="stat"><div class="caption">NORMAL · Strategy equity</div><div class="value" id="mode-normal-balance">$1,000.00</div><div class="statusline" id="mode-normal-cash">Virtual collateral available: $2,000</div></div>
 <div class="stat"><div class="caption">REVERSE · Strategy equity</div><div class="value" id="mode-reverse-balance">$1,000.00</div><div class="statusline" id="mode-reverse-cash">Virtual collateral available: $2,000</div></div>
</div>
{% endif %}
<div class="stats">
 <div class="stat"><div class="caption">{% if parallel_enabled %}Selected Strategy Balance{% else %}Wallet Balance{% endif %}</div><div class="value" id="balance">$1,000.00</div><div class="statusline">Closed-trade balance · starts at $1,000</div></div>
 <div class="stat"><div class="caption">Unrealized PnL</div><div class="value" id="unreal">$0.00</div><div class="statusline">Open positions, gross</div></div>
 <div class="stat"><div class="caption">Winning Trades</div><div class="value positive" id="wins">0</div><div class="statusline">Net after fees</div></div>
 <div class="stat"><div class="caption">Losing Trades</div><div class="value negative" id="losses">0</div><div class="statusline">Net after fees</div></div>
 <div class="stat"><div class="caption">Win Rate</div><div class="value" id="winrate">0%</div><div class="statusline" id="open-count">0 open positions</div></div>
</div>
<div class="main">

 <section class="panel"><div class="heading">TradingView Chart <span><span class="sub" id="selected-symbol">BTCUSDT</span> · <a class="sub" id="chart-external" href="https://www.tradingview.com/chart/?symbol=BITGET%3ABTCUSDT.P" target="_blank" rel="noopener noreferrer">Open on TradingView ↗</a></span></div><div class="timeframe" style="margin-bottom:12px"><button onclick="selectTF('1')" data-tf="1">1m</button><button onclick="selectTF('15')" class="selected" data-tf="15">15m</button><button onclick="selectTF('60')" data-tf="60">1h</button><button onclick="selectTF('D')" data-tf="D">1D</button></div><div class="chartbox" id="chart"><div class="waiting">Loading TradingView chart…</div></div><div class="statusline">Timeframe buttons affect chart display only. Strategy decisions remain on completed 15m candles.</div></section>
</div>
<div class="rows">
 <section class="panel"><div class="market-header"><div class="heading">Dynamic Coins <span class="sub" id="coin-count">0 pairs</span></div><div class="toolbar"><input class="search" id="coin-search" aria-label="Search coin" placeholder="Search coin…" oninput="renderCoins()"><span class="sync" id="market-status">UTC daily change</span></div></div><div id="coin-grid" class="grid-market"><div class="empty">Starting the scanner automatically. Coins will appear after market data loads.</div></div><div class="statusline">Stablecoin base pairs excluded. Score is a UI progress score; trading still requires the original sweep and ≥75 actual entry score.</div></section>
 <div class="side-stack">
 <section class="panel"><div class="heading">Open Paper Positions <span class="sub" id="max-positions">Risk managed · max —</span></div><div class="tablewrap"><table><thead><tr><th>Coin</th><th>Side</th><th>Mode</th><th>Entry</th><th>Stop</th><th>Capital Used</th><th>PnL</th><th>Action</th></tr></thead><tbody id="positions"><tr><td colspan="8" class="empty">No open positions</td></tr></tbody></table></div><div class="statusline" id="scanner-line">Scanner last successful scan: —</div></section>
 <section class="panel"><div class="heading">{% if parallel_enabled %}<span id="equity-title">NORMAL</span> Strategy Equity{% else %}Wallet Performance{% endif %} <span class="sub">Closed-trade equity · After fees</span></div><div class="equity-toolbar"><div class="equity-range" role="group" aria-label="Equity chart history"><button type="button" data-equity-range="10" onclick="setEquityRange(10)">10</button><button type="button" class="selected" data-equity-range="30" onclick="setEquityRange(30)">30</button><button type="button" data-equity-range="50" onclick="setEquityRange(50)">50</button><button type="button" data-equity-range="all" onclick="setEquityRange('all')">All</button></div><span class="sub" id="equity-summary">Closed trades · Starting $1,000</span></div><svg class="graph" id="equity-chart" role="img" aria-label="Recorded equity for selected mode" viewBox="0 0 780 250" preserveAspectRatio="none"></svg><div class="statusline">Only recorded closed-trade balances. Green = profit, red = loss. Unrealized excluded.</div>
{% if parallel_enabled %}<div class="heading" style="margin-top:20px"><span id="equity-other-title">REVERSE</span> Strategy Equity</div><div class="statusline" id="equity-summary-other">Closed trades · Starting $1,000</div><svg class="graph" id="equity-chart-other" role="img" aria-label="Other mode's recorded equity" viewBox="0 0 780 250" preserveAspectRatio="none"></svg>{% endif %}</section>
 </div>
</div>
<section class="panel" style="margin-top:16px"><div class="heading">Last 10 Closed Trades · <span id="history-mode-label">NORMAL</span> <button class="btn" onclick="showHistory()">View Full History →</button></div><div class="tablewrap"><table><thead><tr><th>Coin</th><th>Direction</th><th>Strategy</th><th>Qty</th><th>Capital Used</th><th>Entry</th><th>Exit</th><th>Exit Reason</th><th>Fees</th><th>Net PnL</th><th>Net %</th><th>MFE</th><th>MAE</th><th>Duration</th><th>Closed (UTC)</th></tr></thead><tbody id="recent"><tr><td colspan="15" class="empty">No closed trades yet</td></tr></tbody></table></div></section>
<footer class="footer">HKS Pro Trader · Illustrative paper execution · No live orders · Market/chart data require Binance USD-M Futures / TradingView connectivity · Fees configurable; fills simulated</footer>
</div>
<div class="modalbg" id="modal" onclick="if(event.target===this)hideModal()"><div class="modal"><h3 id="modal-title">Details</h3><div id="modal-content"></div><div class="formactions" style="margin-top:18px"><button class="btn" onclick="hideModal()">Close</button></div></div></div>
<script>
const resetReady={{ reset_ready | tojson }};
const parallelActive={{ parallel_enabled | tojson }};
let portfolioMode="NORMAL", equityByMode={NORMAL:[],REVERSE:[]};
let ownerAuthenticated=false;
const pendingCloses=new Set();
let coinData=[], selected='BTCUSDT', timeframe='15', tradeIndex={}, selectedHistory=[], globalMode='NORMAL';
const fmt=(n,p=2)=>n==null?'—':Number(n).toLocaleString('en-US',{minimumFractionDigits:p,maximumFractionDigits:p});
const money=(v,p=2)=>v==null?'—':(v<0?'−':'')+'$'+fmt(Math.abs(v),p);
const timeUTC=t=>t?new Date(t).toLocaleString('en-GB',{timeZone:'UTC',hour12:false}):'—';
const duration=t=>{const m=Math.max(0,Math.floor(Number(t||0)/60000));return Math.floor(m/1440)+'d '+Math.floor(m%1440/60)+'h '+m%60+'m'};
const el=id=>document.getElementById(id);
const cssSigned=x=>x>0?'positive':x<0?'negative':'muted';
function setThemeLabel(){el('theme-btn').textContent=document.body.classList.contains('light')?'☾ Dark Mode':'☼ Light Mode'}
function initTheme(){document.body.classList.toggle('light',localStorage.getItem('hks-theme')==='light');setThemeLabel()}
function toggleTheme(){let light=document.body.classList.toggle('light');localStorage.setItem('hks-theme',light?'light':'dark');setThemeLabel();renderChart()}
initTheme();
refreshOwnerStatus();
function escapeHTML(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function showModal(title,html){el('modal').querySelector('.modal').classList.remove('history-modal');el('modal-title').textContent=title;el('modal-content').innerHTML=html;el('modal').classList.add('on')}
function hideModal(){el('modal').classList.remove('on')}
function notify(s){showModal('HKS Notice','<p>'+escapeHTML(s)+'</p>')}
async function post(url,body){let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let j=await r.json().catch(()=>({error:'Unexpected server response'}));if(!r.ok)throw Error(j.error||('HTTP '+r.status));return j}
function openTools(){
 if(!ownerAuthenticated){notify('Owner Login required to reset the paper account.');return}
 showModal('Reset 1K','<p class="small muted">Mode changes affect NEW trades only. Existing open positions keep their opening mode. The scanner starts on website visit; external Cron GET /wake performs a direct completed-candle scan even if no browser is open. /api/cron remains token-protected.</p><p class="small negative">Reset 1K deletes paper positions, trade history and wallet performance only. Market scores, SMC/candle analysis and coin modes are preserved.</p><label class="field">Reset password<input type="password" id="reset-pass" autocomplete="off"></label><label class="field">Type RESET 1K<input id="reset-confirm" placeholder="RESET 1K"></label><button class="btn danger" onclick="doReset()" '+(resetReady?'':'disabled')+'>Reset 1K</button>');
}
async function doManualClose(symbol){
 if(!ownerAuthenticated){notify('Owner Login required.');return}
 if(!/^[A-Z0-9]+USDT$/.test(symbol)||pendingCloses.has(symbol))return;
 pendingCloses.add(symbol);
 try{
  // One-click: request starts immediately. No modal or password per trade.
  const result=await post('/api/position/'+symbol+'/close',{});
  await load();
  notify(symbol+' manually closed at '+money(result.exit_price,6)+' · Net '+money(result.net_pnl,4));
 }catch(e){notify(e.message)}
 finally{pendingCloses.delete(symbol)}
}
function updateOwnerUI(){
 const button=el('owner-button');
 button.textContent=ownerAuthenticated?'Owner · Logout':'Owner Login';
 document.querySelectorAll('.global-switch button').forEach(x=>x.disabled=!ownerAuthenticated);
 document.querySelectorAll('.mode-switch button').forEach(x=>x.disabled=!ownerAuthenticated);
 document.querySelectorAll('#positions button').forEach(x=>x.disabled=!ownerAuthenticated);
}
async function refreshOwnerStatus(){
 try{const r=await fetch('/api/owner/status',{cache:'no-store'});ownerAuthenticated=r.ok&&Boolean((await r.json()).owner)}
 catch(_){ownerAuthenticated=false}
 updateOwnerUI();renderCoins();
}
function toggleOwner(){
 if(!ownerAuthenticated){
  showModal('Owner Login','<p class="small muted">Login once to unlock One-Click Close and trade-mode controls. Reset 1K still needs its own password.</p><label class="field">Owner password<input type="password" id="owner-pass" autocomplete="current-password"></label><button class="btn primary" id="owner-login-action" onclick="doOwnerLogin()">Unlock Dashboard</button>');
 }else{
  showModal('Owner Logout','<p class="small muted">Lock owner controls on this browser? Market scanning continues normally.</p><button class="btn danger" onclick="doOwnerLogout()">Logout & Lock</button>');
 }
}
async function doOwnerLogin(){
 const b=el('owner-login-action');if(b.disabled)return;b.disabled=true;
 try{
  await post('/api/owner/login',{password:el('owner-pass').value});
  ownerAuthenticated=true;hideModal();updateOwnerUI();renderCoins();await load();
 }catch(e){b.disabled=false;notify(e.message)}
}
async function doOwnerLogout(){
 try{
  await post('/api/owner/logout',{});
  ownerAuthenticated=false;hideModal();updateOwnerUI();renderCoins();await load();
 }catch(e){notify(e.message)}
}
async function doReset(){try{let p=el('reset-pass').value,confirm=el('reset-confirm').value;if(!window.confirm('Delete ALL paper account data and reset exactly to $1,000?'))return;await post('/api/reset',{password:p,confirm});hideModal();await load()}catch(e){notify(e.message)}}
async function changeMode(symbol,mode,evt){evt.stopPropagation();if(!ownerAuthenticated){notify('Owner Login required.');return}try{await post('/api/mode/'+symbol,{mode});const c=coinData.find(c=>c.symbol===symbol);if(c)c.mode=mode;renderCoins()}catch(e){notify(e.message)}}
function renderGlobalMode(){
 el('global-normal').classList.toggle('selected',globalMode==='NORMAL');
 el('global-reverse').classList.toggle('selected',globalMode==='REVERSE');
}
async function changeGlobalMode(mode){
 if(!ownerAuthenticated){notify('Owner Login required.');return}
 if(!['NORMAL','REVERSE'].includes(mode))return;
 if(!window.confirm('Set ALL coins to '+mode+'? This clears custom coin modes for future entries. Open trades remain unchanged.'))return;
 try{
   await post('/api/mode/all',{mode,confirm:'ALL COINS'});
   globalMode=mode;coinData.forEach(c=>c.mode=mode);renderGlobalMode();renderCoins();
   notify('All coins set to '+mode+'. Open trades unchanged.');
 }catch(e){notify(e.message)}
}
function selectCoin(s){if(!/^[A-Z0-9]+USDT$/.test(s))return;selected=s;el('selected-symbol').textContent=s;renderCoins();renderChart()}
function selectTF(tf){timeframe=tf;document.querySelectorAll('[data-tf]').forEach(x=>x.classList.toggle('selected',x.dataset.tf===tf));renderChart()}
function renderChart(){
 // TradingView embeds require the official container hierarchy. The exact
 // Futures/perpetual market is retained, never silently substituted with Spot.
 const parent=el('chart');parent.replaceChildren();
 const symbol='BITGET:'+selected+'.P';
 const external='https://www.tradingview.com/chart/?symbol='+encodeURIComponent(symbol)+'&interval='+encodeURIComponent(timeframe);
 el('chart-external').href=external;
 const holder=document.createElement('div');holder.className='tradingview-widget-container';
 holder.style.cssText='height:100%;width:100%;position:relative';parent.appendChild(holder);
 const widget=document.createElement('div');widget.className='tradingview-widget-container__widget';
 widget.style.cssText='height:100%;width:100%';holder.appendChild(widget);
 const notice=document.createElement('div');notice.className='waiting';
 notice.style.cssText='z-index:1;pointer-events:auto;flex-direction:column;gap:12px;text-align:center;padding:16px';
 const msg=document.createElement('span');msg.textContent='Loading TradingView chart…';notice.appendChild(msg);
 const link=document.createElement('a');link.href=external;link.target='_blank';link.rel='noopener noreferrer';
 link.textContent='Open '+selected+' on TradingView';link.style.cssText='color:var(--blue);text-decoration:underline';notice.appendChild(link);
 parent.appendChild(notice);
 let ready=false;
 const observer=new MutationObserver(()=>{
   const iframe=holder.querySelector('iframe');
   if(iframe && !ready){ready=true;notice.remove();observer.disconnect()}
 });
 observer.observe(holder,{childList:true,subtree:true});
 const scr=document.createElement('script');scr.type='text/javascript';scr.async=true;
 scr.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
 scr.textContent=JSON.stringify({autosize:true,symbol:symbol,interval:timeframe,timezone:'Etc/UTC',
   theme:document.body.classList.contains('light')?'light':'dark',style:'1',locale:'en',
   allow_symbol_change:false,hide_side_toolbar:true,hide_top_toolbar:true,
   calendar:false,hide_legend:false,support_host:'https://www.tradingview.com'});
 scr.onerror=()=>{
   if(!parent.contains(notice))return;
   msg.textContent='TradingView could not load (network or browser blocking).';
 };
 holder.appendChild(scr);
 setTimeout(()=>{
   if(!parent.contains(holder)){observer.disconnect();return}
   if(!ready){msg.textContent='Chart not available in this browser. Open TradingView directly below.';observer.disconnect()}
 },12000);
}
// Keep coin cards and their image nodes stable across 2-second price refreshes.
const coinNodes=new Map();
const logoUrls=new Map();
let geckoStarted=false;
const logoAliases={"1000PEPE":"PEPE","1000BONK":"BONK","1000SHIB":"SHIB","1000FLOKI":"FLOKI","1000SATS":"SATS","1000RATS":"RATS","1000LUNC":"LUNC","1000XEC":"XEC"};
function logoBase(symbol){const base=symbol.replace(/USDT$/,'');return logoAliases[base]||base.replace(/^1000(?=[A-Z])/, '');}
function updateLogo(card,symbol){
 const img=card.querySelector('.coin-logo'), fallback=card.querySelector('.fallback');
 if(!img||!fallback)return;
 const key=logoBase(symbol).toLowerCase();
 const sources=[logoUrls.get(key),
   'https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@0.18.1/128/color/'+encodeURIComponent(key)+'.png',
   'https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@0.18.1/svg/color/'+encodeURIComponent(key)+'.svg'
 ].filter(Boolean);
 // Preload via a separate eager Image() independent of the hidden UI element.
 // Requests only happen on card creation / icon mapping update, not every 2s.
 const token=String((Number(card.dataset.logoRequest)||0)+1);
 card.dataset.logoRequest=token;
 let idx=0;
 function tryNext(){
   if(card.dataset.logoRequest!==token)return;
   if(idx>=sources.length){
     if(!img.dataset.loaded){img.hidden=true;fallback.hidden=false;}
     return;
   }
   const url=sources[idx++], preloader=new Image();
   preloader.onload=()=>{
     if(card.dataset.logoRequest!==token || !card.isConnected)return;
     img.src=url;img.dataset.loaded='1';img.hidden=false;fallback.hidden=true;
   };
   preloader.onerror=tryNext;
   preloader.src=url;
 }
 tryNext();
}
// CoinGecko public market data is used ONLY for logos; failures never affect trading.
// Fetch once per dashboard load, not once per coin or every 2 seconds.
async function loadCoinGeckoLogos(){
 if(geckoStarted)return;geckoStarted=true;
 try{
  const pages=[{order:'market_cap_desc',page:1},{order:'market_cap_desc',page:2},{order:'market_cap_desc',page:3},{order:'volume_desc',page:1},{order:'volume_desc',page:2},{order:'volume_desc',page:3}];
  for(const p of pages){
   const url='https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order='+p.order+'&per_page=250&page='+p.page+'&sparkline=false';
   const ctl=new AbortController();const timeout=setTimeout(()=>ctl.abort(),6500);
   let response;try{response=await fetch(url,{signal:ctl.signal})}finally{clearTimeout(timeout)}
   if(!response.ok)continue;
   const rows=await response.json();if(!Array.isArray(rows))break;
   for(const x of rows){if(typeof x.symbol==='string'&&typeof x.image==='string'&&/^https:\/\//.test(x.image)){
    const k=x.symbol.toLowerCase();if(!logoUrls.has(k))logoUrls.set(k,x.image);
   }}
  }
  for(const [sym,card] of coinNodes){if(card.isConnected&&logoUrls.has(logoBase(sym).toLowerCase()))updateLogo(card,sym)}
 }catch(_e){/* icon CDN and one-letter fallback stay available */}
}
function renderCoins(){
 const q=el('coin-search').value.toUpperCase().trim();const view=coinData.filter(x=>x.symbol.includes(q));const grid=el('coin-grid');
 if(!view.length){grid.replaceChildren();coinNodes.clear();grid.innerHTML='<div class="empty">No matching coins. Wait for first historical scan or change filter.</div>';return}
 const keep=new Set(view.map(c=>c.symbol));
 grid.querySelectorAll(':scope > .empty').forEach(n=>n.remove());
 for(const [sym,node] of coinNodes){if(!keep.has(sym)){node.remove();coinNodes.delete(sym)}}
 let cardIndex=0;
 for(const c of view){
  const base=c.symbol.slice(0,-4);let card=coinNodes.get(c.symbol);
  if(!card){
   card=document.createElement('article');card.className='coin';card.dataset.symbol=c.symbol;
   card.innerHTML='<div class="coin-top"><img class="coin-logo" alt="" hidden><div class="fallback" style="display:grid">'+escapeHTML(base.slice(0,1))+'</div><div><div class="coin-name">'+escapeHTML(base)+'</div><div class="coin-tag"></div></div><div class="coin-price"><span class="price-text"></span><div class="coin-change"></div></div></div><div class="coin-score"><div><span class="caption">Score</span> <span class="score"></span><span class="small muted"> / 100</span></div><div class="mode-switch"><button data-mode="NORMAL">Normal</button><button data-mode="REVERSE">Reverse</button></div></div><div class="coin-error" hidden></div>';
   card.onclick=()=>selectCoin(c.symbol);
   card.querySelectorAll('[data-mode]').forEach(b=>b.onclick=e=>changeMode(c.symbol,b.dataset.mode,e));
   coinNodes.set(c.symbol,card);updateLogo(card,c.symbol);
  }
  card.classList.toggle('active',selected===c.symbol);
  card.querySelector('.coin-tag').textContent=(c.open?'● Open trade':'USDT · #'+(coinData.indexOf(c)+1))+(c.mode!==globalMode?' · Custom':'');
  card.querySelector('.price-text').textContent=c.price==null?'—':'$'+fmt(c.price,c.price<1?6:2);
  const change=card.querySelector('.coin-change');change.className='coin-change '+cssSigned(c.change);change.textContent=c.change==null?'—':(c.change>0?'+':'')+fmt(c.change,2)+'%';
  card.querySelector('.score').textContent=c.score;
  card.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('selected',b.dataset.mode===c.mode);b.disabled=!ownerAuthenticated});
  const err=card.querySelector('.coin-error');err.hidden=!c.error;err.textContent=c.error||'';
  // Keep the DOM node in place when position is unchanged; no logo flicker.
  const at=grid.children[cardIndex];
  if(at!==card)grid.insertBefore(card,at||null);
  cardIndex++;
 }
 if(!geckoStarted)loadCoinGeckoLogos();
}
// Values come only from persisted EquityPoint records, one for each closed trade
// plus the true recorded $1,000 initialization point. No synthetic trade wiggles.
let equityRange=30, equityRecent=[], equityAll=[], equityAllLoadedCount=-1;
let equityTotalTrades=0, equityLoadingAll=false;
function selectEquityPoints(source,range){
 const count=(range==='all'?Math.max(0,source.length-1):range);
 // Include the prior REAL closing balance as the first anchor for the window.
 return source.slice(-Math.min(source.length,count+1));
}
function setEquityRange(range){
 if(![10,30,50,'all'].includes(range))return;
 equityRange=range;
 document.querySelectorAll('[data-equity-range]').forEach(b=>b.classList.toggle('selected',String(range)===b.dataset.equityRange));
 renderEquity();
 if(range==='all'&&equityAllLoadedCount!==equityTotalTrades)fetchAllEquity();
}
async function fetchAllEquity(){
 if(equityLoadingAll)return;
 equityLoadingAll=true;
 try{
  const res=await fetch('/api/equity',{cache:'no-store'});
  if(!res.ok)throw Error('HTTP '+res.status);
  const data=await res.json();
  if(!Array.isArray(data.points))throw Error('Equity history unavailable');
  equityAll=data.points;
  equityAllLoadedCount=Math.max(0,data.points.length-1);
  if(equityRange==='all')renderEquity();
 }catch(err){if(equityRange==='all')el('equity-summary').textContent='Unable to load full equity history · '+err.message}
 finally{equityLoadingAll=false}
}
function updateEquityPoints(points,totalTrades){
 equityRecent=Array.isArray(points)?points:[];
 equityTotalTrades=totalTrades;
 if(equityRange==='all'&&equityAllLoadedCount!==totalTrades)fetchAllEquity();
 renderEquity();
}
function renderEquity(){
 const svg=el('equity-chart');svg.replaceChildren();
 const source=equityRange==='all'&&equityAllLoadedCount===equityTotalTrades?equityAll:equityRecent;
 const records=selectEquityPoints(source,equityRange);
 const values=records.map(p=>Number(p.balance)).filter(Number.isFinite);
 const ns='http://www.w3.org/2000/svg';
 function add(tag,attrs,parent=svg){const node=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));parent.appendChild(node);return node}
 const w=780,h=250,left=63,right=13,top=13,bottom=30,iw=w-left-right,ih=h-top-bottom;
 const starting=1000,center=top+ih/2;
 const furthest=Math.max(1,...values.map(v=>Math.abs(v-starting)));
 const span=furthest*1.18;
 const sx=i=>left+(values.length<=1?0:i/(values.length-1))*iw;
 const sy=v=>center-(v-starting)/span*(ih/2);
 // Fine guide at initial balance; no thick baseline, fake movement or trade labels.
 add('path',{d:'M'+left+' '+center+' L'+(w-right)+' '+center,stroke:'var(--muted)','stroke-width':'.55',opacity:'.23',fill:'none'});
 for(let i=-2;i<=2;i++){
  const val=starting-i*span/2, y=center+i*ih/4;
  const txt=add('text',{x:left-9,y:y+4,'text-anchor':'end',fill:'var(--muted)',opacity:'.9'});
  txt.textContent='$'+fmt(val,span<10?2:0);
 }
 if(values.length===0){el('equity-summary').textContent='Waiting for recorded equity';return}
 // Shape-preserving Hermite tangents: curves pass through each ACTUAL balance,
 // without overshoot, invented peaks/troughs or extra value observations.
 const xs=values.map((_,i)=>sx(i)),ys=values.map(v=>sy(v));
 const slopes=ys.slice(1).map((y,i)=>(y-ys[i])/(xs[i+1]-xs[i]));
 const tangents=ys.map((_,i)=>{
  if(i===0)return slopes[0]||0;
  if(i===ys.length-1)return slopes[slopes.length-1]||0;
  const a=slopes[i-1],b=slopes[i];
  return a*b<=0?0:(2*a*b/(a+b));
 });
 const bottomY=h-bottom;
 for(let i=0;i<values.length-1;i++){
  const x0=xs[i],x1=xs[i+1],y0=ys[i],y1=ys[i+1],dx=x1-x0;
  const cmd='M'+x0+' '+y0+' C'+(x0+dx/3)+' '+(y0+tangents[i]*dx/3)+' '+(x1-dx/3)+' '+(y1-tangents[i+1]*dx/3)+' '+x1+' '+y1;
  const color=values[i+1]>values[i]?'#35df9f':values[i+1]<values[i]?'#ff687a':'#91a5bd';
  add('path',{d:cmd+' L'+x1+' '+bottomY+' L'+x0+' '+bottomY+' Z',fill:color,opacity:'.07'});
  add('path',{d:cmd,fill:'none',stroke:color,'stroke-width':'7',opacity:'.10','stroke-linecap':'round'});
  add('path',{d:cmd,fill:'none',stroke:color,'stroke-width':'4.25','stroke-linecap':'round','stroke-linejoin':'round'});
 }
 // A single small endpoint indicator is enough, including when no trades exist.
 add('circle',{cx:xs[xs.length-1],cy:ys[ys.length-1],r:'3.1',fill:'var(--text)',stroke:'var(--panel)','stroke-width':'1.4'});
 const count=Math.max(0,records.length-1);
 el('equity-summary').textContent=count+' closed '+(count===1?'trade':'trades')+' · '+money(values[values.length-1]);
}
function rowOfTrade(t){
 let tr=document.createElement('tr');
 tr.innerHTML='<td><b>'+escapeHTML(t.symbol)+'</b></td><td>'+escapeHTML(t.side)+'</td><td><span class="tag">'+escapeHTML(t.mode)+'</span></td>'+
  '<td>'+fmt(t.qty,6)+'</td><td>'+money(t.capital_used,2)+'</td><td>'+money(t.entry,t.entry<1?6:2)+'</td><td>'+money(t.exit,t.exit<1?6:2)+'</td>'+
  '<td>'+escapeHTML(t.reason)+'</td><td>'+money(t.fees,4)+'</td><td class="'+cssSigned(t.net)+'">'+money(t.net,3)+'</td>'+
  '<td class="'+cssSigned(t.net_pct)+'">'+fmt(t.net_pct,2)+'%</td><td class="positive">'+fmt(t.mfe_pct,2)+'%</td><td class="negative">'+fmt(t.mae_pct,2)+'%</td>'+
  '<td>'+duration(t.duration_ms)+'</td><td>'+escapeHTML(timeUTC(t.exit_ms))+'</td>';
 tr.onclick=()=>showTrade(t);return tr;
}
function showTrade(t){
 let data=[['Coin',t.symbol],['Direction',t.side],['Mode at entry',t.mode],['Strategy score',t.score],['Original signal',t.original_signal],
 ['Entry price',money(t.entry,6)],['Exit price',money(t.exit,6)],['Initial stop',money(t.stop,6)],['Quantity',fmt(t.qty,8)],
 ['Capital used / 1x notional',money(t.capital_used,4)],['Entry time UTC',timeUTC(t.entry_ms)],['Exit time UTC',timeUTC(t.exit_ms)],
 ['Duration',duration(t.duration_ms)],['Exit reason',t.reason],['Gross PnL',money(t.gross,4)],['Entry fee',money(t.entry_fee,5)],
 ['Exit fee',money(t.exit_fee,5)],['Total fees',money(t.fees,5)],['Net PnL',money(t.net,4)],
 ['Net PnL % of capital',fmt(t.net_pct,3)+'%'],['MFE (price)',fmt(t.mfe_pct,3)+'% · '+money(t.mfe_usd,3)],
 ['MAE (price)',fmt(t.mae_pct,3)+'% · '+money(t.mae_usd,3)]];
 showModal('Trade #'+t.id,'<div class="details">'+data.map(x=>'<div><div class="caption">'+escapeHTML(x[0])+'</div><div class="value">'+escapeHTML(x[1])+'</div></div>').join('')+'</div><p class="statusline">MFE/MAE are approximate price excursions (1m OHLC, plus manual close quote), not wallet PnL. Legacy STOP rows cannot be reliably classified. All fills/fees are simulations.</p>');
}
async function showHistory(){
 try{
  let r=await fetch('/api/history?limit=100');let d=await r.json();selectedHistory=d.trades;
  let html='<p class="small muted">Latest '+d.trades.length+' closed trades. Net % is relative to original capital used (1x notional). Scroll sideways for all fields; click a row for details.</p><div class="tablewrap" style="max-height:60vh"><table><thead><tr><th>Coin</th><th>Side</th><th>Mode</th><th>Qty</th><th>Capital Used</th><th>Entry</th><th>Exit</th><th>Exit Reason</th><th>Fees</th><th>Net</th><th>Net %</th><th>MFE</th><th>MAE</th><th>Duration</th><th>UTC</th></tr></thead><tbody id="history-body"></tbody></table></div>';
  showModal('Trade History',html);el('modal').querySelector('.modal').classList.add('history-modal');
  let t=el('history-body');d.trades.forEach(x=>t.appendChild(rowOfTrade(x)));
 }catch(e){notify(e.message)}
}
let refreshing=false;
async function load(){if(refreshing)return;refreshing=true;try{
 let r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);let d=await r.json();coinData=d.coins;globalMode=d.global_mode||'NORMAL';renderGlobalMode();
 el('max-positions').textContent='Risk managed · max '+d.max_positions;
 el('balance').textContent=money(d.balance);el('unreal').textContent=money(d.unrealized);el('unreal').className='value '+cssSigned(d.unrealized);
 el('wins').textContent=d.wins;el('losses').textContent=d.losses;el('winrate').textContent=fmt(d.wins*100/Math.max(d.wins+d.losses,1),1)+'%';el('open-count').textContent=d.open_positions.length+' open position(s)';el('coin-count').textContent=d.coin_count+' pairs';
 const st=d.scanner;const pill=el('scanner-pill');pill.innerHTML='<i class="dot '+(st.status==='RUNNING'?'ok':st.status==='OFFLINE'?'fail':'warn')+'"></i>'+escapeHTML('Scanner: '+st.status);pill.title=st.last_error||'';
 el('scanner-line').textContent='Last successful scan: '+timeUTC(st.last_success)+' UTC | Processed '+st.processed+' | Errors '+st.errors+(st.last_error?' | '+st.last_error:'');
 el('market-status').textContent='Prices: '+(d.market_stale?'STALE'+(d.quote_feed?.last_error?' · '+d.quote_feed.last_error.slice(0,110):''):'fresh')+' · 00:00 UTC base · 15m confirmed signals';
 renderCoins();updateEquityPoints(d.equity_points,(Number(d.wins)||0)+(Number(d.losses)||0)+(Number(d.flats)||0));
 const pbody=el('positions');pbody.replaceChildren();if(!d.open_positions.length)pbody.innerHTML='<tr><td colspan="8" class="empty">No open positions</td></tr>';
 d.open_positions.forEach(p=>{let tr=document.createElement('tr');tr.innerHTML='<td><b>'+escapeHTML(p.symbol)+'</b></td><td>'+p.side+'</td><td>'+p.mode+'</td><td>'+fmt(p.entry,p.entry<1?6:2)+'</td><td>'+fmt(p.stop,p.stop<1?6:2)+'</td><td>'+money(p.capital_used,2)+'</td><td class="'+cssSigned(p.pnl)+'">'+money(p.pnl,3)+'</td><td><button class="btn danger" type="button">Close Trade</button></td>';tr.querySelector('button').disabled=!ownerAuthenticated||pendingCloses.has(p.symbol);tr.querySelector('button').textContent=pendingCloses.has(p.symbol)?'Closing…':'Close Trade';tr.querySelector('button').onclick=()=>doManualClose(p.symbol);pbody.appendChild(tr)});
 const recent=el('recent');recent.replaceChildren();if(!d.recent.length)recent.innerHTML='<tr><td colspan="15" class="empty">No closed trades yet</td></tr>';
 d.recent.forEach(t=>recent.appendChild(rowOfTrade(t)));
 }catch(e){el('scanner-pill').innerHTML='<i class="dot fail"></i>Dashboard offline';el('scanner-line').textContent='Dashboard request failed: '+e.message}finally{refreshing=false}}
renderChart();load();setInterval(load,2000);
</script></body></html>'''

# Bot 2 is independently implemented in its own module and b2_* tables.
# Do not change Bot 1 scanner, scoring, wallet, cron, or trade endpoints.
from bot2_spot import install_bot2
install_bot2(app, Session=Session, engine=engine, Base=Base, db_postgres=DB_POSTGRES,
             evaluate_smc=evaluate_smc, trail_stop=trail_stop,
             get_stop_fill=get_stop_fill, require_cron_token=require_cron_token,
             require_owner=require_owner, same_origin_post=same_origin_post,
             check_reset_attempt=check_reset_attempt)

if __name__ == "__main__":
    # python app.py starts the background scanner before Flask accepts traffic.
    # Gunicorn starts it on ordinary browser requests; cron /wake runs a direct
    # request-bound scan, independent of daemon background thread longevity.
    _ensure_automatic_scanner()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
