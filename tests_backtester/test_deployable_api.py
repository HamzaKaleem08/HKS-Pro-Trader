import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from backtester.cache import group_key
from backtester.cli import init_demo
from backtester.web import create_app
from backtester.errors import ValidationError
from test_storage_web import TOKEN,HEADERS


class DeployableAPI(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.version=init_demo(self.root)
        self.app=create_app(state_dir=self.root,token=TOKEN,async_jobs=True);self.client=self.app.test_client()
    def tearDown(self):self.tmp.cleanup()
    def meta(self,sym="BTCUSDT"):
        return {"exchange":"SYNTHETIC","market":"SPOT","symbol":sym,"interval":"1m","synthetic":True,"source":"Synthetic UI/API fixture only","retrieved_at":None}
    def import_symbol(self,sym="BTCUSDT"):
        data=(self.root/"datasets"/"synthetic-demo"/(sym+".csv")).read_bytes()
        return self.client.post("/api/data/import",headers=HEADERS,data={"metadata":json.dumps(self.meta(sym)),"file":(io.BytesIO(data),sym+".csv")})

    def test_import_and_inventory_authenticated(self):
        self.assertEqual(self.client.get("/api/data").status_code,401)
        self.assertEqual(self.import_symbol().status_code,201)
        inventory=self.client.get("/api/data",headers=HEADERS).json
        self.assertEqual(inventory["series"][0]["records"],960)
        self.assertEqual(self.import_symbol().json["inserted"],0)
        self.assertEqual(self.client.get("/api/data?q=NOSUCH",headers=HEADERS).json["series"],[])

    def test_malformed_import_and_plan(self):
        self.assertEqual(self.client.post("/api/data/import",json={},headers=HEADERS).status_code,415)
        r=self.client.post("/api/data/import",headers=HEADERS,data={"metadata":"{}","file":(io.BytesIO(b"bad"),"a.csv")})
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.client.post("/api/data/plan",json={},headers=HEADERS).status_code,400)

    def test_async_both_modes_same_cached_data(self):
        self.import_symbol();self.import_symbol("ETHUSDT")
        hashes=[]
        for mode in ("shared","individual","shared"):
            body={"dataset_id":group_key(self.meta()),"strategy_version":self.version,"symbols":["BTCUSDT","ETHUSDT"],"config":{"start_ms":"2025-11-01T00:30:00Z","end_ms":"2025-11-01T04:00:00Z","mode":mode}}
            with patch("backtester.acquire.public_open",side_effect=AssertionError("no market requests allowed")):
                response=self.client.post("/api/runs",json=body,headers=HEADERS)
                self.assertEqual(response.status_code,202,response.text)
                job=response.json["id"]
                for _ in range(100):
                    record=self.client.get("/api/runs/"+job,headers=HEADERS).json
                    if record["status"]!="RUNNING":break
                    time.sleep(.03)
                self.assertEqual(record["status"],"COMPLETE",record)
                self.assertGreater(record["summary"]["closed_trades"],0)
                self.assertEqual(record["summary"]["starting_capital"],"1000" if mode=="shared" else "2000")
                if mode=="shared":hashes.append(record["metadata"]["result_hash"])
        self.assertEqual(hashes[0],hashes[1])
        self.assertEqual(len(self.app.extensions["historical_cache"].inventory()["imports"]),2)

    def test_imported_dataset_survives_application_recreation(self):
        self.import_symbol()
        second=create_app(state_dir=self.root,token=TOKEN)
        data=second.test_client().get("/api/data",headers=HEADERS).json
        self.assertEqual(data["series"][0]["records"],960)

    def test_old_running_job_is_interrupted_not_reported_successful(self):
        store=self.app.extensions["research_store"];progress=self.app.extensions["job_progress"]
        job=store.begin_job();progress.set(job,25,"Simulating")
        with store.connect() as c:c.execute("UPDATE job_progress SET updated_at='2000-01-01T00:00:00.000+00:00' WHERE job_id=?",(job,))
        r=self.client.get("/api/runs/"+job,headers=HEADERS)
        self.assertEqual(r.json["status"],"INTERRUPTED")
        self.assertNotIn("summary",r.json)
        with self.assertRaises(ValidationError):store.finish_job(job,{"false_success":True})

    def test_job_admission_and_recovery_progress_are_atomic(self):
        store=self.app.extensions["research_store"]
        job=store.begin_job(with_progress=True)
        self.assertEqual(self.app.extensions["job_progress"].get(job)["stage"],"ADMITTED")

    def test_different_saved_strategy_reuses_identical_cache_snapshot(self):
        self.import_symbol()
        from backtester.strategies import DEMO_DEFINITION
        version=self.client.post("/api/strategies",json=DEMO_DEFINITION|{"fast":6},headers=HEADERS).json["version_id"]
        hashes=[]
        for v in (self.version,version):
            body={"dataset_id":group_key(self.meta()),"strategy_version":v,"symbols":["BTCUSDT"],"config":{"start_ms":"2025-11-01T00:30:00Z","end_ms":"2025-11-01T04:00:00Z","mode":"individual"}}
            r=self.client.post("/api/runs",json=body,headers=HEADERS);self.assertEqual(r.status_code,202)
            for _ in range(100):
                record=self.client.get("/api/runs/"+r.json["id"],headers=HEADERS).json
                if record["status"]!="RUNNING":break
                time.sleep(.03)
            self.assertEqual(record["status"],"COMPLETE");hashes.append(record["metadata"]["dataset_hash"])
        self.assertEqual(hashes[0],hashes[1])
        self.assertEqual(len(self.app.extensions["historical_cache"].inventory()["imports"]),1)

    def test_hosted_requires_public_origin_durable_db_and_secret(self):
        with patch.dict("os.environ",{},clear=True),self.assertRaises(ValidationError):create_app(state_dir=self.root,token=TOKEN,hosted=True)
        with patch.dict("os.environ",{"HKS_PUBLIC_URL":"https://example.replit.app"},clear=True),self.assertRaisesRegex(ValidationError,"PostgreSQL"):
            create_app(state_dir=self.root,token=TOKEN,hosted=True)


if __name__=="__main__":unittest.main()
