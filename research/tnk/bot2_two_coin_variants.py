"""Bot 2 / MEXC Spot research: TNKUSDT and CYSUSDT, long-only.
Isolated from production. Existing HKS SMC scoring & baseline trailing imported
unaltered. Genuine exchange 1m; no candles manufactured. No API credentials.
Period: 2026-09-25 00:00 to 2026-10-24 00:00 UTC, inclusive 29 full days.
"""
from __future__ import annotations
import bisect,json,os,sys,tempfile,time,statistics
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import requests
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE))
tmp=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(tmp.name)/"isolated.sqlite3")
os.environ.pop("VERCEL",None)
import app as hks
S=requests.Session()
S.headers.update({"User-Agent":"HKS-Bot2-MEXC-Public-Research-1.0"})
START=datetime(2026,9,25,tzinfo=timezone.utc)
END=datetime(2026,10,24,tzinfo=timezone.utc)
WARM=START-timedelta(days=4)
EPOCH=lambda dt:int(dt.timestamp()*1000)
TS=lambda t:datetime.fromtimestamp(t/1000,timezone.utc).strftime("%Y-%m-%d %H:%M")
def emit(kind,obj):print("B2_RESULT "+json.dumps({"phase":kind,**obj},default=str,separators=(",",":")),flush=True)
def fetch(sym,interval,start,end,step,expect=None):
    cur=EPOCH(start);limit=EPOCH(end);data={};pg=0
    while cur<limit:
        for attempt in range(4):
            try:
                r=S.get("https://api.mexc.com/api/v3/klines",params={"symbol":sym,"interval":interval,
                    "startTime":cur,"endTime":limit-1,"limit":1000},timeout=22)
                r.raise_for_status();payload=r.json()
                if not isinstance(payload,list):raise RuntimeError(str(payload)[:200])
                break
            except Exception as ex:
                if attempt==3:raise
                time.sleep(.8*(attempt+1))
        if not payload:break
        rows=[x for x in payload if len(x)>=8 and cur<=int(x[0])<limit]
        if not rows:break
        for x in rows:data[int(x[0])]=x
        nxt=max(int(x[0]) for x in rows)+step
        if nxt<=cur:raise RuntimeError("stuck pagination")
        cur=nxt;pg+=1
        if pg%25==0:print("B2_PROGRESS",sym,interval,"pages",pg,"bars",len(data),flush=True)
        time.sleep(.045)
    arr=[]
    for t,x in sorted(data.items()):
        o,h,l,c,v,q=[D(x[i]) for i in (1,2,3,4,5,7)]
        if not(o>0 and l>0 and l<=min(o,c,h) and h>=max(o,c,l)):raise RuntimeError("Invalid MEXC candle "+TS(t))
        arr.append({"t":t,"end":t+step,"o":o,"h":h,"l":l,"c":c,"q":q})
    expected=(limit-EPOCH(start))//step
    is_complete=len(arr)==expected and (not arr or (arr[0]["t"]==EPOCH(start) and
        arr[-1]["end"]==limit and all(x["end"]==y["t"] for x,y in zip(arr,arr[1:]))))
    emit("coverage",{"symbol":sym,"interval":interval,"rows":len(arr),"expected":expected,
                    "complete":is_complete,"first":TS(arr[0]["t"]) if arr else None,
                    "last":TS(arr[-1]["t"]) if arr else None})
    return arr,is_complete
def metadata(sym):
    try:
        r=S.get("https://api.mexc.com/api/v3/exchangeInfo",params={"symbol":sym},timeout=15)
        ans=r.json()
        rows=ans.get("symbols",[])
        emit("symbol_info",{"symbol":sym,"status":r.status_code,"entries":[{
            k:y.get(k) for k in ("symbol","status","baseAsset","quoteAsset","isSpotTradingAllowed","isMarginTradingAllowed")
            } for y in rows[:3]],"error":ans if not rows else None})
    except Exception as exc:emit("symbol_info_error",{"symbol":sym,"error":str(exc)[:220]})

def signals_for(q,h):
    ends=[x["end"] for x in h]
    all_sigs=[]
    for i in range(34,len(q)):
        b=q[i];t=b["end"]
        if not EPOCH(START)<=t<EPOCH(END):continue
        fifteen=q[i-34:i+1]
        j=bisect.bisect_right(ends,t);hours=h[j-25:j]
        if len(hours)<25:continue
        if any(a["end"]!=z["t"] for a,z in zip(fifteen,fifteen[1:])):continue
        if any(a["end"]!=z["t"] for a,z in zip(hours,hours[1:])):continue
        ev=hks.evaluate_smc(fifteen,hours,t)
        if ev["original"] and ev["trade_score"]>=75:
            all_sigs.append({"t":t,"side":ev["original"],"score":ev["trade_score"],"sl":ev["stop_fraction"]})
    return all_sigs

