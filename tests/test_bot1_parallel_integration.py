"""Subprocess integration: exercise Bot 1 parallel Flask endpoints, never hosted."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

WORK=textwrap.dedent("""
from decimal import Decimal as D
from sqlalchemy import func,select
import app
from bot1_parallel import ModePosition,ModeTrade,ModeWallet,open_pair

assert app.BOT1_PARALLEL_ENABLED
app.app.config["TESTING"]=True
client=app.app.test_client()
page=client.get("/")
assert page.status_code==200,page.get_data(as_text=True)[:500]
html=page.get_data(as_text=True)
assert 'data-parallel-mode="on"' in html
assert 'id="equity-chart-other"' in html
assert 'Reset BOTH' in html

for m in ("NORMAL","REVERSE"):
    v=client.get("/api/state?mode="+m)
    assert v.status_code==200,v.get_data(as_text=True)
    j=v.get_json()
    assert j["parallel"] and j["view_mode"]==m
    assert D(str(j["balance"]))==D("1000")
    assert D(str(j["available_cash"]))==D("2000")
    assert len(j["equity_points"])==1
    assert len(j["mode_equity_points"][m])==1

with app.Session.begin() as db:
    coin=app.init_coin(db,"BTCUSDT")
    result=open_pair(db,coin,{"original":"LONG","trade_score":85,
                 "stop_fraction":D("0.01"),"end_ms":1800000},
        D("100"),1800000,app.FEE_RATE,app.RISK_FRACTION,
        app.MAX_POSITION_CASH_FRACTION,app.MAX_POSITIONS)
    assert result["NORMAL"][1]=="OPEN",result
    assert result["REVERSE"][1]=="OPEN",result

n=client.get("/api/state?mode=NORMAL").get_json()
r=client.get("/api/state?mode=REVERSE").get_json()
assert len(n["open_positions"])==1
assert len(r["open_positions"])==1
assert n["open_positions"][0]["side"]=="LONG"
assert r["open_positions"][0]["side"]=="SHORT"
assert n["mode_summaries"]["NORMAL"]["open"]==1
assert n["mode_summaries"]["REVERSE"]["open"]==1

assert client.post("/api/reset",json={"confirm":"RESET BOTH","password":"test-password"},
                   headers={"Origin":"http://localhost"}).status_code==401
login=client.post("/api/owner/login",json={"password":"test-password"},
                  headers={"Origin":"http://localhost"})
assert login.status_code==200,login.get_data(as_text=True)
bad=client.post("/api/reset",json={"confirm":"RESET 1K","password":"test-password"},
                headers={"Origin":"http://localhost"})
assert bad.status_code==400

reset=client.post("/api/reset",json={"confirm":"RESET BOTH","password":"test-password"},
                  headers={"Origin":"http://localhost"})
assert reset.status_code==200,reset.get_data(as_text=True)
with app.Session() as db:
    assert db.scalar(select(func.count()).select_from(ModePosition))==0
    assert db.scalar(select(func.count()).select_from(ModeTrade))==0
    for m in ("NORMAL","REVERSE"):
        assert db.get(ModeWallet,m).cash==D("2000")
assert client.get("/api/history?mode=NORMAL").get_json()["trades"]==[]
assert client.get("/api/history?mode=REVERSE").get_json()["trades"]==[]
print("Bot 1 parallel Flask read-only and owner-reset integration PASS")
""")


class ParallelAPIIntegration(unittest.TestCase):
    def test_parallel_endpoints_and_authorized_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=os.environ.copy()
            env.update({
                "DATABASE_URL":"sqlite:///"+str(Path(tmp)/"isolated.sqlite3"),
                "HKS_BOT1_PARALLEL_ENABLED":"1",
                "VERCEL":"1",
                "HKS_RESET_PASSWORD":"test-password",
            })
            p=subprocess.run([sys.executable,"-c",WORK],cwd=ROOT,env=env,
                             text=True,capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+"\n"+p.stderr)


if __name__=="__main__":
    unittest.main()
