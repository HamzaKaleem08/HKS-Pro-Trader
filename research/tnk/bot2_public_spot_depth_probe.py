"""MEXC TNK+CYS current Spot depth snapshots only, no orders or credentials.
$250 entry/exit hypothetical book walk. This is instantaneous not historical.
"""
import requests,time,json
from decimal import Decimal as D
S=requests.Session();S.headers["User-Agent"]="HKS-Bot2-Research-Only"
def use_depth(side,book,dollars=250):
 target=D(dollars);qty=target
 worst=last=filled=D(0)
 # For buy: consume $250 quote budget. For sell: assume base qty $250/mid
 for price,q in book:
  p=D(price);units=D(q)
  if p<=0 or units<=0:continue
  take=min(units,qty/p) if side=="buy" else min(units,qty)
  filled+=take*p;qty-=take*p if side=="buy" else take
  worst=p
  if qty<=D(".00000001"):break
 return (filled,worst,qty)
for sym in ("TNKUSDT","CYSUSDT"):
 for ix in range(3):
  try:
   r=S.get("https://api.mexc.com/api/v3/depth",params={"symbol":sym,"limit":100},timeout=14)
   r.raise_for_status();book=r.json()
   bids=book["bids"];asks=book["asks"]
   bid=D(bids[0][0]);ask=D(asks[0][0]);mid=(bid+ask)/2
   spread_pct=(ask-bid)/mid*100
   buy_amount,buy_worst,buy_left=use_depth("buy",asks,250)
   qty=D(250)/mid
   sell_amount,sell_worst,sell_left=use_depth("sell",bids,qty)
   d={"symbol":sym,"snapshot":ix+1,"best_bid":str(bid),"best_ask":str(ask),
     "spread_pct":round(float(spread_pct),4),"bid_depth_usd_2pct":round(float(sum(D(x[0])*D(x[1]) for x in bids if D(x[0])>=mid*D(".98"))),2),
     "ask_depth_usd_2pct":round(float(sum(D(x[0])*D(x[1]) for x in asks if D(x[0])<=mid*D("1.02"))),2),
     "buy250_full":buy_left<=D(".00000001"),
     "sell250_full":sell_left<=D(".00000001"),
     "buy250_last_price":str(buy_worst),"sell250_last_price":str(sell_worst),
     "buy250_impact_pct":round(float((buy_worst/mid-1)*100),3),
     "sell250_impact_pct":round(float((1-sell_worst/mid)*100),3)}
   print("DEPTH_SNAPSHOT",json.dumps(d),flush=True)
  except Exception as exc:print("DEPTH_ERROR",sym,ix,str(exc)[:250],flush=True)
  time.sleep(2)
