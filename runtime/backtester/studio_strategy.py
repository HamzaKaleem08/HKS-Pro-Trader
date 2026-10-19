"""Bounded data-only language. Never eval/exec/compile/import user text.

The evaluator is trusted code; untrusted definitions can only select these
finite operators. All observations are completed bars. No files/network/loops.
"""
from dataclasses import dataclass
from decimal import Decimal

from .common import canonical, decimal, digest, integer
from .errors import ValidationError
from .models import Signal

FIELDS = {"open", "high", "low", "close", "volume"}
COMPARE = {"gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below"}


def validate(raw):
    allowed = {"schema_version", "kind", "name", "long", "short", "exit_long", "exit_short", "stop", "target_fraction", "management"}
    if not isinstance(raw, dict) or set(raw)-allowed or raw.get("kind") != "STUDIO_RULES" or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValidationError("expected STUDIO_RULES schema_version 1; Python/JavaScript and unknown fields are rejected")
    if len(canonical(raw).encode()) > 12000:
        raise ValidationError("strategy definition exceeds 12KiB")
    name = raw.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c)<32 for c in name):
        raise ValidationError("name requires 1–80 printable characters")
    count = 0
    def node(x, boolean=False, depth=0):
        nonlocal count
        count += 1
        if count > 128 or depth > 8:
            raise ValidationError("strategy expression budget: 128 nodes / depth 8")
        if boolean and type(x) is bool:
            return
        if not boolean and not isinstance(x, list):
            decimal(x, "expression literal", "-1000000000", "1000000000"); return
        if not isinstance(x, list) or not x or not isinstance(x[0], str):
            raise ValidationError("invalid structured expression")
        op, args = x[0], x[1:]
        if boolean:
            if op in {"and", "or"} and 1 <= len(args) <= 8:
                for a in args: node(a, True, depth+1)
            elif op == "not" and len(args) == 1: node(args[0], True, depth+1)
            elif op in COMPARE and len(args) == 2:
                for a in args: node(a, False, depth+1)
            else: raise ValidationError("unsupported condition or arity")
        elif op in FIELDS and len(args) == 1:
            integer(args[0], "bar offset", 0, 200)
        elif op in {"sma", "atr"} and len(args) == 2:
            integer(args[0], "indicator period", 2, 200); integer(args[1], "bar offset", 0, 200)
        elif op in {"add", "sub", "mul", "div"} and len(args) == 2:
            for a in args: node(a, False, depth+1)
        else: raise ValidationError("unsupported numeric operator; no attributes, calls or executable code")
    for name in ("long", "short", "exit_long", "exit_short"):
        node(raw.get(name, False), True)
    stop = raw.get("stop")
    if not isinstance(stop, dict) or stop.get("type") not in {"fixed", "atr"}:
        raise ValidationError("stop must be fixed or atr")
    if stop["type"] == "fixed" and set(stop) == {"type", "fraction"}:
        decimal(stop["fraction"], "stop fraction", ".0001", ".5")
    elif stop["type"] == "atr" and set(stop) == {"type", "period", "multiple"}:
        integer(stop["period"], "ATR period", 2, 200); decimal(stop["multiple"], "ATR multiple", ".1", "20")
    else: raise ValidationError("invalid stop fields")
    target = raw.get("target_fraction")
    if target is not None: decimal(target, "target fraction", ".0001", ".99")
    m = raw.get("management", {})
    if not isinstance(m, dict) or set(m)-{"trailing", "partials", "max_hold_bars", "breakeven_at"}:
        raise ValidationError("unsupported position-management fields")
    if "max_hold_bars" in m: integer(m["max_hold_bars"], "max hold bars", 1, 2102400)
    if "breakeven_at" in m: decimal(m["breakeven_at"], "breakeven activation", ".0001", "10")
    if "trailing" in m:
        t = m["trailing"]
        if not isinstance(t, dict) or set(t) != {"activate_fraction", "distance_fraction"}: raise ValidationError("trailing requires activate_fraction/distance_fraction")
        decimal(t["activate_fraction"], "trail activation", ".0001", "10")
        decimal(t["distance_fraction"], "trail distance", ".0001", ".99")
    parts = m.get("partials", [])
    if not isinstance(parts, list) or len(parts)>4: raise ValidationError("at most four partial exits")
    total = Decimal(0); previous = Decimal(0)
    for p in parts:
        if not isinstance(p, dict) or set(p)!={"profit_fraction", "close_fraction"}: raise ValidationError("invalid partial exit")
        level = decimal(p["profit_fraction"], "partial threshold", ".0001", "10")
        if level <= previous: raise ValidationError("partial thresholds must strictly increase")
        previous = level; total += decimal(p["close_fraction"], "partial original quantity fraction", ".0001", ".99")
    if total >= 1: raise ValidationError("partial fractions of ORIGINAL quantity must total less than 1")
    # Copy through JSON, disallow mutable aliases and non-JSON objects.
    import json
    value = json.loads(canonical(raw))
    if warmup(value)>501: raise ValidationError("warm-up exceeds 501 completed bars")
    return value


