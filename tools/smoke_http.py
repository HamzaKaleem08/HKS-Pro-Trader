"""Real loopback HTTP checks with a disposable server and synthetic data only."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen


def main():
    root=Path(__file__).resolve().parents[1];out=root/"evidence"/"http-smoke";out.mkdir(parents=True,exist_ok=True)
    checks=[]
    with tempfile.TemporaryDirectory(prefix="hks-http-smoke-") as tmp:
        token=secrets.token_urlsafe(40);state=Path(tmp)/"state";env=dict(os.environ,HKS_BACKTEST_TOKEN=token,HKS_BACKTEST_ENV="local")
        subprocess.run([sys.executable,"-m","backtester.cli","--state",str(state),"init-demo"],cwd=root,env=env,check=True,capture_output=True)
        with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        origin=f"http://127.0.0.1:{port}"
        def request(path,body=None,authenticated=True,extra=None):
            headers=({"Authorization":"Bearer "+token} if authenticated else {})|(extra or {})
            data=None if body is None else json.dumps(body).encode()
            if data is not None:headers["Content-Type"]="application/json"
            with urlopen(Request(origin+path,data=data,headers=headers),timeout=45) as r:
                return r.status,r.headers,r.read()
        with (out/"SERVER.log").open("w") as log:
            process=subprocess.Popen([sys.executable,"-m","backtester.cli","--state",str(state),"serve","--port",str(port)],cwd=root,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:request("/health",authenticated=False);break
                    except OSError:time.sleep(.05)
                else:raise AssertionError("local server failed startup")
                checks.append("real loopback server startup and health")
                try:request("/api/catalog",authenticated=False);raise AssertionError("unauthenticated access")
                except HTTPError as e:assert e.code==401
                checks.append("real HTTP authentication enforcement")
                for asset in ("/","/assets/app.js","/assets/style.css"):
                    status,headers,data=request(asset,authenticated=False)
                    assert status==200 and headers["X-Content-Type-Options"]=="nosniff" and token.encode() not in data
                checks.append("HTML/JavaScript/CSS serving and security headers")
                catalog=json.loads(request("/api/catalog")[2]);version=catalog["strategies"][0]["version_id"]
                totals={}
                for mode in ("shared","individual"):
                    body={"dataset_id":"synthetic-demo","strategy_version":version,"symbols":["BTCUSDT","ETHUSDT"],
                          "config":{"start_ms":"2025-11-01T00:30:00Z","end_ms":"2025-11-01T16:00:00Z","mode":mode}}
                    status,_,raw=request("/api/runs",body);assert status==201
                    run=json.loads(raw);job=run["id"]
                    assert run["summary"]["closed_trades"]>25
                    assert run["summary"]["starting_capital"]==("1000" if mode=="shared" else "2000")
                    totals[mode]={"closed_trades":run["summary"]["closed_trades"],"result_hash":run["result_hash"]}
                    checks.append(f"real HTTP {mode} request launches actual bounded worker and reconciles report")
                    report=json.loads(request("/api/runs/"+job)[2])
                    assert all(v["cash_residual"].strip("0.")=="" and v["equity_residual"].strip("0.")=="" for v in report["metadata"]["reconciliation"].values())
                    page1=json.loads(request(f"/api/runs/{job}/trades?size=25&page=1&sort=net_pnl&direction=desc")[2])
                    page2=json.loads(request(f"/api/runs/{job}/trades?size=25&page=2&sort=net_pnl&direction=desc")[2])
                    assert page1["trades"] and page2["trades"]
                    assert not {t["trade_id"] for t in page1["trades"]}&{t["trade_id"] for t in page2["trades"]}
                    checks.append(f"{mode} server-side sorted pagination has disjoint pages")
                    coin=json.loads(request(f"/api/runs/{job}/trades?q=ETHUSDT")[2]);assert all(t["symbol"]=="ETHUSDT" for t in coin["trades"])
                    trade=page1["trades"][0]
                    assert json.loads(request(f"/api/runs/{job}/trade/{trade['trade_id']}")[2])==trade
                    checks.append(f"{mode} filtering and trade-detail API")
                    for kind in ("trades","coins","decisions"):
                        _,headers,csv_bytes=request(f"/api/runs/{job}/export/{kind}")
                        assert "attachment" in headers["Content-Disposition"]
                        (out/f"{mode}-{kind}.csv").write_bytes(csv_bytes)
                        if kind=="trades":assert len(list(csv.DictReader(io.StringIO(csv_bytes.decode()))))==page1["total"]
                    checks.append(f"{mode} real CSV transfer is complete and matches trade count")
                receipt={"status":"PASS","checks":checks,"check_count":len(checks),"runs":totals,
                         "scope":"real HTTP and API contracts; browser clicks/rendering NOT tested here",
                         "external_network_requests":0,"data":"synthetic only"}
                (out/"HTTP_RESULTS.json").write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))
            finally:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=="__main__":main()
