"""Parse metadata/syntax only. User Python is NEVER evaluated in this module."""
import ast
from dataclasses import dataclass
from decimal import Decimal

from .common import digest
from .errors import ValidationError
from .models import Signal


def validate(raw):
    if not isinstance(raw,dict) or set(raw)!={'schema_version','kind','name','code'} or raw.get('kind')!='PYTHON_STRATEGY' or type(raw.get('schema_version')) is not int or raw['schema_version']!=1:
        raise ValidationError('expected PYTHON_STRATEGY/1 with name and code')
    name,code=raw['name'],raw['code']
    if not isinstance(name,str) or not 1<=len(name)<=80 or any(ord(c)<32 for c in name):raise ValidationError('strategy name requires 1–80 printable characters')
    if not isinstance(code,str) or not code.strip() or len(code.encode())>12000:raise ValidationError('Python source requires 1–12000 UTF-8 bytes')
    try:tree=ast.parse(code,filename='strategy.py')
    except (SyntaxError,ValueError) as e:raise ValidationError('Python syntax error at line '+str(getattr(e,'lineno','?'))+': '+str(getattr(e,'msg','invalid source'))) from None
    if not any(isinstance(n,ast.FunctionDef) and n.name=='on_bar' and len(n.args.args)==1 and not n.args.vararg and not n.args.kwarg for n in tree.body):
        raise ValidationError('define on_bar(ctx) with one argument; Python executes only in the isolated runner')
    warmup=100
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WARMUP_BARS' for t in n.targets):
            if not isinstance(n.value,ast.Constant) or type(n.value.value) is not int or not 2<=n.value.value<=501:raise ValidationError('WARMUP_BARS must be a literal integer from 2 to 501')
            warmup=n.value.value
    return {'schema_version':1,'kind':'PYTHON_STRATEGY','name':name,'code':code},warmup


@dataclass(frozen=True)
class PythonSpec:
    definition:dict
    content_hash:str
    warmup_bars:int
    @property
    def version_id(self):return 'PYTHON_V1_'+self.content_hash
    def evaluate(self,history):raise ValidationError('Python requires the verified isolated container runner; no host execution fallback')


@dataclass(frozen=True)
class PythonSignal(Signal):
    stop_rule:tuple|None=None
    target_rule:tuple|None=None


def build(raw):
    definition,warmup=validate(raw)
    return PythonSpec(definition,digest(definition),warmup)


TEMPLATE='''from decimal import Decimal as D

WARMUP_BARS = 51

def on_bar(ctx):
    # All history is completed candles. No future candles are supplied.
    fast = ctx.sma(10)
    slow = ctx.sma(50)
    atr = ctx.atr(14)
    p = ctx.position
    if p is None:
        if atr <= 0:
            return None
        if fast > slow and ctx.close > ctx.history[-2].close:
            return ctx.enter("LONG", stop_distance=2 * atr, target_distance=4 * atr)
        # SHORT is supported only in diagnostic Futures, never ordinary Spot.
        return None
    if p.side == "LONG" and fast < slow:
        return ctx.exit()
    # Custom Python indicators and state are allowed inside the OS sandbox.
    if p.quantity == p.original_quantity and p.unrealized_fraction >= D("0.03"):
        return ctx.manage(reduce_fraction=D("0.25"), stop=max(p.stop, p.entry_price))
    if p.side == "LONG":
        return ctx.manage(stop=max(p.stop, ctx.close - 2 * atr))
    return ctx.manage(stop=min(p.stop, ctx.close + 2 * atr))
'''
