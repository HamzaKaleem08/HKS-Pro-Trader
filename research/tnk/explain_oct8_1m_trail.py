"""Explain exact TNK 1m trailing sequence on 2026-10-08 and 2026-10-13.
Read-only genuine MEXC Spot 1m OHLC. Production HKS stop formula imported
unchanged and tested independently for 100% vs 50% initial ATR stop.
No trading changes or fake candles.
"""
import os,sys,tempfile,requests,json
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory() as tmp:
 os.environ["DATABASE_URL"]="sqlite:///"+str(Path(tmp)/"oct8_trace.sqlite3")
 os.environ.pop("VERCEL",None)
 import app as hks
 s=requests.Session()
 s.headers["User-Agent"]="HKS-Research-Trailing-Trace-ReadOnly"
 def ms(x):return int(datetime.strptime(x,"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()*1000)
 def utc(t):return datetime.fromtimestamp(t/1000,timezone.utc).strftime("%Y-%m-%d %H:%M")
 def f(x):return round(float(x),9)
 cases=[
  {"id":"OCT8","start":"2026-10-08 13:30","finish":"2026-10-08 19:00","entry":D("0.08176"),"sl_pct":D("2.670708694")},
  {"id":"OCT13","start":"2026-10-13 13:00","finish":"2026-10-13 16:00","entry":D("0.08640"),"sl_pct":D("3")}
 ]
 def emit(d):print("TRAIL_TRACE "+json.dumps(d,separators=(",",":")),flush=True)
 for case in cases:
  resp=s.get("https://api.mexc.com/api/v3/klines",params={"symbol":"TNKUSDT","interval":"1m",
     "startTime":ms(case["start"]),"endTime":ms(case["finish"])-1,"limit":1000},timeout=25)
  resp.raise_for_status()
  raw=resp.json()
  if not isinstance(raw,list):raise RuntimeError(str(raw)[:200])
  candles=[]
  for r in raw:
   t=int(r[0])
   if not(ms(case["start"])<=t<ms(case["finish"])):continue
   candles.append({"t":t,"o":D(r[1]),"h":D(r[2]),"l":D(r[3]),"c":D(r[4])})
  n=(ms(case["finish"])-ms(case["start"]))//60000
  assert len(candles)==n,(case["id"],len(candles),n)
  assert all(b["t"]-a["t"]==60000 for a,b in zip(candles,candles[1:]))
  assert candles[0]["o"]==case["entry"], (case["id"],candles[0]["o"])
  emit({"case":case["id"],"event":"data","bars":len(candles),"entry":f(case["entry"]),
       "SL_original_pct":f(case["sl_pct"])})
  for factor in (D(1),D(".5")):
   orig_sl=case["sl_pct"]/100
   active_sl=orig_sl*factor
   entry=case["entry"]
   pos=SimpleNamespace(direction="LONG",entry_price=entry,stop=entry*(1-active_sl),
         initial_stop=entry*(1-active_sl),reference_distance=entry*active_sl*2)
   trigger_price=entry+D(".4")*pos.reference_distance
   first_move=None;updates=0;peak=entry
   timeline=[]
   exit=None;exit_i=None
   for i,b in enumerate(candles):
    stop_in=pos.stop
    fill=hks.get_stop_fill(pos,b)
    if fill is not None:
     exit_i=i
     exit={"utc":utc(b["t"]+60000),"exit_bar_time":utc(b["t"]),"exit_price":f(fill),
       "exit_bar_open":f(b["o"]),"exit_bar_high":f(b["h"]),"exit_bar_low":f(b["l"]),
       "prior_stop":f(stop_in),"max_seen_high_before_exit":f(peak),
       "high_gain_before_exit_pct":round(float((peak/entry-1)*100),4),
       "gross_pnl_250":round(float(D(250)*(fill/entry-1)),4),
       "net_pnl_250_cost_0p2":round(float(D(250)*(fill/entry-1)-D(".001")*(D(250)+D(250)*fill/entry)),4)}
     timeline.append({"utc":utc(b["t"]),"event":"STOP HIT","open":f(b["o"]),"high":f(b["h"]),"low":f(b["l"]),
           "stop_before":f(stop_in),"fill":f(fill)})
     break
    peak=max(peak,b["h"])
    moved=hks.trail_stop(pos,b["h"])
    if moved:
     updates+=1
     if first_move is None:first_move={"utc":utc(b["t"]),"bar_high":f(b["h"]),"bar_low":f(b["l"]),
       "bar_close":f(b["c"]),"stop_before":f(stop_in),"stop_after":f(pos.stop)}
     timeline.append({"utc":utc(b["t"]),"event":"TRAIL MOVED","open":f(b["o"]),"high":f(b["h"]),
       "low":f(b["l"]),"close":f(b["c"]),"stop_before":f(stop_in),"stop_after":f(pos.stop)})
   emit({"case":case["id"],"factor":str(factor),"event":"summary","threshold_price":f(trigger_price),
       "threshold_gain_pct":round(float((trigger_price/entry-1)*100),4),
       "initial_stop":f(pos.initial_stop),"first_trail_move":first_move,
       "updates":updates,"exit":exit,"events_last":timeline[-7:]})
   if exit_i is not None:
    emit({"case":case["id"],"factor":str(factor),"event":"last_5_bars",
      "bars":[{"utc":utc(b["t"]),"o":f(b["o"]),"h":f(b["h"]),"l":f(b["l"]),"c":f(b["c"])}
       for b in candles[max(0,exit_i-4):exit_i+1]]})
  # Show price recovery to original exit timestamp, independent of half position
  if case["id"]=="OCT8":
   price_slice=[x for x in candles if x["t"]>=ms("2026-10-08 16:53") and x["t"]<ms("2026-10-08 18:36")]
   if price_slice:
    high=max(price_slice,key=lambda b:b["h"])
    low=min(price_slice,key=lambda b:b["l"])
    emit({"case":"OCT8","event":"after_half_exit","max_high":f(high["h"]),
      "max_high_time":utc(high["t"]),"min_low":f(low["l"]),"min_low_time":utc(low["t"]),
      "pct_high_above_entry":round(float((high["h"]/case["entry"]-1)*100),4)})
