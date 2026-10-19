"""Optional structured management; legacy Account/strategy path is unchanged.

Protective stop/target checks precede discretionary next-open actions. A closed
bar can schedule actions only for the NEXT contiguous opening boundary. Partial
threshold touches schedule market reductions, never guaranteed limit fills.
"""
from copy import copy
from decimal import Decimal

from .portfolio import Account, ZERO
from .studio_strategy import condition


class ManagedAccount(Account):
    def enter(self, *args, **kwargs):
        p,reason=super().enter(*args,**kwargs)
        if p is not None:
            p.original_quantity=p.quantity; p.partial_done=set(); p.scheduled=None
            p.stop_active_ms=p.entry_ms; p.segment=0
        return p,reason

    def close(self,p,*args,**kwargs):
        args=list(args)
        if len(args)>3 and p.stop!=p.initial_stop and args[3] in {"INITIAL_STOP","STOP_GAP"}:
            args[3]="TRAILING_STOP" if args[3]=="INITIAL_STOP" else "TRAILING_STOP_GAP"
        return super().close(p,*args,**kwargs)

    def finalize_trade(self,p,row):
        row.update(position_id=getattr(p,"position_id",p.trade_id),stop_active_ms=p.stop_active_ms,
                   exit_segment=p.segment,management_contract="COMPLETED_BAR_TO_NEXT_OPEN_V1")
        if hasattr(p,'partial_fraction'):row['partial_of_original_quantity']=str(p.partial_fraction)
        return row

    def partial(self,p,quantity,bar,config,reason='PARTIAL_THRESHOLD_NEXT_OPEN'):
        if quantity<=0 or quantity>=p.quantity: return
        piece=copy(p); ratio=quantity/p.quantity
        piece.quantity=quantity; piece.position_id=p.trade_id; p.segment+=1
        piece.partial_fraction=quantity/p.original_quantity
        piece.segment=p.segment; piece.trade_id=p.trade_id+"_part"+str(p.segment)
        for field in ("notional","margin","planned_risk","entry_fee","entry_slippage"):
            value=getattr(p,field)*ratio
            setattr(piece,field,value); setattr(p,field,getattr(p,field)-value)
        p.quantity-=quantity
        super_row=self.close(piece,bar.open,bar.open_ms,config,reason,(bar.open_ms,bar.open_ms))
        self.positions[p.symbol]=p


def at_open(account,bar,config):
    p=account.positions.get(bar.symbol)
    if p is None or not p.scheduled: return
    cmd=p.scheduled; p.scheduled=None
    if cmd["effective_ms"]!=bar.open_ms: raise ValueError("noncontiguous management action")
    # Stop ratchets are effective even on zero-volume bars; orders cannot fill.
    if cmd["stop"] is not None:
        p.stop=max(p.stop,cmd["stop"]) if p.side=="LONG" else min(p.stop,cmd["stop"])
        p.stop_active_ms=bar.open_ms
    if 'target' in cmd:p.target=cmd['target']
    p.pending_action=cmd


def after_gap(account,bar,config):
    p=account.positions.get(bar.symbol)
    if p is None: return
    cmd=getattr(p,"pending_action",None); p.pending_action=None
    if not cmd or bar.volume<=0: return
    if cmd["close"]:
        account.close(p,bar.open,bar.open_ms,config,cmd["close"],(bar.open_ms,bar.open_ms)); return
    for index,quantity in cmd["partials"]:
        account.partial(p,quantity,bar,config,reason=cmd.get('partial_reason','PARTIAL_THRESHOLD_NEXT_OPEN')); p.partial_done.add(index)


def at_close(account,bar,history,strategy):
    p=account.positions.get(bar.symbol)
    if p is None or len(history)<strategy.warmup_bars: return
    d=strategy.definition; m=d.get("management",{}); sign=1 if p.side=="LONG" else -1
    progress=p.mfe/p.entry_price
    candidate=None
    if "breakeven_at" in m and progress>=Decimal(str(m["breakeven_at"])): candidate=p.entry_price
    t=m.get("trailing")
    if t and progress>=Decimal(str(t["activate_fraction"])):
        peak=p.entry_price+sign*p.mfe
        tr=peak-sign*p.entry_price*Decimal(str(t["distance_fraction"]))
        candidate=tr if candidate is None else (max(candidate,tr) if sign==1 else min(candidate,tr))
    parts=[]
    for index,part in enumerate(m.get("partials",[])):
        if index not in p.partial_done and progress>=Decimal(str(part["profit_fraction"])):
            quantity=p.original_quantity*Decimal(str(part["close_fraction"]))
            quantity=(quantity//Decimal('0.00000001'))*Decimal('0.00000001')
            parts.append((index,quantity))
    close=None
    if condition(d.get("exit_long" if sign==1 else "exit_short",False),history): close="STRATEGY_EXIT_NEXT_OPEN"
    if m.get("max_hold_bars") and bar.end_ms-p.entry_ms>=m["max_hold_bars"]*bar.interval_ms: close="MAX_HOLD_NEXT_OPEN"
    p.scheduled={"effective_ms":bar.end_ms,"stop":candidate,"partials":parts,"close":close}
