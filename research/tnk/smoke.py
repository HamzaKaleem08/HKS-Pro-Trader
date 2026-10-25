"""MEXC TNK spot public market data connectivity test, no keys and no trades."""
import json
import requests

urls=[
    "https://api.mexc.com/api/v3/klines",
    "https://api.mexc.co/api/v3/klines",
]
for url in urls:
    try:
        r=requests.get(url,params={"symbol":"TNKUSDT","interval":"15m","limit":4},timeout=12,
                       headers={"User-Agent":"HKS-Public-Market-Research/1.0"})
        print(json.dumps({"url":url,"status":r.status_code,"rows":len(r.json()) if isinstance(r.json(),list) else None,
                          "first":r.json()[0] if isinstance(r.json(),list) and r.json() else None,
                          "body_preview":r.text[:250] if r.status_code!=200 else None}))
    except Exception as e:
        print(json.dumps({"url":url,"error":str(e)[:350]}))
