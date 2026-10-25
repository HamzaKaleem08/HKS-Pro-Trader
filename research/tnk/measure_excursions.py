"""Enrich 180d TNK Spot 5m-proxy ledger with factual candle range excursions.
Read-only public MEXC OHLCV; does not touch strategy, wallet, or production.
Reports BOTH 5m bar envelope and a conservative pre-exit observation floor.
5m exit bar may contain prices reached after simulated stop, so bar-envelope
MFE/MAE are RANGE BOUNDS, not exact pre-exit trading MFE/MAE.
"""
import csv, io, json, time, requests
from datetime import datetime,timezone
from pathlib import Path
from decimal import Decimal as D
BASE=Path(__file__).resolve().parent
rows=list(csv.DictReader((BASE/"tnk_180d_full_trade_history.csv").open()))
session=requests.Session()
session.headers.update({"User-Agent":"HKS-Public-TNK-Research-Only/1.0"})
def time_ms(x):
    return int(datetime.strptime(x,"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()*1000)
def fetch(start,end):
    for attempt in range(4):
        try:
            r=session.get("https://api.mexc.com/api/v3/klines",
                params={"symbol":"TNKUSDT","interval":"5m","startTime":start,"endTime":end-1,"limit":1000},timeout=24)
            r.raise_for_status()
            data=r.json()
            if not isinstance(data,list):raise ValueError("Non-list API response "+str(data)[:100])
            return sorted(data,key=lambda b:int(b[0]))
        except Exception as exc:
            if attempt==3:raise RuntimeError("MEXC OHLCV fetch "+str(start)+": "+str(exc)) from exc
            time.sleep((attempt+1)*0.8)
trades={}
for row in rows:
    key=(row["Mode"],row["SignalUTC"])
    if key in trades:
        prev=trades[key]
        assert prev["ExitUTC"]==row["ExitUTC"] and prev["EntryPriceUSDT"]==row["EntryPriceUSDT"]
    else:trades[key]=row
assert len(rows)==110 and len(trades)==55,(len(rows),len(trades))
for ix,((mode,signal),r) in enumerate(sorted(trades.items()),1):
    start=time_ms(r["SignalUTC"]); end=time_ms(r["ExitUTC"])
    assert start<end and start%300000==0 and end%300000==0,(r["SignalUTC"],r["ExitUTC"])
    candles=fetch(start,end)
    count=(end-start)//300000
    assert len(candles)==count and count<1000,("missing_bars",signal,count,len(candles))
    for i,b in enumerate(candles):
        assert int(b[0])==start+i*300000,("gap",signal,i,b[0])
    entry=D(r["EntryPriceUSDT"]); exit_price=D(r["ExitPriceUSDT"])
    highs=[D(b[2]) for b in candles]
    lows=[D(b[3]) for b in candles]
    # EXIT-BAR-ENVELOPE: possible extremes, but event ordering is unknown.
    peak=max([entry,exit_price]+highs)
    trough=min([entry,exit_price]+lows)
    # "FLOOR": completed 5m candles before final exit bar plus simulated exit fill.
    # These excursions definitely happened while position was held under proxy.
    prior_hi=max([entry,exit_price]+highs[:-1])
    prior_lo=min([entry,exit_price]+lows[:-1])
    assert peak>=prior_hi>=entry>=prior_lo>=trough
    # Print compact JSON for connector transfer; no private records.
    print("TNK_EXCURSION "+json.dumps({"mode":mode,"signal":signal,
      "bars":count,"peak":str(peak),"trough":str(trough),
      "pre_exit_peak":str(prior_hi),"pre_exit_trough":str(prior_lo)},
      separators=(",",":")),flush=True)
    if ix%15==0:print("PROGRESS",ix,"/",len(trades),flush=True)
    time.sleep(.11)
print("TNK_EXCURSION_TOTAL "+str(len(trades)),flush=True)
