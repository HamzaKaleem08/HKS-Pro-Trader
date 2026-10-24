"""Preserve real recent MEXC Spot TNK 1m candles as research-only CI artifact.
Public OHLCV, no credentials, no trading and no published source dataset.
"""
import csv,gzip,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
start=int(datetime(2026,9,25,tzinfo=timezone.utc).timestamp()*1000)
end=int(datetime(2026,10,24,tzinfo=timezone.utc).timestamp()*1000)
step=60000
rows={}
s=requests.Session()
cursor=start
while cursor<end:
    r=s.get("https://api.mexc.com/api/v3/klines",params={"symbol":"TNKUSDT","interval":"1m",
       "startTime":cursor,"endTime":end-1,"limit":1000},timeout=25)
    r.raise_for_status()
    vals=r.json()
    if not isinstance(vals,list) or not vals:raise RuntimeError(f"Missing data at {cursor}")
    valid=[x for x in vals if len(x)>=8 and cursor<=int(x[0])<end]
    if not valid:raise RuntimeError(f"Missing aligned data at {cursor}")
    for x in valid:rows[int(x[0])]=x
    nxt=max(int(x[0]) for x in valid)+step
    if nxt<=cursor:raise RuntimeError("Pagination failed")
    cursor=nxt
    time.sleep(.055)
timestamps=sorted(rows)
expected=(end-start)//step
assert len(timestamps)==expected,("coverage",len(timestamps),expected)
assert timestamps==list(range(start,end,step)),"timestamp gap"
out=Path("tnk_mexc_spot_1m_2026-09-25_to_2026-10-23.csv.gz")
with gzip.open(out,"wt",newline="") as f:
    w=csv.writer(f);w.writerow(["open_ms","open","high","low","close","volume_base","close_ms","quote_volume"])
    for t in timestamps:
        x=rows[t]
        w.writerow([x[0],x[1],x[2],x[3],x[4],x[5],x[6],x[7]])
hash=hashlib.sha256(out.read_bytes()).hexdigest()
print("ARCHIVED_1M "+json.dumps({"symbol":"MEXC:TNKUSDT","rows":len(timestamps),
"missing":0,"file":str(out),"gzip_bytes":out.stat().st_size,"sha256_gzip":hash}),flush=True)
