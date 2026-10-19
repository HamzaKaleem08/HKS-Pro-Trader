"""Runs ONLY inside the unprivileged, secret-free, network-disabled container.

No application imports, database client or project mount is present here.
Security is the container boundary, not restrictions on Python builtins/AST.
"""
from collections import deque,namedtuple
from decimal import Decimal,localcontext
import contextlib
import json
import os
import sys
from types import SimpleNamespace

Candle=namedtuple('Candle','symbol open_ms interval_ms open high low close volume')


def encode(x):
    if isinstance(x,Decimal):return str(x)
    raise TypeError('strategy decisions must be dictionaries containing finite numbers, strings, booleans or null')


class Context:
    def __init__(self,row,history,state):
        self.symbol=row['symbol'];self.history=tuple(history);self.state=state
        self.bar=history[-1];self.close=self.bar.close;self.timestamp_ms=self.bar.open_ms+self.bar.interval_ms
        self.account=SimpleNamespace(**{k:Decimal(str(v)) for k,v in row['account'].items()})
        self.position=None
        if row['position']:
            p=dict(row['position'])
            for k in ['entry_price','quantity','original_quantity','stop','initial_stop','unrealized_fraction','planned_risk','mfe','mae']:
                p[k]=Decimal(str(p[k]))
            if p.get('target') is not None:p['target']=Decimal(str(p['target']))
            self.position=SimpleNamespace(**p)
            key=p['trade_id']
        else:key=None
        if state.get('__position_id')!=key:state.clear();state['__position_id']=key

    def sma(self,period):
        if type(period) is not int or not 1<=period<=len(self.history):raise ValueError('SMA period exceeds supplied completed history; increase WARMUP_BARS')
        return sum((b.close for b in self.history[-period:]),Decimal(0))/period

    def atr(self,period):
        if type(period) is not int or not 1<=period<len(self.history):raise ValueError('ATR needs period+1 completed candles; increase WARMUP_BARS')
        h=self.history
        return sum((max(h[i].high-h[i].low,abs(h[i].high-h[i-1].close),abs(h[i].low-h[i-1].close)) for i in range(len(h)-period,len(h))),Decimal(0))/period

    def enter(self,side,*,stop_fraction=None,stop_distance=None,stop_price=None,target_fraction=None,target_distance=None,target_price=None):
        def rule(fraction,distance,price,required):
            fields=[(k,v) for k,v in [('fraction',fraction),('distance',distance),('price',price)] if v is not None]
            if not fields and not required:return None
            if len(fields)!=1:raise ValueError('choose exactly one stop/target fraction, distance or absolute price')
            k,v=fields[0];return {'mode':k,'value':str(v)}
        return {'enter':{'side':side,'stop':rule(stop_fraction,stop_distance,stop_price,True),'target':rule(target_fraction,target_distance,target_price,False)}}

    def exit(self):return {'close':True}
    def manage(self,**kwargs):return kwargs


def send(value):
    text=json.dumps(value,default=encode,separators=(',',':'),allow_nan=False)
    if len(text.encode())>65536:raise ValueError('strategy response exceeds 64KiB')
    sys.stdout.write(text+'\n');sys.stdout.flush()


def main():
    histories={};states={}
    namespace={'__name__':'strategy','__file__':'/strategy.py'}
    try:
        # User stdout cannot corrupt normal protocol output. Direct os.write is
        # still untrusted protocol input and is rejected/bounded by the broker.
        with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink):
            exec(compile(open('/strategy.py').read(),'strategy.py','exec'),namespace)
        if not callable(namespace.get('on_bar')):raise ValueError('on_bar(ctx) is not callable')
        warmup=namespace.get('WARMUP_BARS',100)
        if type(warmup) is not int or not 2<=warmup<=501:raise ValueError('WARMUP_BARS must remain a literal integer from 2 to 501')
        send({'ready':True,'api':'HKS_PYTHON/1','warmup_bars':warmup})
    except BaseException as e:
        send({'error':type(e).__name__+': '+str(e)[:500]});return
    for line in sys.stdin.buffer:
        sequence=None
        try:
            if len(line)>512*1024:raise ValueError('input frame exceeds 512KiB')
            row=json.loads(line);sequence=row['seq'];sym=row['symbol']
            h=histories.setdefault(sym,deque(maxlen=warmup))
            for b in row['bars']:
                candle=Candle(sym,b['open_ms'],b['interval_ms'],*(Decimal(b[k]) for k in ['open','high','low','close','volume']))
                if h and candle.open_ms!=h[-1].open_ms+h[-1].interval_ms:raise ValueError('noncontiguous completed history')
                h.append(candle)
            if len(h)<warmup:raise ValueError('insufficient completed warm-up')
            with localcontext() as ctx:
                ctx.prec=34
                context=Context(row,h,states.setdefault(sym,{}))
                with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink):decision=namespace['on_bar'](context)
            send({'seq':sequence,'decision':decision})
        except BaseException as e:
            send({'seq':sequence,'error':type(e).__name__+': '+str(e)[:500]});return


if __name__=='__main__':main()