# Fixed notional across all stop variants: tightening SL must actually reduce
# USD risk, not silently increase size to maintain constant 1%-wallet risk.
NOTIONAL=D("250")
def replay(m1,sigs,threshold,sl_mult,trailer,cost):
    times=[x["t"] for x in m1]
    wallet=D(1000);closed=[];busy_until=0
    side_cost=D(str(cost))/2
    for sig in sigs:
        if sig["side"]!="LONG" or sig["score"]<threshold or sig["t"]<busy_until:continue
        k=bisect.bisect_left(times,sig["t"])
        if k>=len(m1) or m1[k]["t"]!=sig["t"]:continue
        entry=m1[k]["o"];frac=sig["sl"]*D(str(sl_mult))
        size=min(NOTIONAL,wallet/(D(1)+side_cost))
        if size<D(5):break
        qty=size/entry
        initial=entry*(1-frac)
        # "coupled": trailing reference resets to tightened stop, like existing HKS
        # "decoupled": trailing reference stays original 2R, to isolate stop effect
        ref=2*entry*(sig["sl"] if trailer=="decoupled" else frac)
        pos=SimpleNamespace(direction="LONG",entry_price=entry,initial_stop=initial,stop=initial,
                            reference_distance=ref)
        highest=entry;lowest=entry;oldend=sig["t"];exit=None
        for i in range(k,len(m1)):
            b=m1[i]
            if b["t"]!=oldend:break
            oldend=b["end"]
            fill=hks.get_stop_fill(pos,b)
            if fill is not None:
                # exclude exit bar high/low, ordering unknown
                exit={"px":fill,"end":b["end"],"reason":"INITIAL" if pos.stop==initial else "TRAILING",
                      "stop":pos.stop,"exitbar_open":b["o"]}
                break
            highest=max(highest,b["h"]);lowest=min(lowest,b["l"])
            if trailer in ("coupled","decoupled"):
                hks.trail_stop(pos,b["h"])
            elif trailer=="atr1m":
                # ATR14 on completed minute candles. Activate after +1R.
                # Lock at least estimated round-trip fee buffer at activation.
                if (b["h"]-entry)>=entry*frac and i>=14:
                    hist=m1[i-13:i+1]
                    ranges=[max(c["h"]-c["l"],abs(c["h"]-m1[j-1]["c"]),abs(c["l"]-m1[j-1]["c"]))
                        for j,c in zip(range(i-13,i+1),hist)]
                    atr=sum(ranges,D(0))/D(14)
                    proposed=max(entry*(1+D(str(cost))),highest-2*atr)
                    pos.stop=max(pos.stop,proposed)
                # no stop backdating to inside the bar
            else:raise ValueError("unknown trailing model")
        if exit is None:continue
        gross=(exit["px"]-entry)*qty
        fees=size*side_cost+exit["px"]*qty*side_cost
        net=gross-fees;wallet+=net
        busy_until=exit["end"]
        closed.append({"signal":TS(sig["t"]),"exit":TS(exit["end"]),"score":sig["score"],
           "sl_pct":round(float(frac*100),3),"original_sl_pct":round(float(sig["sl"]*100),3),
           "entry":round(float(entry),8),"exit_price":round(float(exit["px"]),8),
           "notional":round(float(size),2),"gross_mfe_pct":round(float((highest/entry-1)*100),3),
           "gross_mae_pct":round(float((lowest/entry-1)*100),3),
           "net_usd":round(float(net),4),"wallet":round(float(wallet),4),
           "reason":exit["reason"]})
    gross_net=sum(x["net_usd"] for x in closed)
    return {"trades":len(closed),"wins":sum(x["net_usd"]>0 for x in closed),
        "wallet_return_pct":round(float((wallet/D(1000)-1)*100),3),
        "net_usd":round(float(wallet-D(1000)),3),
        "net_without_biggest_win":round(gross_net-max([0]+[x["net_usd"] for x in closed]),3),
        "trade_details":closed}

for sym in ("TNKUSDT","CYSUSDT"):
    metadata(sym)
    try:
        q,qok=fetch(sym,"15m",WARM,END,900000)
        h,hok=fetch(sym,"60m",WARM,END,3600000)
        m1,ok=fetch(sym,"1m",START,END,60000)
    except Exception as exc:
        emit("symbol_fetch_failed",{"symbol":sym,"error":str(exc)[:400]})
        continue
    if not(qok and hok and ok):
        emit("halt",{"symbol":sym,"reason":"Incomplete true 1m or strategy warmup coverage"})
        continue
    sigs=signals_for(q,h)
    emit("signal_counts",{"symbol":sym,"original_LONG":sum(x["side"]=="LONG" for x in sigs),
         "original_SHORT_filtered":sum(x["side"]=="SHORT" for x in sigs),
         "scores_LONG":[x["score"] for x in sigs if x["side"]=="LONG"]})
    for threshold in (75,85):
        for mult in (1,.75,.5):
            for trail in ("coupled","decoupled","atr1m"):
                for cost in (.002,.005):
                    val=replay(m1,sigs,threshold,mult,trail,cost)
                    emit("scenario",{"symbol":sym,"score_min":threshold,"sl_factor":mult,
                        "trailing":trail,"cost_pct":cost*100,
                        **{k:v for k,v in val.items() if k!="trade_details"}})
                    if cost==.002 and threshold==85 and (trail=="coupled" or (trail=="atr1m" and mult==.75)):
                        emit("trades",{"symbol":sym,"score_min":threshold,"sl_factor":mult,"trailing":trail,"trades":val["trade_details"]})
emit("done",{"note":"Historical genuine 1m OHLC. No tick fills, orderbook, slippage validation or out-of-sample claim. TP logic unchanged; all strategies unapproved for live deployment."})
