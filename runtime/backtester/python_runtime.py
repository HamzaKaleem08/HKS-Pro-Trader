"""Trusted decision validator; user code runs across inherited container pipes."""
from dataclasses import asdict
from decimal import Decimal
import os

from .common import decimal,primitives
from .errors import ValidationError
from .python_definition import build,PythonSignal
from .python_sandbox import RPC


class PythonRuntime:
    managed=True
    python_runtime=True
    def __init__(self,definition):
        spec=build(definition)
        self.definition=spec.definition;self.content_hash=spec.content_hash;self.version_id=spec.version_id;self.warmup_bars=spec.warmup_bars
        try:read=int(os.environ['HKS_SANDBOX_READ_FD']);write=int(os.environ['HKS_SANDBOX_WRITE_FD'])
        except (KeyError,ValueError):raise ValidationError('isolated Python channel missing; ordinary subprocess execution is forbidden') from None
        self.rpc=RPC(read,write);self.previous={};self.signals={}

    def after_close(self,account,bar,history):
        if len(history)<self.warmup_bars:return
        previous=self.previous.get(bar.symbol)
        if previous is not None and bar.open_ms!=previous+bar.interval_ms:raise ValidationError('Python observation chronology mismatch')
        rows=history if previous is None else (bar,)
        position=account.positions.get(bar.symbol)
        p=None
        if position:
            p={k:getattr(position,k) for k in ['trade_id','side','entry_ms','entry_price','quantity','stop','initial_stop','target','planned_risk','mfe','mae']}
            p['original_quantity']=getattr(position,'original_quantity',position.quantity)
            p['unrealized_fraction']=(bar.close-position.entry_price)/position.entry_price*(1 if position.side=='LONG' else -1)
        decision=self.rpc.call({'symbol':bar.symbol,'bars':primitives([asdict(b) for b in rows]),'position':primitives(p),
                                'account':primitives({'equity':account.equity(),'cash':account.cash,'reserved_capital':account.reserved(),'reserved_risk':account.reserved_risk()})})
        self.previous[bar.symbol]=bar.open_ms
        self.signals[bar.symbol]=self.validate(decision,position,bar)

    def validate(self,decision,p,bar):
        decision={} if decision is None else decision
        if not isinstance(decision,dict) or set(decision)-{'enter','close','reduce_fraction','stop','target'}:raise ValidationError('on_bar must return None or supported entry/close/reduction/stop/target actions')
        side='NO_SIGNAL';stop=None;target=None
        entry=decision.get('enter')
        if entry is not None:
            if not isinstance(entry,dict) or set(entry)!={'side','stop','target'} or entry['side'] not in {'LONG','SHORT'}:raise ValidationError('use ctx.enter(LONG/SHORT, stop_..., target_...)')
            side=entry['side']
            def rule(value,required):
                if value is None and not required:return None
                if not isinstance(value,dict) or set(value)!={'mode','value'} or value['mode'] not in {'fraction','distance','price'}:raise ValidationError('stop/target requires fraction, distance or price')
                v=decimal(value['value'],'Python stop/target','.000000000000000001','1000000000000000')
                if value['mode']=='fraction' and v>Decimal('2'):raise ValidationError('fraction exceeds supported 2x price distance')
                return value['mode'],v
            stop=rule(entry['stop'],True);target=rule(entry['target'],False)
        manage=set(decision)-{'enter'}
        if manage:
            if p is None:raise ValidationError('position-management action requires an actual open position')
            if 'close' in decision and decision['close'] is not True:raise ValidationError('close action must be true')
            if 'close' in decision and 'reduce_fraction' in decision:raise ValidationError('choose close or reduce_fraction, not both')
            candidate=None;partials=[];close='PYTHON_EXIT_NEXT_OPEN' if decision.get('close') else None
            if 'stop' in decision:
                candidate=decimal(decision['stop'],'updated stop','.000000000000000001','1000000000000000')
                if (p.side=='LONG' and candidate<p.stop) or (p.side=='SHORT' and candidate>p.stop):raise ValidationError('stop loosening is forbidden; use max/min of the active stop and your candidate')
            if 'reduce_fraction' in decision:
                fraction=decimal(decision['reduce_fraction'],'position reduction','.00000001','1')
                if fraction==1:close='PYTHON_EXIT_NEXT_OPEN'
                else:
                    quantity=(p.quantity*fraction//Decimal('.00000001'))*Decimal('.00000001')
                    if quantity<=0 or quantity>=p.quantity:raise ValidationError('position reduction rounds to unsupported simulator quantity')
                    partials=[(('PYTHON',bar.end_ms),quantity)]
            command={'effective_ms':bar.end_ms,'stop':candidate,'partials':partials,'close':close,'partial_reason':'PYTHON_REDUCTION_NEXT_OPEN'}
            if 'target' in decision:
                value=decision['target']
                value=None if value is None else decimal(value,'updated target','.000000000000000001','1000000000000000')
                if value is not None and ((p.side=='LONG' and value<=p.entry_price) or (p.side=='SHORT' and value>=p.entry_price)):raise ValidationError('target must be on the profitable side of entry')
                command['target']=value
            p.scheduled=command
        return PythonSignal(bar.symbol,bar.end_ms,side,'PYTHON_ON_COMPLETED_BAR',Decimal('.0001'),None,stop,target)

    def evaluate(self,history):
        b=history[-1]
        try:return self.signals.pop(b.symbol)
        except KeyError:raise ValidationError('Python evaluation was not supplied a causal account snapshot') from None
