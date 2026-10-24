"""Production smoke: read-only checks on HKS Vercel site, never prints account values."""
import json,urllib.request,urllib.error,sys,time
base="https://hks-pro-trader.vercel.app"
checks=[
 ("/api/bot2/state","bot2-state"),
 ("/bot2","bot2-html"),
 ("/api/state","bot1-state"),
 ("/","bot1-html"),
 ("/healthz","health") ]
for path, label in checks:
    req=urllib.request.Request(base+path,headers={"User-Agent":"HKS-Bot2-ReadOnly-Public-Smoke/1.0","Cache-Control":"no-cache"})
    try:
        with urllib.request.urlopen(req,timeout=35) as r:
            content=r.read(120000)
            status=r.status
            typ=r.headers.get("Content-Type","")
    except Exception as exc:
        print("PROD_SMOKE_FAILURE",label,type(exc).__name__,str(exc)[:140],flush=True)
        raise
    if label.endswith("-state") or label=="health":
        try:
            payload=json.loads(content)
            if label=="bot2-state":
                assert payload["bot"]=="BOT 2"
                assert {x["symbol"] for x in payload["coins"]}=={"TNKUSDT","CYSUSDT"}
                assert payload["initial_sl_multiplier"]==2
                assert payload["score_min"]==85
                print("PROD_SMOKE_BOT2",json.dumps({"http":status,"coins":2,
                    "paper_enabled":payload["paper_enabled"],
                    "scanner_status":payload["scanner"]["status"]}),flush=True)
            elif label=="bot1-state":
                assert "coins" in payload and "balance" in payload and "scanner" in payload
                print("PROD_SMOKE_BOT1",json.dumps({"http":status,
                    "coin_count":len(payload["coins"]),"scanner_status":payload["scanner"]["status"]}),flush=True)
            else:
                assert payload.get("http")=="ok"
                print("PROD_SMOKE_HEALTH",status,flush=True)
        except Exception as e:
            print("PROD_SMOKE_BAD_JSON",label,status,typ,str(e)[:130],flush=True)
            raise
    else:
        html=content.decode("utf-8")
        assert status==200
        if label=="bot2-html":
            assert "TNKUSDT" in html and "CYSUSDT" in html and "MEXC Spot" in html
        else:
            assert 'href="/bot2"' in html
        print("PROD_SMOKE_HTML",label,status,flush=True)
print("PROD_SMOKE_PASS",flush=True)
