"""Illustrative live MEXC Spot $25-$250 instantaneous buy/sell book-walk.
Public order books, no real orders. Snapshot not representative of history.
"""
import requests,json
from decimal import Decimal as D
S=requests.Session()
S.headers["User-Agent"]="HKS-Spot-Orderbook-Research"
for sym in ("TNKUSDT","CYSUSDT"):
 try:
  r=S.get("https://api.mexc.com/api/v3/depth",params={"symbol":sym,"limit":500},timeout=18)
  r.raise_for_status();data=r.json()
  bids=[(D(x[0]),D(x[1])) for x in data["bids"]]
  asks=[(D(x[0]),D(x[1])) for x in data["asks"]]
  best_bid=bids[0][0];best_ask=asks[0][0];mid=(best_bid+best_ask)/2
  for amount in (25,50,100,250):
   target=D(amount);left=target;got=D(0)
   for price,qty in asks:
    spend=min(left,price*qty)
    got+=spend/price
    left-=spend
    if left<=D("0.0000000001"):break
   remain=got;received=D(0)
   for price,qty in bids:
    sell=min(remain,qty);received+=price*sell;remain-=sell
    if remain<=D("0.0000000001"):break
   full=(left<=D("0.0000000001") and remain<=D("0.0000000001"))
   result={"symbol":sym,"notional_usdt":amount,"best_bid":str(best_bid),"best_ask":str(best_ask),
      "spread_pct":round(float((best_ask-best_bid)/mid*100),4),"both_sides_fully_filled":full,
      "hypothetical_immediate_resale_usdt":round(float(received),4),
      "roundtrip_book_friction_pct_no_fees":round(float((target-received)/target*100),4) if full else None,
      "roundtrip_loss_usdt_no_fees":round(float(target-received),4) if full else None}
   print("BOOK_COST "+json.dumps(result,separators=(",",":")),flush=True)
 except Exception as e:print("BOOK_ERROR",sym,str(e)[:250],flush=True)
