from flask import Flask, jsonify
import requests, os
from datetime import datetime, timedelta
from deta import Deta

app = Flask(__name__)
deta = Deta()
db = deta.Base("hks_wallet")
cache_db = deta.Base("hks_cache")

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT","DOTUSDT","ADAUSDT","XRPUSDT","AVAXUSDT","LINKUSDT","POLUSDT","LTCUSDT"]
BINANCE_URL = "https://data-api.binance.vision/api/v3"
DEFAULT_BALANCE = 1000.0

def get_wallet():
    res = db.get("main_wallet")
    if res: return res["data"]
    data = {"balance": DEFAULT_BALANCE, "open_positions": {}, "trades": [], "history": [DEFAULT_BALANCE]}
    db.put({"key": "main_wallet", "data": data})
    return data

def save_wallet(data):
    db.put({"key": "main_wallet", "data": data})

def get_klines(symbol):
    try:
        return requests.get(f"{BINANCE_URL}/klines?symbol={symbol}&interval=15m&limit=50", timeout=10).json()
    except: return None

def get_session_info():
    now_utc = datetime.utcnow()
    hour = now_utc.hour
    gmt_str = now_utc.strftime("%H:%M GMT")
    if 8 <= hour < 17: return f"LONDON ● LIVE", gmt_str, True
    elif 13 <= hour < 22: return f"NY ● LIVE", gmt_str, True
    else:
        next_open = now_utc.replace(hour=8, minute=0, second=0, microsecond=0)
        if hour >= 8: next_open += timedelta(days=1)
        diff = next_open - now_utc
        h = int(diff.total_seconds() // 3600); m = int((diff.total_seconds() % 3600) // 60)
        return f"OFF - London in {h}h {m}m", gmt_str, False

def scan_logic(symbol, WALLET):
    try:
        klines = get_klines(symbol)
        if not klines or len(klines) < 30: return None
        closes = [float(k[4]) for k in klines]; highs = [float(k[2]) for k in klines]; lows = [float(k[3]) for k in klines]
        curr = closes[-1]

        tr_list = []
        for i in range(1, len(klines)):
            tr = max(float(klines[i][2]) - float(klines[i][3]), abs(float(klines[i][2]) - float(klines[i-1][4])), abs(float(klines[i][3]) - float(klines[i-1][4])))
            tr_list.append(tr)
        atr = sum(tr_list[-14:]) / 14
        atr_perc = atr / curr
        stop_perc = max(0.008, min(0.03, atr_perc * 1.5))
        tp_perc = stop_perc * 2.0

        # ===== GOD LEVEL TRAILING - 100% CLEAN BOSS =====
        if symbol in WALLET.get("open_positions", {}):
            pos = WALLET["open_positions"][symbol]
            entry = pos["entry"]
            tp = pos["tp"]

            if pos["side"] == "LONG":
                total_distance = tp - entry
                if total_distance > 0:
                    covered = curr - entry
                    progress = (covered / total_distance) * 100

                    # FINAL CLEAN LOGIC BOSS - 10% GAP + 5% TRAILING BOSS!
                    final_sl = None
                    if progress >= 80:
                        final_sl = entry + (total_distance * (progress - 10) / 100) # 80->70, 85->75, 100->90, 120->110 Boss - PERFECT!
                    elif progress >= 50:
                        final_sl = entry + (total_distance * 0.10) # 50% -> 10% Boss

                    if final_sl and final_sl > pos["sl"]:
                        WALLET["open_positions"][symbol]["sl"] = final_sl

                    if curr <= WALLET["open_positions"][symbol]["sl"]:
                        pnl = (WALLET["open_positions"][symbol]["sl"] - entry) * pos["qty"]
                        WALLET["balance"] += (pnl + pos["risk"])
                        WALLET["history"].append(round(WALLET["balance"],2))
                        WALLET["trades"].append({"symbol": symbol, "side": pos["side"], "pnl": round(pnl,2), "reason": f"TRAIL BOOK {progress:.0f}%", "progress": round(progress,1)})
                        del WALLET["open_positions"][symbol]
                        return {"symbol": symbol, "price": curr, "score": 0, "side": "HOLD", "status": f"BOOKED {progress:.0f}%", "color_type": "hold", "progress": progress}

            else: # SHORT Boss - Same clean logic Boss
                total_distance = entry - tp
                if total_distance > 0:
                    covered = entry - curr
                    progress = (covered / total_distance) * 100

                    final_sl = None
                    if progress >= 80:
                        final_sl = entry - (total_distance * (progress - 10) / 100)
                    elif progress >= 50:
                        final_sl = entry - (total_distance * 0.10)

                    if final_sl and final_sl < pos["sl"]:
                        WALLET["open_positions"][symbol]["sl"] = final_sl

                    if curr >= WALLET["open_positions"][symbol]["sl"]:
                        pnl = (entry - WALLET["open_positions"][symbol]["sl"]) * pos["qty"]
                        WALLET["balance"] += (pnl + pos["risk"])
                        WALLET["history"].append(round(WALLET["balance"],2))
                        WALLET["trades"].append({"symbol": symbol, "side": pos["side"], "pnl": round(pnl,2), "reason": f"TRAIL BOOK {progress:.0f}%", "progress": round(progress,1)})
                        del WALLET["open_positions"][symbol]
                        return {"symbol": symbol, "price": curr, "score": 0, "side": "HOLD", "status": f"BOOKED {progress:.0f}%", "color_type": "hold", "progress": progress}

        swingH = max(highs[-21:-1]); swingL = min(lows[-21:-1])
        bullSweep = lows[-1] < swingL and curr > swingL
        bearSweep = highs[-1] > swingH and curr < swingH
        bullMSS = any(c > swingH for c in closes[-4:-1]); bearMSS = any(c < swingL for c in closes[-4:-1])
        bullFVG = lows[-1] > highs[-3]; bearFVG = highs[-1] < lows[-3]
        score, side, status, ctype = 0, None, "NO SETUP", "hold"
        if bullSweep or bearSweep:
            score = 35; side = "LONG" if bullSweep else "SHORT"; status = "SWEEP"
            if (bullSweep and bullMSS) or (bearSweep and bearMSS): score += 35; status = "MSS OK"
            if (bullSweep and bullFVG) or (bearSweep and bearFVG): score += 20; status = "FVG OK"
            _, _, is_live = get_session_info()
            if is_live: score += 10
            else: score = 0; status = "SESSION OFF"
            if score >= 80:
                status = f"BEST A++"; ctype = "buy" if side == "LONG" else "sell"
                if symbol not in WALLET.get("open_positions", {}):
                    risk = WALLET["balance"] * 0.01
                    if WALLET["balance"] > risk:
                        pos_val = risk / stop_perc; qty = pos_val / curr
                        sl_price = curr * (1 - stop_perc) if side == "LONG" else curr * (1 + stop_perc)
                        tp_price = curr * (1 + tp_perc) if side == "LONG" else curr * (1 - tp_perc)
                        WALLET["open_positions"][symbol] = {"side": side, "entry": curr, "qty": qty, "sl": sl_price, "tp": tp_price, "risk": risk}
                        WALLET["balance"] -= risk
            elif score >= 50: status = "SETUP"

        prog = 0
        if symbol in WALLET.get("open_positions", {}):
            p = WALLET["open_positions"][symbol]
            if p["side"] == "LONG": prog = ((curr - p["entry"]) / (p["tp"] - p["entry"]) * 100) if (p["tp"] - p["entry"]) > 0 else 0
            else: prog = ((p["entry"] - curr) / (p["entry"] - p["tp"]) * 100) if (p["entry"] - p["tp"]) > 0 else 0

        return {"symbol": symbol, "price": curr, "score": score, "side": side if side else "HOLD", "status": status, "color_type": ctype, "progress": round(prog,1)}
    except: return None

@app.route("/api/cron")
def cron_job():
    WALLET = get_wallet()
    results = []
    for symbol in COINS:
        res = scan_logic(symbol, WALLET)
        if res: results.append(res)
    save_wallet(WALLET)
    results.sort(key=lambda x: x['score'], reverse=True)
    session_text, gmt_str, is_live = get_session_info()
    cache_db.put({"key": "cache", "board": results, "session_text": session_text, "gmt": gmt_str, "is_live": is_live})
    return jsonify({"status": "ok", "scanned": len(results), "balance": WALLET["balance"]})

@app.route("/api/data")
def api_data():
    WALLET = get_wallet()
    cache = cache_db.get("cache")
    if not cache: return jsonify({"board": [], "session_text": "WAITING CRON", "gmt": "", "is_live": False, "wallet": WALLET, "stats": {"wins":0,"losses":0,"open":0}})
    wins = len([t for t in WALLET.get("trades", []) if t.get("pnl",0) > 0]); losses = len([t for t in WALLET.get("trades", []) if t.get("pnl",0) <= 0])
    return jsonify({"board": cache["board"], "session_text": cache["session_text"], "gmt": cache["gmt"], "is_live": cache["is_live"], "wallet": WALLET, "stats": {"wins": wins, "losses": losses, "open": len(WALLET.get("open_positions", {}))}})

@app.route("/reset_wallet")
def reset_wallet_route():
    save_wallet({"balance": DEFAULT_BALANCE, "open_positions": {}, "trades": [], "history": [DEFAULT_BALANCE]})
    return "<script>alert('Wallet Reset $1000 Boss!');window.location.href='/';</script>"

@app.route("/")
def dashboard():
    return """<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>HKS.PRO FINAL</title></head><body style="background:#0A0E17;color:#fff;font-family:sans-serif;padding:20px"><h2>HKS.PRO GOD CLEAN 10% GAP</h2><div id="board">Loading...</div><script>setInterval(()=>fetch('/api/data').then(r=>r.json()).then(d=>{let h=`Balance: $${d.wallet.balance.toFixed(2)} | ${d.stats.wins}W/${d.stats.losses}L | Open: ${d.stats.open}<br><br>`;d.board.forEach(r=>h+=`${r.symbol} ${r.status} ${r.progress||0}% - ${r.score}% ${r.side}<br>`);document.getElementById('board').innerHTML=h}),2000)</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
