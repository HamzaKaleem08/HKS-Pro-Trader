"""Exploratory CYS MEXC Spot 180d 5m OHLC proxy exit replay.
Genuine 5m MEXC candles; old genuine 1m not free. No paid data/real orders.
200% initial ATR SL, original undisturbed HKS trailing virtual 2R.
"""
from __future__ import annotations
import bisect,os,sys,tempfile,json,time
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import requests

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
TMP=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(TMP.name)/"cys_isolated_5m_proxy.sqlite3")
os.environ.pop("VERCEL",None)
import app as hks

SYM="CYSUSDT"
START=datetime(2026,4,27,tzinfo=timezone.utc)
END=datetime(2026,10,24,tzinfo=timezone.utc)
WARM=START-timedelta(days=4)
TO_MS=lambda x:int(x.timestamp()*1000)
FMT=lambda t:datetime.fromtimestamp(t/1000,timezone.utc).strftime("%Y-%m-%d %H:%M")
S=requests.Session()
S.headers["User-Agent"]="HKS-Bot2-CYS-5m-Proxy-Research-Only"
def log(phase,**kw):
    print("CYS180 "+json.dumps({"phase":phase,**kw},default=str,separators=(",",":")),flush=True)

def get(interval,from_date,to_date,step):
    begin=TO_MS(from_date);end=TO_MS(to_date);cursor=begin;data={}
    while cursor<end:
        for attempt in range(4):
            try:
                r=S.get("https://api.mexc.com/api/v3/klines",timeout=23,params={
                    "symbol":SYM,"interval":interval,"startTime":cursor,"endTime":end-1,"limit":1000})
                r.raise_for_status()
                raw=r.json()
                if not isinstance(raw,list):
                    raise RuntimeError("invalid MEXC "+str(raw)[:140])
                break
            except Exception:
                if attempt==3:raise
                time.sleep(1+attempt)
        if not raw:break
        items=[a for a in raw if isinstance(a,list) and len(a)>=8 and cursor<=int(a[0])<end]
        if not items:break
        for z in items:data[int(z[0])]=z
        nxt=max(int(x[0]) for x in items)+step
        if nxt<=cursor:raise RuntimeError("pagination loop")
        cursor=nxt
        if len(data)%10000<1000:print("CYS_FETCH",interval,len(data),flush=True)
        time.sleep(.045)
    bars=[]
    for t,x in sorted(data.items()):
        o,h,l,c=map(D,[x[1],x[2],x[3],x[4]])
        if not(o>0 and l>0 and l<=min(o,h,c) and h>=max(o,l,c)):
            raise RuntimeError("invalid OHLC "+FMT(t))
        bars.append({"t":t,"end":t+step,"o":o,"h":h,"l":l,"c":c})
    expected=(end-begin)//step
    good=(len(bars)==expected and
          (not bars or (bars[0]["t"]==begin and bars[-1]["end"]==end)) and
          all(x["end"]==y["t"] for x,y in zip(bars,bars[1:])))
    log("coverage",interval=interval,count=len(bars),expected=expected,gap_free=good,
        first=FMT(bars[0]["t"]) if bars else None,
        last=FMT(bars[-1]["t"]) if bars else None)
    return bars,good

q,qok=get("15m",WARM,END,900000)
h,hok=get("60m",WARM,END,3600000)
bars,ok=get("5m",START,END,300000)
if not(qok and hok and ok):
    log("HALT",cause="Incomplete real historical candle coverage",q=qok,h=hok,m5=ok)
    raise SystemExit(2)
ts=[b["end"] for b in h]
signals=[]
for i in range(34,len(q)):
    t=q[i]["end"]
    if not TO_MS(START)<=t<TO_MS(END):continue
    last35=q[i-34:i+1]
    j=bisect.bisect_right(ts,t)
    last25=h[j-25:j]
    if len(last25)!=25:continue
    if any(a["end"]!=b["t"] for a,b in zip(last35,last35[1:])):raise RuntimeError("15m gap")
    if any(a["end"]!=b["t"] for a,b in zip(last25,last25[1:])):raise RuntimeError("1h gap")
    ev=hks.evaluate_smc(last35,last25,t)
    if ev["original"]=="LONG" and ev["trade_score"]>=75:
        signals.append({"t":t,"score":ev["trade_score"],"sl":ev["stop_fraction"]})
