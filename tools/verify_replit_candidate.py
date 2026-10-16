"""Disposable local PostgreSQL/TLS + real production-Gunicorn verification.

Uses an already cached postgres:16-bookworm Docker image. No image pulls, cloud,
exchange requests or production databases. Credentials exist only in private tmp.
"""
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
import uuid

ROOT=Path(__file__).resolve().parents[1]


def command(args,**kwargs):return subprocess.run(args,check=True,capture_output=True,**kwargs).stdout


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--archives",required=True,type=Path);p.add_argument("--output",required=True,type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    report={"cloud_access":False,"replit_persistence_verified":False,"checks":[],"market_download_requests":0,"database":"DISPOSABLE LOCAL POSTGRESQL TLS VERIFY-FULL"}
    with tempfile.TemporaryDirectory(prefix="hks-persistent-deployment-") as tmp:
        private=Path(tmp);certs=private/"certs";certs.mkdir();certs.chmod(0o755)
        command(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-keyout",str(certs/"server.key"),"-out",str(certs/"server.crt"),"-days","1","-subj","/CN=localhost","-addext","subjectAltName=DNS:localhost,IP:127.0.0.1"])
        password=secrets.token_urlsafe(40);token=secrets.token_urlsafe(40);name="hks-backtester-check-"+uuid.uuid4().hex[:10]
        envfile=private/"postgres.env";envfile.write_text("POSTGRES_DB=hks_disposable\nPOSTGRES_USER=hks_test\nPOSTGRES_PASSWORD="+password+"\n");envfile.chmod(0o600)
        server=None;db_started=False
        try:
            command(["docker","run","--pull","never","-d","--name",name,"--memory","512m","--cpus","1","--env-file",str(envfile),"-p","127.0.0.1::5432","--mount","type=bind,source="+str(certs)+",target=/certs,readonly","--entrypoint","bash","postgres:16-bookworm","-c",
                "mkdir -p /tmp/hks-tls && cp /certs/server.crt /certs/server.key /tmp/hks-tls/ && chown -R postgres:postgres /tmp/hks-tls && chmod 600 /tmp/hks-tls/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/hks-tls/server.crt -c ssl_key_file=/tmp/hks-tls/server.key"])
            db_started=True
            info=json.loads(command(["docker","inspect",name]))[0];dbport=info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
            url=f"postgresql://hks_test:{password}@localhost:{dbport}/hks_disposable?sslmode=verify-full&sslrootcert={certs/'server.crt'}"
            sys.path.insert(0,str(ROOT));from backtester.postgres import PostgresStore
            last_error=None
            for _ in range(100):
                try:store=PostgresStore(url,private/"scratch");break
                except Exception as exc:last_error=exc;time.sleep(.1)
            else:
                diagnostic=(type(last_error).__name__+": "+str(last_error)).replace(password,"[REDACTED]").replace(url,"[DISPOSABLE_DATABASE_URL]")
                (args.output/"STARTUP_DIAGNOSIS.txt").write_text(diagnostic)
                pglog=subprocess.run(["docker","logs",name],capture_output=True,text=True)
                (args.output/"DISPOSABLE_POSTGRES.log").write_text((pglog.stdout+pglog.stderr).replace(password,"[REDACTED]"))
                raise AssertionError("disposable PostgreSQL/TLS startup failed: "+diagnostic)
            report["checks"].append("Actual PostgreSQL connection and new isolated schema over verified TLS")
            import psycopg
            with psycopg.connect(url,autocommit=True) as c:c.execute("CREATE DATABASE hks_verify_aux")
            aux_url=url.replace("/hks_disposable?","/hks_verify_aux?")
            test_env=dict(os.environ,HKS_TEST_POSTGRES_URL=aux_url,HKS_TEST_POSTGRES_DISPOSABLE="YES")
            tests=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests_backtester","-v"],cwd=ROOT,env=test_env,capture_output=True,text=True)
            test_log=(tests.stdout+tests.stderr).replace(password,"[REDACTED]").replace(url,"[DISPOSABLE_DATABASE_URL]").replace(aux_url,"[DISPOSABLE_AUX_URL]")
            (args.output/"FULL_SQLITE_POSTGRES_TESTS.log").write_text(test_log)
            assert tests.returncode==0,test_log[-5000:]
            import re
            report["automated_tests"]={"tests":int(re.search(r"Ran (\d+) tests",test_log).group(1)),"exit_code":tests.returncode,"failures":0,"errors":0,"skipped":0}
            report["checks"].append("Full regression suite including real PostgreSQL import/dedup/gap/conflict and independent-instance coordination tests")
            from backtester.cache import HistoricalCache
            cache=HistoricalCache(store)
            def start_app(scratch):
                nonlocal server
                with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
                env=dict(os.environ,DATABASE_URL=url,HKS_PUBLIC_URL="https://hks-test.replit.app",HKS_BACKTEST_TOKEN=token,HKS_BACKTEST_ENV="production",HKS_BACKTEST_STATE=str(scratch),PORT=str(port))
                log=(args.output/(scratch.name+"-gunicorn.log")).open("w")
                server=subprocess.Popen([sys.executable,"-m","gunicorn","--config","gunicorn.conf.py","app:app"],cwd=ROOT,env=env,stdout=log,stderr=log)
                base=f"http://127.0.0.1:{port}"
                for _ in range(100):
                    try:
                        with urlopen(base+"/ready",timeout=1) as r:
                            if r.status==200:break
                    except OSError:time.sleep(.1)
                else:raise AssertionError("production Gunicorn entrypoint did not become ready")
                return base,log
            def stop_app(log):
                nonlocal server
                if server:
                    server.terminate()
                    try:server.wait(timeout=10)
                    except subprocess.TimeoutExpired:server.kill();server.wait()
                    server=None
                log.close()
            base,log=start_app(private/"fresh-runtime-one")
            headers={"Authorization":"Bearer "+token,"Host":"hks-test.replit.app","Origin":"https://hks-test.replit.app","X-Forwarded-Proto":"https"}
            def request(path,body=None,content_type="application/json"):
                data=None if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
                h=headers|({"Content-Type":content_type} if data is not None else {})
                with urlopen(Request(base+path,data=data,headers=h),timeout=70) as r:return r.status,r.read()
            report["checks"].append("Production app:app / Gunicorn gthread entrypoint, health and readiness")
            catalog=json.loads(request("/api/catalog")[1]);version=catalog["strategies"][0]["version_id"]
            imports=[]
            for sym in ("BTCUSDT","ETHUSDT"):
                path=args.archives/f"{sym}-15m-2026-09.zip";sidecar=Path(str(path)+".CHECKSUM")
                sha=hashlib.sha256(path.read_bytes()).hexdigest();assert sidecar.read_text().split()[0]==sha
                metadata={"exchange":"BINANCE","market":"USDT_LINEAR_PERPETUAL","symbol":sym,"interval":"15m","synthetic":False,"source":f"Owner-supplied official Binance USD-M {path.name}; original retrieval timestamp unknown","retrieved_at":None}
                boundary="hks"+uuid.uuid4().hex
                body=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n"+json.dumps(metadata)+"\r\n").encode()
                for field,file in (("file",path),("checksum",sidecar)):
                    body+=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{file.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()+file.read_bytes()+b"\r\n"
                body+=f"--{boundary}--\r\n".encode()
                status,raw=request("/api/data/import",body,"multipart/form-data; boundary="+boundary);result=json.loads(raw)
                assert status==201 and result["records"]==2880 and result["checksum_verified"],result
                imports.append(result)
            report["checks"].append("Real authenticated multipart ZIP/CHECKSUM intake: 5760 genuine original Futures15m candles")
            cached=json.loads(request("/api/data")[1]);assert sum(s["records"] for s in cached["series"])==5760
            group=cached["series"][0]["group_id"]
            plan=json.loads(request("/api/data/plan",{"metadata":metadata,"start_ms":"2026-09-01T00:00:00Z","end_ms":"2026-10-01T00:15:00Z"})[1]);assert plan["missing_candles"]==1
            report["checks"].append("Indexed exact missing-range plan identifies one absent future interval without downloading")
            config={"start_ms":"2026-09-02T00:00:00Z","end_ms":"2026-09-05T00:00:00Z","mode":"shared","allow_uncertified_futures":True}
            def run(mode,label):
                status,raw=request("/api/runs",{"dataset_id":group,"strategy_version":version,"symbols":["BTCUSDT","ETHUSDT"],"config":config|{"mode":mode}})
                assert status==202;job=json.loads(raw)["id"];stages=[]
                for _ in range(300):
                    record=json.loads(request("/api/runs/"+job)[1])
                    if record.get("progress"):stages.append(record["progress"])
                    if record["status"]!="RUNNING":break
                    time.sleep(.1)
                assert record["status"]=="COMPLETE",record
                assert record["summary"]["closed_trades"]==5 and record["summary"]["open_trades"]==2,record["summary"]
                result=store.get_job(job)["result"]
                for rec in result["reconciliation"].values():assert float(rec["cash_residual"])==0 and float(rec["equity_residual"])==0
                from backtester.cli import export_run
                export_run(store,job,args.output/label)
                return {"id":job,"result_hash":result["result_hash"],"summary":record["summary"],"progress_observed":stages}
            shared1=run("shared","shared-first");shared2=run("shared","shared-reuse")
            assert shared1["result_hash"]==shared2["result_hash"]
            individual=run("individual","individual")
            report["checks"].append("Real asynchronous worker: shared twice identically, individual once, all cash/equity reconciled")
            with store.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM cache_fetch_receipts").fetchone()[0]==0
                assert c.execute("SELECT COUNT(*) FROM cache_imports").fetchone()[0]==2
            report["checks"].append("Repeat backtests: ZERO additional historical downloads, ZERO additional imports, identical shared result hashes")
            stop_app(log)
            command(["docker","restart",name])
            info=json.loads(command(["docker","inspect",name]))[0];newport=info["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
            url=url.replace(":"+dbport+"/",":"+newport+"/")
            for _ in range(100):
                try:store=PostgresStore(url,private/"totally-new-export-scratch");break
                except Exception:time.sleep(.1)
            else:raise AssertionError("PostgreSQL restart failed")
            base,log=start_app(private/"fresh-runtime-two")
            recreated=json.loads(request("/api/data")[1]);assert sum(s["records"] for s in recreated["series"])==5760
            assert json.loads(request("/api/runs/"+shared1["id"])[1])["metadata"]["result_hash"]==shared1["result_hash"]
            shared3=run("shared","shared-after-restart");assert shared3["result_hash"]==shared1["result_hash"]
            report["checks"].append("Actual DB restart + new Gunicorn instance/empty runtime directory: cache, versions, reports survive and repeated result remains identical")
            stop_app(log)
            report.update({"status":"PASS","checks_passed":len(report["checks"]),"imports":imports,"runs":{"shared_first":shared1,"shared_reused":shared2,"individual":individual,"shared_after_restart":shared3},
                           "storage_scope":"Actual PostgreSQL/TLS and local application/database restart verified; Replit account/redeployment NOT accessed or verified"})
        finally:
            if server:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
            if db_started:subprocess.run(["docker","rm","-f",name],capture_output=True)
            (args.output/"DEPLOYMENT_VERIFICATION.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("runs","imports")},indent=2))


if __name__=="__main__":main()
