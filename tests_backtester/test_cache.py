from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from backtester.cache import HistoricalCache,key,group_key
from backtester.acquire import fetch_missing
from backtester.storage import Store
from backtester.errors import ValidationError,ResourceLimit
from helpers import T,M


META={"exchange":"BINANCE","market":"USDT_LINEAR_PERPETUAL","symbol":"BTCUSDT","interval":"1m","synthetic":False,"source":"OFFLINE SYNTHETIC PARSER FIXTURE — not authentic market history","retrieved_at":None}


def raw_csv(start=T,count=10,gap=None,price="100"):
    text=io.StringIO(newline="");w=csv.writer(text);w.writerow(["open_time","open","high","low","close","volume"])
    for i in range(count):
        if gap==i:continue
        w.writerow([start+i*M,price,price,price,price,"10"])
    return text.getvalue().encode()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root);self.cache=HistoricalCache(self.store)
    def tearDown(self):self.tmp.cleanup()
    def ingest(self,raw=None,meta=META):return self.cache.ingest(io.BytesIO(raw if raw is not None else raw_csv()),"fixture.csv",meta)

    def test_import_reuse_is_idempotent(self):
        a=self.ingest();b=self.ingest()
        self.assertEqual(a["inserted"],10);self.assertEqual(b["inserted"],0);self.assertEqual(b["reused"],10)
        self.assertEqual(self.cache.inventory()["series"][0]["records"],10)

    def test_cache_restart_new_scratch_survives(self):
        self.ingest();new=HistoricalCache(Store(self.root))
        self.assertEqual(new.inventory()["series"][0]["records"],10)
        self.assertFalse(new.missing(META,T,T+10*M))

    def test_missing_ranges_exact(self):
        self.ingest(raw_csv(count=3));self.ingest(raw_csv(start=T+5*M,count=3))
        self.assertEqual(self.cache.missing(META,T,T+10*M),[{"start_ms":T+3*M,"end_ms":T+5*M,"candles":2},{"start_ms":T+8*M,"end_ms":T+10*M,"candles":2}])
        self.assertEqual(self.cache.inventory()["series"][0]["missing_intervals"],2)

    def test_fill_only_missing_range(self):
        self.ingest(raw_csv(count=3));self.ingest(raw_csv(start=T+5*M,count=3));self.ingest(raw_csv(start=T+3*M,count=2))
        self.assertFalse(self.cache.missing(META,T,T+8*M));self.assertEqual(self.cache.inventory()["series"][0]["records"],8)

    def test_gap_inside_input_rejected_atomically(self):
        with self.assertRaisesRegex(ValidationError,"gap"):self.ingest(raw_csv(gap=4))
        self.assertFalse(self.cache.inventory()["series"])
        self.assertEqual(self.cache.inventory()["imports"][0]["status"],"FAILED")

    def test_duplicate_internal_input_rejected(self):
        raw=raw_csv();lines=raw.splitlines();lines.insert(4,lines[3])
        with self.assertRaisesRegex(ValidationError,"duplicate"):self.ingest(b"\n".join(lines))

    def test_conflict_never_overwrites(self):
        self.ingest()
        with self.assertRaisesRegex(ValidationError,"conflict"):self.ingest(raw_csv(price="101"))
        self.assertEqual(self.cache.inventory()["series"][0]["records"],10)

    def test_numeric_formatting_is_not_a_candle_conflict(self):
        self.ingest()
        result=self.ingest(raw_csv(price="100.00000000"))
        self.assertEqual(result["inserted"],0);self.assertEqual(result["reused"],10)

    def test_checksum_pair_verified(self):
        raw=raw_csv();sha=hashlib.sha256(raw).hexdigest()
        r=self.cache.ingest(io.BytesIO(raw),"fixture.csv",META,sha+"  fixture.csv")
        self.assertTrue(r["checksum_verified"])
        self.assertTrue(self.cache.inventory()["imports"][0]["source"]["checksum_verified"])

    def test_checksum_failure(self):
        with self.assertRaisesRegex(ValidationError,"SHA-256"):self.cache.ingest(io.BytesIO(raw_csv()),"fixture.csv",META,"0"*64)
        self.assertFalse(self.cache.inventory()["series"])

    def test_zip_safe_single_member(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,"w") as z:z.writestr("BTCUSDT-1m-2025-11.csv",raw_csv())
        self.assertEqual(self.cache.ingest(io.BytesIO(raw.getvalue()),"history.zip",META)["records"],10)

    def test_zip_traversal_and_wrong_symbol(self):
        for name in ("../evil.csv","..\\evil.csv","ETHUSDT-1m-2025-11.csv"):
            raw=io.BytesIO()
            with zipfile.ZipFile(raw,"w") as z:z.writestr(name,raw_csv())
            with self.assertRaises(ValidationError):self.cache.ingest(io.BytesIO(raw.getvalue()),"history.zip",META)

    def test_zip_expansion_bound(self):
        from unittest.mock import patch
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,"w") as z:z.writestr("fixture.csv",raw_csv())
        with patch("backtester.cache.MAX_EXPANDED_BYTES",10),self.assertRaises(ResourceLimit):self.cache.ingest(io.BytesIO(raw.getvalue()),"fixture.zip",META)

    def test_overlapping_operation_lock(self):
        with self.cache.operation(META,"DOWNLOAD"):
            with self.assertRaises(ResourceLimit):self.ingest()
        self.assertEqual(self.ingest()["inserted"],10)

    def test_market_symbol_interval_isolation(self):
        self.ingest();self.ingest(meta=META|{"market":"SPOT"});self.ingest(meta=META|{"symbol":"ETHUSDT"})
        self.assertEqual(len(self.cache.inventory()["series"]),3)
        self.assertEqual(len(self.cache.groups()),2)

    def test_bundle_snapshot_repeatability_and_gap_rejection(self):
        from backtester.data import load_dataset
        self.ingest();a=self.cache.export_bundle(group_key(META),["BTCUSDT"],T+M,T+10*M,1,self.root/"a")
        b=self.cache.export_bundle(group_key(META),["BTCUSDT"],T+M,T+10*M,1,self.root/"b")
        self.assertEqual(load_dataset(a).content_hash,load_dataset(b).content_hash)
        with self.assertRaisesRegex(ValidationError,"missing"):self.cache.export_bundle(group_key(META),["BTCUSDT"],T+M,T+11*M,1,self.root/"c")

    def test_bad_header_ohlc_and_future(self):
        for raw in (raw_csv().replace(b"high,low",b"low,high"),raw_csv().replace(b"100,100,100,100",b"100,99,100,100"),raw_csv(start=T+10**12)):
            with self.assertRaises(ValidationError):self.ingest(raw)

    def test_no_network_when_already_cached(self):
        self.ingest()
        def forbidden(*a,**k):raise AssertionError("unexpected network")
        result=fetch_missing(self.cache,META,T,T+10*M,opener=forbidden,sleep=lambda _:None)
        self.assertEqual(result["requests"],0);self.assertEqual(result["status"],"COMPLETE")

    def test_mock_download_fetches_only_missing(self):
        from urllib.parse import urlsplit,parse_qs
        self.ingest(raw_csv(count=3));self.ingest(raw_csv(start=T+5*M,count=3));calls=[]
        def opener(request,timeout):
            q=parse_qs(urlsplit(request.full_url).query);calls.append(q)
            rows=[[T+i*M,"100","100","100","100","10",T+(i+1)*M-1,"1000",1,"5","500","0"] for i in (3,4)]
            return io.BytesIO(json.dumps(rows).encode())
        result=fetch_missing(self.cache,META,T,T+8*M,opener=opener,sleep=lambda _:None)
        self.assertEqual(result["requests"],1);self.assertEqual(int(calls[0]["startTime"][0]),T+3*M)
        self.assertFalse(result["remaining"])

    def test_denial_not_retried(self):
        from urllib.error import HTTPError
        calls=[]
        def blocked(*a,**k):calls.append(1);raise HTTPError("public",403,"Denied",{},None)
        with self.assertRaisesRegex(ValidationError,"403"):fetch_missing(self.cache,META,T,T+M,opener=blocked,sleep=lambda _:None)
        self.assertEqual(len(calls),1)


if __name__=="__main__":unittest.main()
