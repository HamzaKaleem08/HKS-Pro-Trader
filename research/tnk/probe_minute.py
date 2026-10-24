import requests,json
from datetime import datetime,timezone,timedelta
s=requests.Session()
for when in ["2026-07-26","2026-09-09","2026-10-22","2026-10-23"]:
 d=datetime.strptime(when,"%Y-%m-%d").replace(tzinfo=timezone.utc)
 a=int(d.timestamp()*1000)
 for label,opts in [("12h",{"startTime":a,"endTime":a+43200000-1,"limit":500}),
                    ("start-only",{"startTime":a,"limit":5})]:
  try:
   r=s.get("https://api.mexc.com/api/v3/klines",params={"symbol":"TNKUSDT","interval":"1m",**opts},timeout=15)
   val=r.json()
   print("PROBE",json.dumps({"date":when,"query":label,"status":r.status_code,
         "count":len(val) if isinstance(val,list) else None,
         "first":val[0][0] if isinstance(val,list) and val else None,
         "body":str(val)[:200] if not isinstance(val,list) else None}))
  except Exception as e:print("PROBE",when,label,str(e)[:150])
