"""Read-only REAL public MEXC Spot data smoke test for Bot2's exact API paths.
No API credentials, no database writes, no exchange orders.
"""
from datetime import datetime,timezone
from decimal import Decimal as D
import json
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
import tempfile
from unittest import mock
TMP=tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"]="sqlite:///"+TMP.name+"/live_public_smoke.sqlite3"
os.environ["HKS_BOT2_PAPER_ENABLED"]="0"
import bot2_spot as b2
import app as hks

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
# Exercise the REAL Bot2 scan processing & persistence against public MEXC,
# but with paper trading hard-disabled. No funds and no exchange order APIs.
runner=hks.app.extensions["hks_bot2"]
for symbol in b2.COINS:
    scan=runner["scan_symbol"](symbol,int(time.time()*1000))
    assert scan["status"]=="ok",(symbol,scan)
    print("MEXC_SCAN_E2E "+json.dumps(scan,separators=(",",":")),flush=True)
with mock.patch.object(hks,"_ensure_automatic_scanner",return_value=None):
    state=hks.app.test_client().get("/api/bot2/state").json
assert state["paper_enabled"] is False
assert {coin["symbol"] for coin in state["coins"]}==set(b2.COINS)
assert all(coin["price_bid"] is not None for coin in state["coins"])
assert state["open_positions"]==[]
print("MEXC_SMOKE_PASS",flush=True)
