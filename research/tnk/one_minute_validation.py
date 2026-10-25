"""Research only: TNK MEXC Spot 1m vs 5m stop/trailing validation.
Historical public candles, isolated temp SQLite, imported actual HKS SMC and
actual HKS trail_stop/get_stop_fill; no live positions or changes to app.py.
"""
from __future__ import annotations
import bisect,json,os,statistics,sys,tempfile,time
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import requests
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
tmp=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(tmp.name)/"separate_1m_research.sqlite3")
os.environ.pop("VERCEL",None)
import app as hks
S=requests.Session()
S.headers["User-Agent"]="HKS-TNK-Research-Safe-MEXC-Candles"
END=datetime(2026,10,24,tzinfo=timezone.utc)
START=datetime(2026,9,25,tzinfo=timezone.utc)
WARM=START-timedelta(days=4)
def ms(x):return int(x.timestamp()*1000)
def iso(x):return datetime.fromtimestamp(x/1000,timezone.utc).strftime("%Y-%m-%d %H:%M")
def emit(tag,d):print("RESEARCH_"+tag+" "+json.dumps(d,default=str,separators=(",",":")),flush=True)
def candles(interval,from_ms,to_ms,step):
    rows={};cursor=from_ms;pages=0
    while cursor<to_ms:
        for attempt in range(4):
            try:
                r=S.get("https://api.mexc.com/api/v3/klines",
                  params={"symbol":"TNKUSDT","interval":interval,"startTime":cursor,"endTime":to_ms-1,"limit":1000},timeout=22)
                r.raise_for_status()
                vals=r.json()
                if not isinstance(vals,list):raise RuntimeError(str(vals)[:180])
                break
            except Exception as e:
                if attempt==3:raise
                time.sleep(attempt+1)
        if not vals:break
        valid=[x for x in vals if isinstance(x,list) and len(x)>=8 and cursor<=int(x[0])<to_ms]
        if not valid:break
        for x in valid:rows[int(x[0])]=x
        new=max(int(x[0]) for x in valid)+step
        if new<=cursor:break
        cursor=new;pages+=1
        if pages%30==0:print("FETCH",interval,pages,len(rows),flush=True)
        time.sleep(.06)
    out=[]
    for t,x in sorted(rows.items()):
        o,h,l,c,v,q=map(D,[x[1],x[2],x[3],x[4],x[5],x[7]])
        if not (o>0 and l>0 and l<=min(o,c,h) and h>=max(o,c,l)):raise RuntimeError("invalid MEXC bar")
        out.append({"t":t,"end":t+step,"o":o,"h":h,"l":l,"c":c,"v":v,"q":q})
    expected=(to_ms-from_ms)//step
    gaps=sum(y["t"]!=x["end"] for x,y in zip(out,out[1:]))
    stat={"from":iso(out[0]["t"]) if out else None,
      "to":iso(out[-1]["t"]) if out else None,"rows":len(out),
      "expected":expected,"coverage_pct":round(100*len(out)/expected,3),
      "gaps":gaps,"pages":pages,"first_gap":next((iso(x["end"]) for x,y in zip(out,out[1:]) if y["t"]!=x["end"]),None)}
    emit("COVERAGE_"+interval,stat)
    return out,stat

# 15m and 60m add 4d of warmup; 1m only for recent 29d.
q,qs=candles("15m",ms(WARM),ms(END),900000)
h,hs=candles("60m",ms(WARM),ms(END),3600000)
m1,ms1=candles("1m",ms(START),ms(END),60000)
m5,ms5=candles("5m",ms(START),ms(END),300000)
# Strict no extrapolation; do not call missing minutes fake historical bars.
if ms1["coverage_pct"]<99.9 or ms1["gaps"] or ms1["rows"]!=ms1["expected"]:
    emit("HALT",{"reason":"1m historical coverage incomplete; no robust 1m replay authorized",
                  "data":ms1})
    raise SystemExit(0)
if qs["coverage_pct"]<99.9 or hs["coverage_pct"]<99.9 or ms5["coverage_pct"]<99.9:raise SystemExit("Other interval incomplete")
# Compare MEXC native 5m OHLC with 5 contiguous 1m OHLC for provenance.
by_t={b["t"]:b for b in m1}
checked=mismatch=0
for b in m5:
    sub=[by_t.get(b["t"]+k*60000) for k in range(5)]
    if any(x is None for x in sub):continue
    checked+=1
    exp=(sub[0]["o"],max(x["h"] for x in sub),min(x["l"] for x in sub),sub[-1]["c"])
    actual=(b["o"],b["h"],b["l"],b["c"])
    if exp!=actual:
        mismatch+=1
        if mismatch<=4:emit("OHLC_MISMATCH",{"t":iso(b["t"]),"reconstructed":list(map(str,exp)),"native":list(map(str,actual))})
emit("OHLC_VALIDATION",{"checked_5m_bars":checked,"mismatched":mismatch})

