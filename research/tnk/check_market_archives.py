"""Public source availability check; read-only, no purchases, accounts or user keys."""
import requests,json
urls=["https://cryptostruct.com/api/search?q=TNKUSDT",
      "https://cryptostruct.com/api/search?q=TNK",
      "https://www.mexc.com/market-data-download?search=TNK&type=kline",
      "https://www.mexc.com/market-data-download/TNK"]
s=requests.Session()
for url in urls:
 try:
  r=s.get(url,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
  data=r.json() if "json" in r.headers.get("content-type","") else None
  print("SOURCE",json.dumps({"url":url,"status":r.status_code,"content_type":r.headers.get("content-type",""),
   "data":str(data)[:6000] if data is not None else "",
   "tnk_literal_hits":r.text.upper().count("TNK"),"length":len(r.content)}),flush=True)
 except Exception as e:print("SOURCE_ERROR",url,str(e)[:300],flush=True)
