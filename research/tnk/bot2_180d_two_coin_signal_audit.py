"""Research-only 180d eligibility audit: CYS and TNK MEXC Spot.
True MEXC 15m/60m candles; strict completed candle scoring, no future data.
Not an exit backtest (180d 1m not available free).
"""
import os,sys,tempfile,requests,json,time,collections,bisect,statistics
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
base=Path(__file__).resolve().parents[2];sys.path.insert(0,str(base))
tmp=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+str(Path(tmp.name)/"audit.sqlite3")
os.environ.pop("VERCEL",None)
import app as hks
start=datetime(2026,4,27,tzinfo=timezone.utc)
end=datetime(2026,10,24,tzinfo=timezone.utc)
to_ms=lambda d:int(d.timestamp()*1000)
def out(obj):print("AUDIT180 "+json.dumps(obj,default=str,separators=(",",":")),flush=True)
S=requests.Session();S.headers["User-Agent"]="HKS-Public-Spot-Research"
def get(sym,inter,step):
 cur=to_ms(start);endms=to_ms(end);data={}
 while cur<endms:
  for attempt in range(3):
   try:
    r=S.get("https://api.mexc.com/api/v3/klines",params={"symbol":sym,"interval":inter,
         "startTime":cur,"endTime":endms-1,"limit":1000},timeout=22)
    r.raise_for_status();x=r.json()
    if not isinstance(x,list):raise RuntimeError("Invalid response "+str(x)[:160])
    break
   except Exception:
    if attempt==2:raise
    time.sleep(attempt+1)
  if not x:break
  valid=[z for z in x if cur<=int(z[0])<endms]
  if not valid:break
  for z in valid:data[int(z[0])]=z
  cur=max(int(z[0]) for z in valid)+step
  time.sleep(.06)
 bars=[]
 for t,z in sorted(data.items()):
  bars.append({"t":t,"end":t+step,"o":D(z[1]),"h":D(z[2]),"l":D(z[3]),"c":D(z[4])})
 complete=len(bars)==(endms-to_ms(start))//step and all(x["end"]==y["t"] for x,y in zip(bars,bars[1:]))
 return bars,complete
for sym in ("CYSUSDT","TNKUSDT"):
 try:
  m15,c15=get(sym,"15m",900000);hour,c60=get(sym,"60m",3600000)
  if not(c15 and c60):
   out({"symbol":sym,"phase":"halt","15m_rows":len(m15),"hour_rows":len(hour),"reason":"incomplete history"})
   continue
  times=[b["end"] for b in hour]
  dist=collections.Counter();monthly=collections.defaultdict(collections.Counter)
  signals=[];scans=0;candidate=0
  for i in range(34,len(m15)):
   close=m15[i]["end"];window=m15[i-34:i+1];j=bisect.bisect_right(times,close)
   h=hour[j-25:j]
   if len(h)<25:continue
   ev=hks.evaluate_smc(window,h,close);scans+=1
   if ev["original"]:
    candidate+=1
    orig=ev["original"];score=ev["trade_score"]
    dist[(orig,score)]+=1
    month=datetime.fromtimestamp(close/1000,timezone.utc).strftime("%Y-%m")
    monthly[month][orig+"_candidate"]+=1
    if score>=75:
     monthly[month][orig+"_eligible"]+=1
     signals.append({"t":datetime.fromtimestamp(close/1000,timezone.utc).strftime("%Y-%m-%d %H:%M"),
                   "side":orig,"score":score})
  out({"symbol":sym,"phase":"scores","15m_rows":len(m15),"hour_rows":len(hour),
      "complete":True,"evaluated":scans,"sweep_candidates":candidate,
      "eligible_LONG":sum(x["side"]=="LONG" for x in signals),
      "eligible_SHORT_filtered":sum(x["side"]=="SHORT" for x in signals),
      "score_distribution":[{"side":k[0],"score":k[1],"n":v} for k,v in sorted(dist.items())],
      "monthly":{k:dict(v) for k,v in sorted(monthly.items())},
      "eligible_signal_times":signals})
 except Exception as exc:out({"symbol":sym,"phase":"error","message":str(exc)[:400]})
