"""Probe MEXC historical 1m legacy public API and official archive landing page; no secrets."""
import requests,json
from datetime import datetime,timezone
start=int(datetime(2026,6,28,tzinfo=timezone.utc).timestamp())
s=requests.Session()
urls=[
("v2_mexc_com","https://api.mexc.com/open/api/v2/market/kline",{"symbol":"TNK_USDT","interval":"1m","start_time":start,"limit":20}),
("v2_mexc_co","https://api.mexc.co/open/api/v2/market/kline",{"symbol":"TNK_USDT","interval":"1m","start_time":start,"limit":20}),
("spot_tnk_archive","https://www.mexc.com/market-data-download/TNK",{}),
]
for tag,u,params in urls:
 try:
  r=s.get(u,params=params,timeout=18,headers={"User-Agent":"Mozilla/5.0"})
  output={"tag":tag,"status":r.status_code,"final_url":r.url,"bytes":len(r.content),"content_type":r.headers.get("content-type")}
  if tag.startswith("v2"):
   output["response_preview"]=r.text[:700]
  else:
   import re
   for term in ["1min","5min","Chart Daily Data","18 months","Trading Data","Trade History"]:
    output[term]=len(re.findall(re.escape(term),r.text,re.I))
  print("LEGACY_CHECK "+json.dumps(output),flush=True)
 except Exception as e:print("LEGACY_ERROR "+tag+" "+str(e)[:240],flush=True)
