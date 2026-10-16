from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtester.catalog import dataset_path,import_bundle
from backtester.cli import init_demo,export_run
from backtester.common import timestamp
from backtester.errors import ResourceLimit,ValidationError
from backtester.jobs import run_worker
from backtester.storage import Store
from backtester.strategies import DEMO_DEFINITION
from backtester.web import create_app

# Disposable test authentication only; not a production credential.
TOKEN="synthetic-local-unit-test-token-only-000000"
HEADERS={"Authorization":"Bearer "+TOKEN}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root)
    def tearDown(self):self.tmp.cleanup()

    def test_immutable_versions(self):
        v=self.store.save_strategy(DEMO_DEFINITION)
        with self.assertRaises(sqlite3.IntegrityError),self.store.connect() as c:
            c.execute("UPDATE strategies SET definition='{}' WHERE version_id=?",(v,))
        self.assertEqual(self.store.get_strategy(v),DEMO_DEFINITION)

    def test_different_strategy_edit_creates_new_version(self):
        a=self.store.save_strategy(DEMO_DEFINITION);b=self.store.save_strategy(DEMO_DEFINITION|{"fast":6})
        self.assertNotEqual(a,b);self.assertEqual(len(self.store.list_strategies()),2)

    def test_cross_process_style_job_admission(self):
        def start(i):
            try:return Store(self.root).begin_job()
            except ResourceLimit:return None
        with ThreadPoolExecutor(max_workers=6) as ex:jobs=list(ex.map(start,range(6)))
        self.assertEqual(sum(v is not None for v in jobs),1)

    def test_restart_preserves_interrupted_state(self):
        job=self.store.begin_job();reopened=Store(self.root)
        self.assertEqual(reopened.get_job(job)["status"],"RUNNING")
        with self.assertRaises(ResourceLimit):reopened.begin_job()
        self.assertEqual(reopened.recover_interrupted(),1)
        self.assertEqual(reopened.get_job(job)["status"],"INTERRUPTED")
        self.assertTrue(reopened.begin_job())

    def test_completed_results_immutable_and_restart_persistent(self):
        job=self.store.begin_job();self.store.finish_job(job,{"synthetic":True})
        with self.assertRaises(ValidationError):self.store.finish_job(job,{"different":True})
        self.assertEqual(Store(self.root).get_job(job)["result"],{"synthetic":True})

    def test_dataset_import_never_overwrites(self):
        init_demo(self.root)
        with self.assertRaisesRegex(ValidationError,"already exists"):
            import_bundle(self.root/"datasets"/"synthetic-demo",self.root/"datasets")


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.version=init_demo(self.root)
        self.app=create_app(state_dir=self.root,token=TOKEN);self.client=self.app.test_client()
    def tearDown(self):self.tmp.cleanup()

    def body(self):
        return {"dataset_id":"synthetic-demo","strategy_version":self.version,"symbols":["BTCUSDT","ETHUSDT"],
                "config":{"start_ms":"2025-11-01T00:30:00Z","end_ms":"2025-11-01T04:00:00Z","mode":"shared"}}

    def test_authentication_all_data_and_mutations(self):
        for path in ("/api/catalog","/api/runs/run_fake","/api/runs/run_fake/trades","/api/runs/run_fake/export/trades"):
            self.assertEqual(self.client.get(path).status_code,401)
        for path in ("/api/runs","/api/strategies"):
            self.assertEqual(self.client.post(path,json={}).status_code,401)

    def test_wrong_and_unicode_auth(self):
        for value in ("Bearer wrong","Bearer "+"é"*40,"Bearer "+"x"*600):
            self.assertEqual(self.client.get("/api/catalog",headers={"Authorization":value}).status_code,401)

    def test_no_token_in_public_html_or_catalog(self):
        with self.client.get("/") as response:
            self.assertNotIn(TOKEN,response.text)
        self.assertNotIn(TOKEN,self.client.get("/api/catalog",headers=HEADERS).text)

    def test_host_origin_csrf_and_cors(self):
        self.assertEqual(self.client.get("/api/catalog",headers=HEADERS|{"Host":"evil.example"}).status_code,400)
        self.assertEqual(self.client.post("/api/strategies",json=DEMO_DEFINITION,headers=HEADERS|{"Origin":"https://evil.example"}).status_code,403)
        self.assertNotIn("Access-Control-Allow-Origin",self.client.get("/",headers={"Origin":"https://evil.example"}).headers)

    def test_malformed_decimal_is_400_not_500(self):
        b=self.body();b["config"]["fee_bps"]="bad decimal"
        r=self.client.post("/api/runs",json=b,headers=HEADERS)
        self.assertEqual(r.status_code,400);self.assertIn("finite decimal",r.json["error"])
        self.assertEqual(self.app.extensions["research_store"].list_jobs(),[])

    def test_malformed_json_and_content_type(self):
        self.assertEqual(self.client.post("/api/strategies",data="{",content_type="application/json",headers=HEADERS).status_code,400)
        self.assertEqual(self.client.post("/api/strategies",data="{}",headers=HEADERS).status_code,415)

    def test_deep_json_is_validation_response(self):
        self.assertEqual(self.client.post("/api/strategies",data="["*1500+"0"+"]"*1500,content_type="application/json",headers=HEADERS).status_code,400)

    def test_request_size_limit(self):
        self.assertEqual(self.client.post("/api/strategies",data="x"*17000,content_type="application/json",headers=HEADERS).status_code,413)

    def test_no_arbitrary_paths_or_python(self):
        b=self.body();b["dataset_id"]="../private"
        self.assertEqual(self.client.post("/api/runs",json=b,headers=HEADERS).status_code,400)
        self.assertEqual(self.client.post("/api/strategies",json=DEMO_DEFINITION|{"python":"__import__('os')"},headers=HEADERS).status_code,400)
        self.assertEqual(self.client.get("/assets/../../app.py").status_code,404)
        for route in ("/api/cron","/reset_wallet","/run_upgraded_backtest"):
            self.assertEqual(self.client.get(route,headers=HEADERS).status_code,404)

    def test_security_headers_and_local_assets(self):
        for path in ("/","/assets/app.js","/assets/style.css"):
            with self.client.get(path) as r:
                self.assertEqual(r.status_code,200)
                self.assertIn("default-src 'none'",r.headers["Content-Security-Policy"])
                self.assertEqual(r.headers["X-Content-Type-Options"],"nosniff")

    def test_real_worker_full_run_export_and_detail(self):
        r=self.client.post("/api/runs",json=self.body(),headers=HEADERS)
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json["worker_limits"],"LINUX_RLIMITS_APPLIED")
        job=r.json["id"]
        detail=self.client.get("/api/runs/"+job,headers=HEADERS).json
        self.assertTrue(detail["metadata"]["synthetic"])
        trades=self.client.get(f"/api/runs/{job}/trades?size=2&page=1&sort=net_pnl&direction=desc",headers=HEADERS).json
        self.assertGreater(trades["total"],2);self.assertEqual(len(trades["trades"]),2)
        trade=trades["trades"][0]
        self.assertEqual(self.client.get(f"/api/runs/{job}/trade/{trade['trade_id']}",headers=HEADERS).json,trade)
        self.assertEqual(self.client.get(f"/api/runs/{job}/trades?size=500",headers=HEADERS).status_code,400)
        raw=self.client.get(f"/api/runs/{job}/export/trades",headers=HEADERS)
        rows=list(csv.DictReader(io.StringIO(raw.text)))
        self.assertEqual(len(rows),trades["total"])
        self.assertIn("attachment",raw.headers["Content-Disposition"])
        self.assertEqual(self.client.get(f"/api/runs/{job}/trades?q=NOSUCHCOIN",headers=HEADERS).json["total"],0)
        files=export_run(self.app.extensions["research_store"],job,self.root/"export")
        self.assertIn("trades.csv",files)

    def test_worker_failure_is_persisted_not_success(self):
        with patch("backtester.web.run_worker",side_effect=ResourceLimit("synthetic wall limit")):
            self.assertEqual(self.client.post("/api/runs",json=self.body(),headers=HEADERS).status_code,429)
        self.assertEqual(self.app.extensions["research_store"].list_jobs()[0]["status"],"FAILED")

    def test_concurrent_run_blocked_by_database(self):
        store=self.app.extensions["research_store"];store.begin_job()
        self.assertEqual(self.client.post("/api/runs",json=self.body(),headers=HEADERS).status_code,429)

    def test_startup_fail_closed(self):
        with self.assertRaises(ValidationError):create_app(state_dir=self.root,token="short")
        with patch.dict("os.environ",{"HKS_BACKTEST_ENV":"production"}),self.assertRaises(ValidationError):
            create_app(state_dir=self.root,token=TOKEN)

    def test_actual_worker_timeout_killed(self):
        ds=dataset_path(self.root/"datasets","synthetic-demo")
        with self.assertRaisesRegex(ResourceLimit,"wall limit"):
            run_worker(ds,DEMO_DEFINITION,self.body()["config"],["BTCUSDT"],self.root,timeout=0)

    def test_run_rate_limit(self):
        b=self.body()
        with patch("backtester.web.run_worker",side_effect=ValidationError("synthetic failure")):
            results=[self.client.post("/api/runs",json=b,headers=HEADERS).status_code for _ in range(6)]
        self.assertEqual(results,[400]*5+[429])


if __name__=="__main__":unittest.main()
