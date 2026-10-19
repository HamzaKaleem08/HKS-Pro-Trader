"""Canonical decimal and UTC contracts. No networking or mutable globals."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re

from .errors import ValidationError

INTERVALS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
SYMBOL = re.compile(r"[A-Z0-9]{2,24}USDT\Z")
IDENTIFIER = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")


def decimal(value, name="number", minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValidationError(f"{name}: a finite decimal is required")
    if len(str(value)) > 80:
        raise ValidationError(f"{name}: decimal is too long")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{name}: a finite decimal is required") from None
    if not result.is_finite() or result.adjusted() > 15 or result.as_tuple().exponent < -18:
        raise ValidationError(f"{name}: invalid decimal precision or magnitude")
    if minimum is not None and result < Decimal(str(minimum)):
        raise ValidationError(f"{name}: must be at least {minimum}")
    if maximum is not None and result > Decimal(str(maximum)):
        raise ValidationError(f"{name}: must not exceed {maximum}")
    return result


def integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(f"{name}: integer in [{minimum}, {maximum}] required")
    return value


def symbol(value):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise ValidationError("symbol: uppercase USDT identity required")
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError("invalid identifier")
    return value


def timestamp(value):
    """Integer milliseconds or an explicit UTC ISO instant; never infer seconds."""
    if isinstance(value, bool):
        raise ValidationError("UTC timestamp required")
    if isinstance(value, int):
        if 946684800000 <= value < 4102444800000:
            return value
        raise ValidationError("timestamp must be milliseconds between 2000 and 2100")
    if not isinstance(value, str) or len(value) > 32 or not value.endswith(("Z", "+00:00")):
        raise ValidationError("timestamp must be explicit UTC ISO 8601 or integer milliseconds")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value or dt.tzinfo is None or dt.utcoffset().total_seconds() != 0 or dt.microsecond % 1000:
            raise ValueError
        delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return timestamp(delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000)
    except (ValueError, OverflowError):
        raise ValidationError("invalid UTC timestamp") from None


def utc(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def primitives(value):
    if is_dataclass(value):
        return primitives(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): primitives(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitives(v) for v in value]
    return value


def canonical(value):
    return json.dumps(primitives(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
