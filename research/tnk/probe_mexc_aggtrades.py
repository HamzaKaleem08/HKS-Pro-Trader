"""Public MEXC aggregated-trade historical availability; no credentials or live actions."""
import requests,json,datetime
s=requests.Session()
dates=["2026-04-27","2026-05-23","2026-06-28","2026-07-13","2026-08-07","2026-09-09","2026-10-22"]
for day in dates:
 d=datetime.datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
 start=int(d.timestamp()*1000)
 for period in (300000,3600000):
  for domain in ("api.mexc.com","api.mexc.co"):
   try:
    r=s.get("https://"+domain+"/api/v3/aggTrades",
      params={"symbol":"TNKUSDT","startTime":start,"endTime":start+period-1,"limit":1000},timeout=14)
    data=r.json()
    print("AGG",json.dumps({"day":day,"duration_ms":period,"host":domain,
       "status":r.status_code,"count":len(data) if isinstance(data,list) else None,
       "first":data[0] if isinstance(data,list) and data else None,
       "last":data[-1] if isinstance(data,list) and data else None,
       "error":data if not isinstance(data,list) else None})[:1200],flush=True)
   except Exception as e:print("AGG_ERR",day,domain,str(e)[:180],flush=True)
