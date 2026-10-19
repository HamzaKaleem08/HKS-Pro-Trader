"""Validate genuine local cache and inventory SMC signals; no user code execution."""
import argparse,csv,gzip,hashlib,io,json,sys
from pathlib import Path
from bisect import bisect_right
from decimal import Decimal as D
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
import _kernel_for_tests
from backtester.models import Candle
from backtester.browser_context import aggregate
from smc_reference import snapshot

def load(symbol):
    entry=next(e for e in json.loads((ROOT/'web/candle-catalog.json').read_text()) if e['symbol']==symbol)
    compressed=(ROOT/'web'/entry['url']).read_bytes()
    assert len(compressed)==entry['bytes']
    assert hashlib.sha256(compressed).hexdigest()==entry['sha256']
    raw=gzip.decompress(compressed)
    assert hashlib.sha256(raw).hexdigest()==entry['uncompressed_sha256']
    rows=[]
    for i,r in enumerate(csv.DictReader(io.StringIO(raw.decode()))):
        ts=int(r['open_time']);assert ts==entry['start_ms']+i*60000
        o,h,l,c,v=(D(r[k]) for k in ['open','high','low','close','volume'])
        assert all(x.is_finite() for x in (o,h,l,c,v)) and min(o,h,l,c)>0 and v>=0 and l<=min(o,c)<=max(o,c)<=h
        rows.append(Candle(symbol,ts,60000,o,h,l,c,v))
    assert len(rows)==entry['candles'] and rows[-1].end_ms==entry['end_ms']
    return tuple(rows),entry

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--symbols',nargs='+',default=['BTCUSDT','ETHUSDT']);args=ap.parse_args()
    out=ROOT/'evidence/smc-compat-v1';evidence=[];signals=[]
    for symbol in args.symbols:
        rows,entry=load(symbol);m15=aggregate(rows,'15m');h1=aggregate(rows,'1h');ends=[h.end_ms for h in h1]
        for i,b in enumerate(m15):
            n=bisect_right(ends,b.end_ms)
            if i<49 or n<21:continue
            s=snapshot(m15[i-49:i+1],h1[n-21:n])
            if s['qualifies']:
                s.update(symbol=symbol,utc=datetime.fromtimestamp(s['signal_ms']/1000,timezone.utc).isoformat())
                signals.append(s)
        evidence.append(dict(entry,verified_1m=len(rows),completed_15m=len(m15),completed_1h=len(h1)))
    signals.sort(key=lambda s:(s['signal_ms'],s['symbol']))
    with (out/'GENUINE_SIGNAL_ORACLE.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(signals[0]) if signals else ['signal_ms','symbol']);w.writeheader();w.writerows(signals)
    (out/'CACHE_VERIFICATION.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps({'cache_symbols':len(evidence),'qualified_signal_counts':{s:sum(r['symbol']==s for r in signals) for s in args.symbols},
        'first_10':signals[:10]},indent=2))

if __name__=='__main__':main()