log("signals",long75=sum(x["score"]>=75 for x in signals),
    long85=sum(x["score"]>=85 for x in signals),
    at85=[{"time":FMT(x["t"]),"score":x["score"],"baselineSLpct":round(float(x["sl"]*100),3)}
        for x in signals if x["score"]>=85])
assert sum(x["score"]>=85 for x in signals)==5,"unexpected recent 180d signal count"
index=[b["t"] for b in bars]

def run(min_score,initial_sl_factor,cost):
    balance=D(1000)
    side_fee=D(str(cost))/2
    locked_until=0
    result=[]
    for s in signals:
        if s["score"]<min_score or s["t"]<locked_until:continue
        i=bisect.bisect_left(index,s["t"])
        if i>=len(bars) or bars[i]["t"]!=s["t"]:continue
        entry=bars[i]["o"]
        sl_ref=entry*s["sl"]
        init_sl=sl_ref*D(str(initial_sl_factor))
        pos=SimpleNamespace(direction="LONG",entry_price=entry,
                            initial_stop=entry-init_sl,stop=entry-init_sl,
                            reference_distance=sl_ref*2)
        notional=min(D(250),balance/(1+side_fee))
        if notional<=D(5):break
        max_hi=entry
        min_lo=entry
        exit_data=None
        lastend=s["t"]
        for b in bars[i:]:
            if b["t"]!=lastend:
                log("MODEL_HALT",reason="5m continuity gap",entry=FMT(s["t"]))
                raise SystemExit(2)
            lastend=b["end"]
            fill=hks.get_stop_fill(pos,b)
            if fill is not None:
                exit_data={"price":fill,"t":b["end"],"reason":"INITIAL" if pos.stop==pos.initial_stop else "TRAIL",
                           "bar_open":b["o"],"bar_high":b["h"],"bar_low":b["l"],
                           "last_stop":pos.stop,"mfe_before_exitbar":max_hi,
                           "mae_before_exitbar":min_lo}
                break
            max_hi=max(max_hi,b["h"])
            min_lo=min(min_lo,b["l"])
            hks.trail_stop(pos,b["h"])
        if exit_data is None:
            log("OPEN_AT_WINDOW_END",entry=FMT(s["t"]))
            continue
        exitprice=exit_data["price"]
        qty=notional/entry
        gross=(exitprice-entry)*qty
        fees=side_fee*(notional+exitprice*qty)
        net=gross-fees
        balance+=net
        locked_until=exit_data["t"]
        result.append({"entry":FMT(s["t"]),"exit":FMT(exit_data["t"]),
                       "entry_price":round(float(entry),9),"exit_price":round(float(exitprice),9),
                       "score":s["score"],"original_stop_pct":round(float(s["sl"]*100),4),
                       "initial_stop_pct":round(float(s["sl"]*100*D(str(initial_sl_factor))),4),
                       "reason":exit_data["reason"],"net_usd":round(float(net),4),
                       "wallet_usd":round(float(balance),4),
                       "mfe_preexit_5m_pct":round(float((max_hi/entry-1)*100),3),
                       "mae_preexit_5m_pct":round(float((min_lo/entry-1)*100),3),
                       "last_bar_open":round(float(exit_data["bar_open"]),9),
                       "last_stop":round(float(exit_data["last_stop"]),9)})
    return {"trades":len(result),"wins":sum(x["net_usd"]>0 for x in result),
            "net_usd":round(float(balance-1000),4),
            "wallet_return_pct":round(float((balance/1000-1)*100),4),
            "biggest_net_win_usd":max([0]+[x["net_usd"] for x in result]),
            "records":result}

for threshold in (75,85):
    for factor in (1,1.5,2):
        for cost in (.002,.005,.01):
            x=run(threshold,factor,cost)
            log("scenario",score_min=threshold,sl_factor=factor,total_cost_pct=round(cost*100,2),
                **{k:v for k,v in x.items() if k!="records"})
            if cost==.005:
                log("trades",score_min=threshold,sl_factor=factor,total_cost_pct=0.5,records=x["records"])
log("done",disclaimer="5m OHLC-only proxy, not genuine 1m exits and not fills. Intra-5m high-low chronology unknown; original production trailing formula preserved. Research-only.")