q_ends=[x["end"] for x in q];h_ends=[x["end"] for x in h]
signals=[]
for i in range(34,len(q)):
    if q[i]["end"]<ms(START) or q[i]["end"]>=ms(END):continue
    t=q[i]["end"]
    bars=q[i-34:i+1]
    j=bisect.bisect_right(h_ends,t)
    hours=h[j-25:j]
    if len(hours)<25:continue
    if any(b["end"]!=c["t"] for b,c in zip(bars,bars[1:])):continue
    if any(b["end"]!=c["t"] for b,c in zip(hours,hours[1:])):continue
    data=hks.evaluate_smc(bars,hours,t)
    if data["original"] and data["trade_score"]>=75:
        signals.append({"t":t,"score":data["trade_score"],"side":data["original"],"sl":data["stop_fraction"]})
emit("SIGNALS",{"count":len(signals),"long":sum(x["side"]=="LONG" for x in signals),
               "reverse_eligible":sum(x["side"]=="SHORT" for x in signals),
               "signals":[{"t":iso(x["t"]),"side":x["side"],"score":x["score"],"SLpct":round(float(x["sl"]*100),3)} for x in signals]})

def run_model(bars,step,mode,cost):
    times=[b["t"] for b in bars]
    equity=D(1000)
    active_until=ms(START)
    out=[]
    per_side=D(str(cost))/2
    for sig in signals:
        if (sig["side"]=="LONG")!=(mode=="NORMAL"):continue
        t=sig["t"]
        if t<active_until:continue
        k=bisect.bisect_left(times,t)
        if k>=len(bars) or bars[k]["t"]!=t:continue
        entry=bars[k]["o"];sl=sig["sl"]
        cap=min(equity*D(".01")/sl,equity*D("0.3333333333")/(D(1)+per_side))
        qty=cap/entry
        initial=entry*(1-sl)
        pos=SimpleNamespace(direction="LONG",entry_price=entry,stop=initial,
           initial_stop=initial,reference_distance=2*entry*sl)
        pre_high=entry;pre_low=entry
        bar_high=entry;bar_low=entry
        finish=None
        prev_t=t-step
        for b in bars[k:]:
            if b["t"]!=prev_t+step:break
            prev_t=b["t"]
            fill=hks.get_stop_fill(pos,b)
            if fill is not None:
                finish={"exit":fill,"exit_t":b["end"],"reason":"TRAILING" if pos.stop!=pos.initial_stop else "INITIAL",
                  "stop_before_exit":pos.stop,"candle_open":b["o"],"candle_high":b["h"],"candle_low":b["l"],
                  "candle_close":b["c"],"prior_peak":pre_high,"prior_trough":pre_low,
                  "envelope_peak":max(pre_high,b["h"],fill),"envelope_trough":min(pre_low,b["l"],fill)}
                break
            pre_high=max(pre_high,b["h"]);pre_low=min(pre_low,b["l"])
            hks.trail_stop(pos,b["h"])
        if finish is None:continue
        gross=(finish["exit"]-entry)*qty
        fee=per_side*(cap+finish["exit"]*qty)
        net=gross-fee
        equity+=net
        active_until=finish["exit_t"]
        out.append({"time":iso(t),"exit_time":iso(finish["exit_t"]),"entry":round(float(entry),8),
          "exit":round(float(finish["exit"]),8),"score":sig["score"],
          "initial_SL_pct":round(float(sl*100),3),
          "stop_at_exit":round(float(finish["stop_before_exit"]),8),
          "exit_candle_open":round(float(finish["candle_open"]),8),
          "exit_candle_low":round(float(finish["candle_low"]),8),
          "MFE_certified_gross_pct":round(100*float((finish["prior_peak"]/entry)-1),3),
          "MFE_envelope_gross_pct":round(100*float((finish["envelope_peak"]/entry)-1),3),
          "MAE_certified_gross_pct":round(100*float(1-(finish["prior_trough"]/entry)),3),
          "MAE_envelope_gross_pct":round(100*float(1-(finish["envelope_trough"]/entry)),3),
          "notional":round(float(cap),4),"net":round(float(net),4),
          "net_R":round(float(net/(cap*sl)),3),
          "wallet":round(float(equity),3),"reason":finish["reason"]})
    return {"period":"2026-09-25..2026-10-23","granularity_minutes":step//60000,"mode":mode,
            "round_trip_cost_pct":cost*100,"trades":len(out),"wins":sum(x["net"]>0 for x in out),
            "return_pct":round(float((equity/D(1000)-1)*100),3),"positions":out}
for mode in ("NORMAL","REVERSE"):
    for cost in (.002,.005):
        for step,bars in ((60000,m1),(300000,m5)):
            res=run_model(bars,step,mode,cost)
            emit("MODEL",res)
emit("DONE",{"note":"A 1m OHLC still cannot order intraminute high/low; modeled fill may differ from real exchange, no execution or orderbook verification"})
