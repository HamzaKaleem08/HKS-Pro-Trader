"""Check 180d TNK MEXC spot archive coverage & no-purchase price quote."""
import requests,json,csv
from pathlib import Path
p=Path(__file__).parent/"tnk_180d_required_real_1m_days.csv"
rows=list(csv.DictReader(p.open()))
dates=[x["UTC_Date"] for x in rows if x["Source"].startswith("CryptoStruct")]
assert len(dates)==37
s=requests.Session()
for endpoint in ["coverage","calendar?month=2026-05","calendar?month=2026-06","calendar?month=2026-07","calendar?month=2026-08","calendar?month=2026-09"]:
 try:
  r=s.get("https://cryptostruct.com/api/instrument/394629/"+endpoint,timeout=20)
  print("COVERAGE",endpoint,r.status_code,r.text[:2500],flush=True)
 except Exception as exc:print("COVERAGE_ERROR",endpoint,str(exc)[:180],flush=True)
items=[{"instrument_id":394629,"date":d,"kind":"tick"} for d in dates]
try:
 r=s.post("https://cryptostruct.com/api/quote",json={"items":items},timeout=25)
 data=r.json()
 print("QUOTE",json.dumps({"status":r.status_code,"available":data.get("items_available"),
 "requested":data.get("items_requested"),"total_eur":data.get("total_eur"),
 "missing":data.get("missing"),"price_eur_per_day":data.get("price_eur_per_day")})[:4200],flush=True)
except Exception as exc:print("QUOTE_ERROR",str(exc)[:220],flush=True)
