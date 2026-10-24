"""Standalone TNK MEXC SPOT historical test (public candles, no credentials/orders).
No changes to production app.py or private HKS data.
Outputs summaries only. All times UTC; today/open candles excluded.
"""
from __future__ import annotations
import bisect, json, os, sys, time, statistics, tempfile
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from pathlib import Path
import requests

CUTOFF=datetime(2026,10,24,tzinfo=timezone.utc)
START=CUTOFF-timedelta(days=180)
MINUTE_START=CUTOFF-timedelta(days=90)
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
tmp=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(tmp.name)/"isolated_research.sqlite3")
os.environ.pop("VERCEL",None)
os.environ.pop("REPLIT_DEPLOYMENT",None)
import app as hks

S=requests.Session()
S.headers.update({"User-Agent":"HKS-TNK-Public-Research/1.0"})
API="https://api.mexc.com/api/v3/klines"
def epoch(t):return int(t.timestamp()*1000)
def iso(ms):return datetime.fromtimestamp(ms/1000,tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
def acquire(interval,start,end,step_ms,limit_pages=300):
    """Paginate exchange REST history, discard duplicates and inspect gaps."""
    cursor=epoch(start)
    last=epoch(end)
    rows={}
    pages=0
    while cursor<last and pages<limit_pages:
        resp=None
        for attempt in range(4):
            try:
                resp=S.get(API,params={"symbol":"TNKUSDT","interval":interval,
                         "startTime":cursor,"endTime":last-1,"limit":1000},timeout=20)
                resp.raise_for_status()
                data=resp.json()
                if not isinstance(data,list):raise ValueError("Bad candle payload: "+str(data)[:140])
                break
            except Exception as exc:
                if attempt==3:raise RuntimeError(f"{interval} fetch failed page {pages} at {iso(cursor)}: {exc}") from exc
                time.sleep(0.9*(attempt+1))
        if not data:break
        valid=[x for x in data if isinstance(x,list) and len(x)>=8 and cursor<=int(x[0])<last]
        if not valid:break
        for x in valid:rows[int(x[0])]=x
        next_cursor=max(int(x[0]) for x in valid)+step_ms
        if next_cursor<=cursor:break
        cursor=next_cursor
        pages+=1
        if pages%30==0:print("PROGRESS",interval,pages,"pages",len(rows),"candles",flush=True)
        time.sleep(0.10)
    ordered=[rows[k] for k in sorted(rows)]
    candles=[]
    for x in ordered:
        t=int(x[0]);o,h,l,c,v,q=map(D,[x[1],x[2],x[3],x[4],x[5],x[7]])
        if o<=0 or h<max(o,c,l) or l>min(o,c,h) or l<=0:continue
        candles.append(dict(t=t,end=t+step_ms,o=o,h=h,l=l,c=c,v=v,q=q))
    gaps=sum(1 for a,b in zip(candles,candles[1:]) if b["t"]!=a["end"])
    return candles,dict(interval=interval,requested_start=start.isoformat(),requested_end=end.isoformat(),
        first=iso(candles[0]["t"]) if candles else None,last=iso(candles[-1]["t"]) if candles else None,
        rows=len(candles),pages=pages,gaps=gaps,coverage_pct=round(100*len(candles)/((last-epoch(start))//step_ms),2))

def log(obj):
    print("TNK_RESULT "+json.dumps(obj,sort_keys=True,default=str),flush=True)

m15,cov15=acquire("15m",START,CUTOFF,900000,35)
h1,cov1=acquire("60m",START,CUTOFF,3600000,12)
log({"phase":"coverage","15m":cov15,"1h":cov1})
if cov15["coverage_pct"]<85 or cov1["coverage_pct"]<85:
    log({"phase":"halt","reason":"Insufficient 180-day 15m/1h coverage; cannot safely infer signals"})
    sys.exit(0)

# Group 15m bars by UTC calendar day (only fully-covered days counted).
byday=defaultdict(list)
for b in m15:byday[datetime.fromtimestamp(b["t"]/1000,tz=timezone.utc).date()].append(b)
episodes=[]
for day,bars in sorted(byday.items()):
    if len(bars)<92:continue
    opening=bars[0]["o"];high=max(x["h"] for x in bars);low=min(x["l"] for x in bars);close=bars[-1]["c"]
    peak=(high/opening-1)*100
    if peak>=25:
        crossed10=next((x for x in bars if x["h"]>=opening*D("1.10")),None)
        crossed25=next((x for x in bars if x["h"]>=opening*D("1.25")),None)
        episodes.append(dict(day=str(day),open=float(opening),high=float(high),
          close=float(close),peak_pct=round(float(peak),2),
          close_pct=round(float((close/opening-1)*100),2),
          peak_to_close_pct=round(float((close/high-1)*100),2),
          first10_utc=iso(crossed10["end"]) if crossed10 else None,
          first25_utc=iso(crossed25["end"]) if crossed25 else None))
log({"phase":"episodes","threshold":"UTC day high >= +25% vs day open","days":len(byday),"episodes":episodes})

# Early alert: compare finished 15m candle turnover with historical baseline, breakout above
# PRECEDING 24h high, and avoid already >+10% from day open. Uses no future data.
early=[]
indices={b["t"]:i for i,b in enumerate(m15)}
for day,bars in sorted(byday.items()):
    if len(bars)<92:continue
    opening=bars[0]["o"]
    alert=None
    first10=next((b for b in bars if b["h"]>=opening*D("1.10")),None)
    for b in bars:
        i=indices[b["t"]]
        if i<100:continue
        hist=m15[i-96:i]
        if len(hist)!=96 or any(y["t"]!=x["end"] for x,y in zip(hist,hist[1:])) or b["t"]!=hist[-1]["end"]:continue
        if b["c"]>=opening*D("1.10"):continue
        median_q=statistics.median([float(x["q"]) for x in hist])
        if median_q<=0:continue
        rvol=float(b["q"])/median_q
        breakout=b["c"]>max(x["h"] for x in hist)
        if rvol>=3 and breakout:
            alert=b;break
    dayinfo=next((e for e in episodes if e["day"]==str(day)),None)
    is_early=bool(alert and dayinfo and first10 and alert["end"]<first10["end"])
    lead_min=(first10["end"]-alert["end"])//60000 if is_early else None
    early.append(dict(day=str(day),pump=dayinfo is not None,
        alert=iso(alert["end"]) if alert else None,early_pre10=is_early,lead_minutes=lead_min))
pump_days={e["day"] for e in episodes}
log({"phase":"early_alert","rule":"15m quote volume>=3x past-24h median + close>previous-24h high + close<day-open*1.10",
     "pump_days":len(pump_days),"days_total":len(early),
     "pump_days_detected_early":sum(x["early_pre10"] for x in early),
     "nonpump_days_alerted":sum(x["alert"] is not None and not x["pump"] for x in early),
     "alerts_pre10": [x for x in early if x["early_pre10"]],
     "alerts_nonpump_sample":[x for x in early if x["alert"] is not None and not x["pump"]][:12]})

# Exact current HKS evaluate_smc() imported from app.py, with 35 completed
# 15m candles and 25 completed 1h candles. Never use next or forming candles.
minute_ends=[x["end"] for x in m15]
hour_ends=[x["end"] for x in h1]
signals=[]
stats=Counter()
for i in range(35,len(m15)):
    t=m15[i]["end"]
    window=m15[i-34:i+1]
    if any(y["t"]!=x["end"] for x,y in zip(window,window[1:])):continue
    j=bisect.bisect_right(hour_ends,t)
    hourly=h1[j-25:j]
    if len(hourly)<25 or any(y["t"]!=x["end"] for x,y in zip(hourly,hourly[1:])):continue
    bars=[{k:b[k] for k in ("t","end","o","h","l","c")} for b in window]
    hours=[{k:b[k] for k in ("t","end","o","h","l","c")} for b in hourly]
    try:ev=hks.evaluate_smc(bars,hours,t)
    except Exception as err:
        stats["evaluation_errors"]+=1
        continue
    stats["evaluated"]+=1
    if ev["original"]:
        stats["sweeps"]+=1
        if ev["trade_score"]>=75:
            stats["eligible"]+=1
            stats[ev["original"]]+=1
            signals.append(dict(t=t,original=ev["original"],score=ev["trade_score"],stop=ev["stop_fraction"],
                                price=m15[i]["c"],display=ev["display"]))
log({"phase":"hks_signals","180d_total":dict(stats),"signals":[dict(utc=iso(x["t"]),original=x["original"],score=x["score"],
                                                     stop_pct=float(x["stop"]*100),close=float(x["price"])) for x in signals[:75]],
     "note":"Eligible sweep+>=75 signals; original HKS strategy may evaluate but only enter if wallet/capital/single-position gating permits"})

# Detailed execution test on 90d minute bars: only historical OHLCV, fill at
# next complete minute OPEN, no hindsight in fills, stop checked before trail.
m1,covmin=acquire("1m",MINUTE_START,CUTOFF,60000,160)
log({"phase":"minute_coverage","1m":covmin})
if covmin["coverage_pct"]<95 or covmin["gaps"]>100:
    log({"phase":"stop_simulation","status":"not_run","reason":"Insufficient or gappy 1m price data"})
    sys.exit(0)

mins_ends=[x["t"] for x in m1]
# To check 15m signal at close t, enter next 1m candle (open t), only if exists.
def simulate(mode,fee_round_trip):
    wallet=D("1000")
    entries=[]
    active_until=0
    fee_one=D(str(fee_round_trip))/D(2)
    for sig in signals:
        t=sig["t"]
        if t<epoch(MINUTE_START) or t>=epoch(CUTOFF)-60000:continue
        # Spot-only replay uses long-compatible signals; short is separate synthetic
        side=(sig["original"] if mode=="NORMAL" else
              ("SHORT" if sig["original"]=="LONG" else "LONG"))
        if side!="LONG":continue
        if t<active_until:continue
        k=bisect.bisect_left(mins_ends,t)
        if k>=len(m1) or m1[k]["t"]!=t:continue
        if wallet<=0:break
        entry=m1[k]["o"]
        sl_frac=sig["stop"]
        capital=min(wallet*D(".01")/sl_frac,wallet*D("0.3333333333")/(D(1)+fee_one))
        if capital<=D(5):continue
        qty=capital/entry
        # Fee estimate is separate from spot capital; no leverage.
        entry_fee=capital*fee_one
        initial_stop=entry*(D(1)-sl_frac)
        stop=initial_stop
        # We only use t=15m close and subsequent minute candle OHLC; no same-bar
        # trailing activation or hindsight fill. New tighter stop applies from next bar.
        distance=entry*sl_frac*D(2)
        exit_found=False
        for n in range(k,len(m1)):
            bar=m1[n]
            if n>k and bar["t"]!=m1[n-1]["end"]:break
            if bar["l"]<=stop:
                exit_price=min(bar["o"],stop)
                reason="TRAILING SL HIT" if stop!=initial_stop else "INITIAL SL HIT"
                exit_time=bar["end"]
                exit_found=True
                break
            progress=(bar["h"]-entry)/distance*100
            if progress>=D(40):
                locked=D(10)+(progress-D(40))*D("1.5") if progress<=D(80) else progress-D(10)
                stop=max(stop,entry+distance*locked/100)
        if not exit_found:continue
        gross=(exit_price-entry)*qty
        exit_fee=abs(exit_price*qty)*fee_one
        pnl=gross-entry_fee-exit_fee
        before=wallet
        wallet+=pnl
        active_until=exit_time
        entries.append(dict(utc=iso(t),exit_utc=iso(exit_time),entry=float(entry),
                            exit=float(exit_price),score=sig["score"],stop_pct=float(sl_frac*100),
                            reason=reason,notional=round(float(capital),3),
                            net=round(float(pnl),4),net_R=round(float(pnl/(capital*sl_frac)),3),
                            wallet=round(float(wallet),4)))
    return {"mode":mode,"round_trip_cost_rate":fee_round_trip,
            "trades":len(entries),"wins":sum(x["net"]>0 for x in entries),
            "net_return_pct":round(float((wallet/D(1000)-1)*100),3),
            "mean_R":round(statistics.mean([x["net_R"] for x in entries]),3) if entries else None,
            "entries":entries[:40]}
for mode in ("NORMAL","REVERSE"):
    for costs in (.002,.005):
        log({"phase":"hks_spot_long_90d","result":simulate(mode,costs)})
log({"phase":"done","basis":"MEXC TNKUSDT spot candles; no fills/depth verified; results hypothetical and no out-of-sample validation"})
