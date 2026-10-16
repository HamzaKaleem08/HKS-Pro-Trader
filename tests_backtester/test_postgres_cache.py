"""Opt-in REAL PostgreSQL cases; only an explicitly disposable loopback aux DB."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

import test_cache as fixtures
from backtester.errors import ResourceLimit,ValidationError
from backtester.postgres import PostgresStore
from backtester.cache import HistoricalCache


def disposable_url():
    value=os.environ.get("HKS_TEST_POSTGRES_URL","")
    parsed=urlsplit(value)
    if os.environ.get("HKS_TEST_POSTGRES_DISPOSABLE")!="YES" or parsed.hostname not in ("localhost","127.0.0.1") or not parsed.path.startswith("/hks_verify_aux"):
        raise unittest.SkipTest("requires explicitly disposable auxiliary loopback PostgreSQL test DB")
    return value


class PostgresCacheTests(fixtures.CacheTests):
    def setUp(self):
        url=disposable_url()
        import psycopg
        with psycopg.connect(url) as c:c.execute("DROP SCHEMA IF EXISTS hks_backtester CASCADE")
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=PostgresStore(url,self.root);self.cache=HistoricalCache(self.store)

    def test_cache_restart_new_scratch_survives(self):
        self.ingest();new=HistoricalCache(PostgresStore(disposable_url(),self.root/"different-runtime"))
        self.assertEqual(new.inventory()["series"][0]["records"],10)
        self.assertFalse(new.missing(fixtures.META,fixtures.T,fixtures.T+10*fixtures.M))


class PostgresCoordination(unittest.TestCase):
    def setUp(self):
        self.url=disposable_url()
        import psycopg
        with psycopg.connect(self.url) as c:c.execute("DROP SCHEMA IF EXISTS hks_backtester CASCADE")
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=PostgresStore(self.url,self.root);self.cache=HistoricalCache(self.store)
    def tearDown(self):self.tmp.cleanup()

    def test_independent_instances_admit_only_one_job(self):
        def attempt(n):
            try:return PostgresStore(self.url,self.root/str(n)).begin_job()
            except ResourceLimit:return None
        with ThreadPoolExecutor(max_workers=4) as ex:result=list(ex.map(attempt,range(4)))
        self.assertEqual(sum(r is not None for r in result),1)

    def test_independent_instances_lock_same_import(self):
        second=HistoricalCache(PostgresStore(self.url,self.root/"second"))
        with self.cache.operation(fixtures.META,"DOWNLOAD"):
            with self.assertRaises(ResourceLimit):second.ingest(__import__('io').BytesIO(fixtures.raw_csv()),"fixture.csv",fixtures.META)

    def test_remote_plaintext_rejected_before_connect(self):
        with self.assertRaisesRegex(ValidationError,"TLS"):
            PostgresStore("postgresql://example.invalid/db?sslmode=disable",self.root)
