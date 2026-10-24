"""Read-only REAL public MEXC Spot data smoke test for Bot2's exact API paths.
No API credentials, no database writes, no exchange orders.
"""
from datetime import datetime,timezone
from decimal import Decimal as D
import json
import time
import bot2_spot as b2

now=int(time.time()*1000)
rows=[]
for symbol in b2.COINS:
    spans={}
    for interval in ("1m","15m","60m"):
        bars=b2._bars(symbol,interval,35,now)
        assert len(bars)>=21,(symbol,interval,len(bars))
        assert bars[-1]["end"]<=now
        spans[interval]={"bars":len(bars),"last_end_utc":
            datetime.fromtimestamp(bars[-1]["end"]/1000,timezone.utc).isoformat()}
    bids,asks=b2._book(symbol)
    buy_price,qty=b2._buy_quote(asks,D("50"))
    spread=(asks[0][0]-bids[0][0])/((asks[0][0]+bids[0][0])/2)*100
    result={"symbol":symbol,"spans":spans,"best_bid":str(bids[0][0]),
       "best_ask":str(asks[0][0]),"spread_pct":round(float(spread),3),
       "estimated_50_usdt_buy_price":str(buy_price),
       "paper_qty":str(qty)}
    rows.append(result)
    print("MEXC_SMOKE "+json.dumps(result,separators=(",",":")),flush=True)
assert len(rows)==2
print("MEXC_SMOKE_PASS",flush=True)
