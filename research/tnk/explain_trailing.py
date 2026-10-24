"""Trade 22/24 5m OHLC stop trace, no live trading modifications."""
from datetime import datetime,timezone
from decimal import Decimal as D
import csv,requests
from pathlib import Path
rows=list(csv.DictReader((Path(__file__).parent/"tnk_180d_full_trade_history.csv").open()))
def ms(t):return int(datetime.strptime(t,"%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()*1000)
for trade_no in ("22","24"):
 r=next(x for x in rows if x["Scenario"]=="180d_NORMAL_0.2pct_cost" and x["TradeNo"]==trade_no)
 entry=D(r["EntryPriceUSDT"]); sl=D(r["ATR_SL_Pct"])/100
 stop=entry*(1-sl); initial=stop;dist=entry*sl*2
 api=requests.get("https://api.mexc.com/api/v3/klines",params={"symbol":"TNKUSDT","interval":"5m","startTime":ms(r["SignalUTC"]),"endTime":ms(r["ExitUTC"])-1,"limit":200},timeout=30)
 api.raise_for_status(); cand=sorted(api.json(),key=lambda x:x[0])
 print("CASE",trade_no,"entry",entry,"initial_sl",round(initial,8),"distance",round(dist,8),"bars",len(cand),"expected_exit",r["ExitPriceUSDT"],flush=True)
 for row in cand:
  t=datetime.fromtimestamp(row[0]/1000,tz=timezone.utc).strftime("%H:%M")
  o,h,l,c=(D(v) for v in row[1:5]);old=stop
  if l<=stop:
   fill=min(o,stop)
   why=("GAP_OPEN_BELOW_STOP" if o<stop else "STOP_TOUCH")
   print("BAR",t,"o",o,"h",h,"l",l,"c",c,
         "STOP_BEFORE",round(old,8),"EXIT",round(fill,8),
         why,"stop_above_entry?",stop>entry,flush=True)
   break
  progress=(h-entry)/dist*100
  if progress>=40:
   locked=D(10)+(progress-D(40))*D("1.5") if progress<=80 else progress-D(10)
   stop=max(stop,entry+dist*locked/100)
  print("BAR",t,"o",o,"h",h,"l",l,"c",c,
        "STOP_BEFORE",round(old,8),"STOP_AFTER",round(stop,8),
        "PROGRESS",round(progress,2),
        "STOP_GREATER_THAN_CLOSE_AFTER_UPDATE",stop>c,flush=True)
