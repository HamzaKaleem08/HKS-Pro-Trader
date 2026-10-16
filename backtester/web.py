"""Separate authenticated LOCAL Flask app. The unsafe legacy app is not mounted."""
from collections import defaultdict, deque
import hmac
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import json
import tempfile

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .catalog import dataset_path,list_datasets
from .common import digest, identifier
from .config import RunConfig
from .errors import ResourceLimit,ValidationError
from .jobs import run_worker
from .reports import build_reports,csv_report
from .storage import Store
from .strategies import validate_definition
from .strategies import build_strategy,DEMO_DEFINITION
from .settings import storage,public_origin
from .cache import HistoricalCache
from .progress import Progress


def create_app(*, state_dir=None, token=None, port=8081, hosted=None, database_url=None, async_jobs=None, allow_test_plaintext=False):
    # Fail closed: no shared default or implicit authentication bypass.
    token = os.environ.get("HKS_BACKTEST_TOKEN","") if token is None else token
    if not isinstance(token,str) or len(token)<32 or len(token)>256 or any(c.isspace() for c in token):
        raise ValidationError("HKS_BACKTEST_TOKEN must be an owner-generated secret with at least 32 characters")
    hosted=(os.environ.get("HKS_BACKTEST_ENV","local") in ("production","hosted")) if hosted is None else hosted
    async_jobs=hosted if async_jobs is None else async_jobs
    origin=public_origin(os.environ.get("HKS_PUBLIC_URL")) if hosted else None
    state_dir = Path(state_dir or os.environ.get("HKS_BACKTEST_STATE",".backtester-state")).resolve()
    assets = Path(__file__).resolve().parent/"web"
    app = Flask("hks_offline_backtester",static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=26*1024*1024,JSON_SORT_KEYS=True,MAX_FORM_MEMORY_SIZE=64*1024,MAX_FORM_PARTS=10)
    store=storage(state_dir,hosted=hosted,database_url=database_url,allow_test_plaintext=allow_test_plaintext)
    cache=HistoricalCache(store);progress=Progress(store)
    store.save_strategy(DEMO_DEFINITION)
    app.extensions["research_store"] = store
    app.extensions.update(historical_cache=cache,job_progress=progress)
    buckets = defaultdict(deque)
    mutex = threading.Lock()
    allowed_hosts = {f"127.0.0.1:{port}",f"localhost:{port}","localhost","127.0.0.1"}
    allowed_origins={"http://"+h for h in allowed_hosts}
    if hosted:
        from urllib.parse import urlsplit
        allowed_hosts.add(urlsplit(origin).netloc);allowed_origins={origin}

    @app.before_request
    def protect():
        if request.host not in allowed_hosts:
            return jsonify(error="untrusted host"),400
        origin = request.headers.get("Origin")
        if origin and origin not in allowed_origins:
            return jsonify(error="cross-origin access denied"),403
        # Ignore X-Forwarded-*; this app is local only and is not a proxy deployment.
        if request.path.startswith("/api/"):
            if hosted and not (request.is_secure or request.headers.get("X-Forwarded-Proto","").split(",")[0].strip()=="https"):
                return jsonify(error="HTTPS required through the Replit TLS proxy"),400
            supplied=request.headers.get("Authorization","")
            if len(supplied)>512 or not hmac.compare_digest(supplied.encode(),("Bearer "+token).encode()):
                return jsonify(error="authentication required"),401
            key=({"/api/runs":"run","/api/data/import":"import","/api/data/fetch":"fetch"}.get(request.path,"api") if request.method=="POST" else "api")
            with mutex:
                now=time.monotonic();b=buckets[key]
                while b and b[0] <= now-60: b.popleft()
                if len(b)>={"run":5,"import":12,"fetch":3,"api":240}[key]:
                    return jsonify(error="local request-rate bound reached"),429
                b.append(now)
            if request.path!="/api/data/import" and request.content_length and request.content_length>16*1024:
                return jsonify(error="JSON request limit16KiB"),413
            if request.method=="POST" and not request.is_json and request.path!="/api/data/import":
                return jsonify(error="application/json required"),415

    @app.after_request
    def headers(response):
        response.headers.update({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                                 "Referrer-Policy":"no-referrer","X-Frame-Options":"DENY",
                                 "Content-Security-Policy":"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})
        if hosted:response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    @app.errorhandler(ValidationError)
    def validation(exc):return jsonify(error=str(exc)),400

    @app.errorhandler(ResourceLimit)
    def bounded(exc):return jsonify(error=str(exc)),429

    @app.errorhandler(sqlite3.OperationalError)
    def db_busy(exc):return jsonify(error="research database unavailable or busy; retry after the active operation finishes"),503

    @app.errorhandler(RecursionError)
    def nested_payload(exc):return jsonify(error="input nesting exceeds the supported structured contract"),400

    @app.errorhandler(Exception)
    def safe_error(exc):
        if isinstance(exc,HTTPException):return jsonify(error=exc.name),exc.code
        app.logger.error("backtester_request_failed type=%s",type(exc).__name__)
        return jsonify(error="internal request failure; no successful result reported"),500

    @app.get("/")
    def index():return send_from_directory(assets,"index.html")

    @app.get("/assets/<name>")
    def asset(name):
        if name not in ("app.js","style.css"):return jsonify(error="not found"),404
        return send_from_directory(assets,name)

    @app.get("/health")
    def health():return jsonify(status="ok",mode="hosted" if hosted else "local",durable_backend=store.durable)

    @app.get("/ready")
    def ready():
        try:
            with store.connect() as c:c.execute("SELECT 1")
        except Exception:return jsonify(status="not_ready",error="persistent database unavailable"),503
        return jsonify(status="ready",durable_backend=store.durable)

    @app.get("/api/catalog")
    def catalog():
        return jsonify(datasets=cache.groups()+([] if hosted else list_datasets(state_dir/"datasets")),strategies=store.list_strategies(),runs=store.list_jobs(),
                       limits={"rows":200000,"symbols":20,"max_entries":10000,"worker_wall_seconds":40,"worker_memory_mib_linux":512},
                       storage={"backend":store.backend,"durable_configured":store.durable,"replit_redeploy_persistence_verified":False},
                       async_jobs=async_jobs,
                       unsupported=["Authentic Normal/Reverse parity","Arbitrary Python/JavaScript","Live/paper trading","Certified funding/liquidation/exchange filters"])

    @app.get("/api/data")
    def data_inventory():return jsonify(cache.inventory(request.args.get("q","")))

    @app.post("/api/data/import")
    def import_data():
        if request.mimetype!="multipart/form-data":return jsonify(error="multipart/form-data with file and metadata JSON required"),415
        if set(request.files)-{"file","checksum"} or set(request.form)!={"metadata"}:raise ValidationError("expected file, optional checksum, metadata only")
        upload=request.files.get("file")
        if upload is None:raise ValidationError("CSV/ZIP file required")
        try:meta=json.loads(request.form["metadata"])
        except ValueError:raise ValidationError("invalid source metadata JSON") from None
        checksum=request.files.get("checksum")
        check=None
        if checksum:
            raw=checksum.read(2049)
            if len(raw)>2048:raise ValidationError("CHECKSUM sidecar too large")
            try:check=raw.decode("ascii")
            except UnicodeError:raise ValidationError("CHECKSUM must be ASCII") from None
        return jsonify(cache.ingest(upload.stream,upload.filename,meta,check)),201

    @app.post("/api/data/plan")
    def plan_data():
        raw=request.get_json()
        if not isinstance(raw,dict) or set(raw)!={"metadata","start_ms","end_ms"}:raise ValidationError("expected metadata,start_ms,end_ms")
        gaps=cache.missing(raw["metadata"],raw["start_ms"],raw["end_ms"])
        return jsonify(missing=gaps,missing_candles=sum(g["candles"] for g in gaps),download_requests=0)

    @app.post("/api/data/fetch")
    def fetch_data():
        from .acquire import fetch_missing
        raw=request.get_json()
        if not isinstance(raw,dict) or set(raw)!={"metadata","start_ms","end_ms"}:raise ValidationError("expected metadata,start_ms,end_ms")
        return jsonify(fetch_missing(cache,raw["metadata"],raw["start_ms"],raw["end_ms"]))

    def execute_job(job,path,definition,raw_config,symbols,cached_id):
        try:
            progress.set(job,10,"Preparing verified cached range and indicator warm-up")
            with tempfile.TemporaryDirectory(prefix="job-input-",dir=state_dir) as tmp:
                if cached_id:
                    path=cache.export_bundle(cached_id,symbols,raw_config["start_ms"],raw_config["end_ms"],build_strategy(definition).warmup_bars,Path(tmp)/"dataset")
                progress.set(job,25,"Simulating in bounded Python worker (phase progress, not candle percentage)")
                result,limits=run_worker(path,definition,raw_config,symbols,state_dir)
                progress.set(job,95,"Persisting reconciled immutable report")
                store.finish_job(job,result)
                progress.set(job,100,"COMPLETE")
                return result,limits
        except (ValidationError,ResourceLimit) as exc:
            store.finish_job(job,error=str(exc));progress.set(job,100,"FAILED: "+str(exc))
            if not async_jobs:raise
        except Exception:
            try:store.finish_job(job,error="internal worker failure; no result accepted");progress.set(job,100,"FAILED")
            except Exception:app.logger.error("job_status_update_failed")
            if not async_jobs:raise
            app.logger.error("background_job_failed")

    @app.post("/api/strategies")
    def save_strategy():
        definition=validate_definition(request.get_json())
        return jsonify(version_id=store.save_strategy(definition),activation_changed=False),201

    @app.post("/api/runs")
    def run():
        raw=request.get_json()
        if not isinstance(raw,dict) or set(raw)!={"dataset_id","strategy_version","symbols","config"}:
            raise ValidationError("run requires dataset_id, strategy_version, symbols and config only")
        identifier(raw["dataset_id"])
        cached_id=raw["dataset_id"] if raw["dataset_id"].startswith("cache_") else None
        if hosted and not cached_id:raise ValidationError("Hosted runs must use persistent-cache datasets; import historical data first")
        path=None if cached_id else dataset_path(state_dir/"datasets",raw["dataset_id"])
        definition=store.get_strategy(raw["strategy_version"])
        config=RunConfig.from_dict(raw["config"])
        symbols=raw["symbols"]
        if not isinstance(symbols,list) or not 1<=len(symbols)<=20 or not all(isinstance(s,str) for s in symbols):
            raise ValidationError("symbols must be a list of 1–20 available identities")
        progress.recover_stale()
        job=store.begin_job(with_progress=True)
        if async_jobs:
            threading.Thread(target=execute_job,args=(job,path,definition,raw["config"],symbols,cached_id),daemon=True,name="bounded-backtest").start()
            return jsonify(id=job,status="RUNNING",progress=progress.get(job)),202
        result,limits=execute_job(job,path,definition,raw["config"],symbols,cached_id)
        return jsonify(id=job,status="COMPLETE",worker_limits=limits,result_hash=result["result_hash"],**build_reports(result)),201

    @app.get("/api/runs/<job>")
    def get_run(job):
        progress.recover_stale()
        record=store.get_job(job);result=record.pop("result")
        if result is None:return jsonify(**record,progress=progress.get(job))
        return jsonify(**record,**build_reports(result),metadata={k:result[k] for k in (
            "label","market","exchange","source","synthetic","strategy_version","strategy_hash","dataset_hash",
            "result_hash","config","coverage","warnings","reconciliation","input_hashes","strategy_parity")},open_positions=result["open_positions"])

    @app.get("/api/runs/<job>/trades")
    def trades(job):
        result=store.get_job(job)["result"]
        if result is None:raise ValidationError("run has no complete result")
        q=request.args.get("q","")
        if len(q)>100:raise ValidationError("search exceeds 100 characters")
        try:
            page=int(request.args.get("page","1"));size=int(request.args.get("size","25"))
        except ValueError:raise ValidationError("invalid pagination") from None
        if not 1<=page<=10000 or not 1<=size<=100:raise ValidationError("invalid pagination bounds")
        sort=request.args.get("sort","exit_ms");direction=request.args.get("direction","asc")
        if sort not in ("entry_ms","exit_ms","symbol","net_pnl","holding_ms") or direction not in ("asc","desc"):
            raise ValidationError("invalid sorting")
        rows=[t for t in result["trades"] if q.lower() in (t["symbol"]+" "+t["side"]+" "+t["exit_reason"]+" "+t["trade_id"]).lower()]
        from decimal import Decimal
        rows.sort(key=lambda t:(Decimal(str(t[sort])) if sort=="net_pnl" else t[sort],t["trade_id"]),reverse=direction=="desc")
        return jsonify(total=len(rows),page=page,size=size,trades=rows[(page-1)*size:page*size])

    @app.get("/api/runs/<job>/trade/<trade_id>")
    def detail(job,trade_id):
        identifier(trade_id)
        result=store.get_job(job)["result"]
        if result is None:raise ValidationError("run has no result")
        row=next((t for t in result["trades"] if t["trade_id"]==trade_id),None)
        if row is None:return jsonify(error="unknown trade"),404
        return jsonify(row)

    @app.get("/api/runs/<job>/export/<kind>")
    def export(job,kind):
        if kind not in ("trades","coins","decisions"):return jsonify(error="not found"),404
        result=store.get_job(job)["result"]
        if result is None:raise ValidationError("run has no complete result")
        return Response(csv_report(result,kind),mimetype="text/csv",headers={"Content-Disposition":f'attachment; filename="{job}-{kind}.csv"'})

    return app
