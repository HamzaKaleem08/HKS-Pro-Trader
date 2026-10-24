"""Test free historic 1m TNK on Gate.io Spot; never pretend Gate.io prices are MEXC prices."""
import json,requests,datetime
S=requests.Session()
dates=["2026-04-27","2026-05-23","2026-06-28","2026-07-13","2026-08-07","2026-09-09","2026-10-22"]
urls=["https://api.gateio.ws/api/v4/spot/candlesticks","https://api.gate.us/api/v4/spot/candlesticks"]
for url in urls:
 for day in dates:
  d=datetime.datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
  st=int(d.timestamp())
  try:
   r=S.get(url,params={"currency_pair":"TNK_USDT","interval":"1m","from":st,"to":st+3600-1},timeout=14)
   data=r.json()
   print("GATE_PROBE",json.dumps({"base":url,"day":day,"status":r.status_code,"count":len(data) if isinstance(data,list) else None,
   "first":data[0] if isinstance(data,list) and data else None,"last":data[-1] if isinstance(data,list) and data else None,
   "message":data if not isinstance(data,list) else None})[:1300],flush=True)
  except Exception as e:print("GATE_ERROR",url,day,str(e)[:160],flush=True)