def warmup(raw):
    def walk(x):
        if not isinstance(x, list) or not x: return 1
        if x[0] in FIELDS: return x[1]+1
        if x[0] in {"sma", "atr"}: return x[1]+x[2]+1
        return max([1]+[walk(a) for a in x[1:]])+(1 if x[0] in {"cross_above", "cross_below"} else 0)
    return max([walk(raw.get(k)) for k in ("long", "short", "exit_long", "exit_short")]+[raw["stop"].get("period", 0)+1])


def number(expr, bars, shift=0):
    if not isinstance(expr, list): return Decimal(str(expr))
    op, args = expr[0], expr[1:]
    if op in FIELDS: return getattr(bars[-1-args[0]-shift], op)
    if op in {"sma", "atr"}:
        period, offset = args; end = len(bars)-offset-shift
        if op == "sma": return sum((b.close for b in bars[end-period:end]), Decimal(0))/period
        return sum((max(bars[i].high-bars[i].low, abs(bars[i].high-bars[i-1].close), abs(bars[i].low-bars[i-1].close)) for i in range(end-period, end)), Decimal(0))/period
    a, b = (number(x, bars, shift) for x in args)
    if op == "add": return a+b
    if op == "sub": return a-b
    if op == "mul": return a*b
    if b == 0: raise ValidationError("strategy expression divides by zero; no successful result accepted")
    return a/b


def condition(expr, bars):
    if type(expr) is bool: return expr
    op, args = expr[0], expr[1:]
    if op == "and": return all(condition(a, bars) for a in args)
    if op == "or": return any(condition(a, bars) for a in args)
    if op == "not": return not condition(args[0], bars)
    a,b = (number(x,bars) for x in args)
    if op in {"cross_above", "cross_below"}:
        pa,pb = (number(x,bars,1) for x in args)
        return (pa<=pb and a>b) if op=="cross_above" else (pa>=pb and a<b)
    return {"gt":a>b, "gte":a>=b, "lt":a<b, "lte":a<=b, "eq":a==b}[op]


@dataclass(frozen=True)
class StudioStrategy:
    definition: dict
    content_hash: str
    managed: bool = True

    @property
    def warmup_bars(self): return warmup(self.definition)
    @property
    def version_id(self): return "STUDIO_RULES_"+self.content_hash

    def evaluate(self, history):
        d=self.definition; b=history[-1]; stop=d["stop"]
        fraction = Decimal(str(stop["fraction"])) if stop["type"]=="fixed" else number(["atr",stop["period"],0],history)*Decimal(str(stop["multiple"]))/b.close
        if not Decimal('.0001') <= fraction <= Decimal('.5'):
            return Signal(b.symbol,b.end_ms,"NO_SIGNAL","ATR_STOP_OUTSIDE_SUPPORTED_BOUNDS",Decimal('.0001'))
        long=condition(d.get("long",False),history); short=condition(d.get("short",False),history)
        side = "NO_SIGNAL" if long==short else ("LONG" if long else "SHORT")
        return Signal(b.symbol,b.end_ms,side,"CONFLICTING_DIRECTIONS" if long and short else "STRUCTURED_RULE",fraction,
                      None if d.get("target_fraction") is None else Decimal(str(d["target_fraction"])))


def build(raw):
    value=validate(raw)
    return StudioStrategy(value,digest(value))


EXAMPLE = {"schema_version":1,"kind":"STUDIO_RULES","name":"Editable SMA crossover example (not private HKS)",
           "long":["cross_above",["sma",5,0],["sma",20,0]],"short":False,
           "exit_long":["cross_below",["sma",5,0],["sma",20,0]],
           "stop":{"type":"fixed","fraction":"0.02"},"target_fraction":None,
           "management":{"trailing":{"activate_fraction":"0.03","distance_fraction":"0.015"},
                         "partials":[{"profit_fraction":"0.04","close_fraction":"0.25"}],"max_hold_bars":180}}
