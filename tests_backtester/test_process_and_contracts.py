import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backtester.common import digest
from backtester.config import RunConfig
from backtester.errors import ValidationError
from backtester.reports import build_reports
from backtester.simulation import simulate
from backtester.storage import Store
from helpers import M,T,Scripted,dataset


class ProcessAndContractTests(unittest.TestCase):
    def test_actual_independent_process_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            Store(tmp)
            code="""from backtester.storage import Store
from backtester.errors import ResourceLimit
import sys
try:
 print(Store(sys.argv[1]).begin_job())
except ResourceLimit:
 print('BLOCKED')
"""
            processes=[subprocess.Popen([sys.executable,"-c",code,tmp],cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
            results=[]
            for p in processes:
                out,err=p.communicate(timeout=10)
                self.assertEqual(p.returncode,0,err);results.append(out.strip())
            self.assertEqual(results.count("BLOCKED"),1)
            self.assertEqual(sum(x.startswith("run_") for x in results),1)

    def test_result_hash_and_wallet_equity_equation(self):
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,end_policy="CLOSE_AT_LAST_CLOSE")
        r=simulate(dataset(),Scripted(),c)
        self.assertEqual(digest({k:v for k,v in r.items() if k!="result_hash"}),r["result_hash"])
        summary=build_reports(r)["summary"]
        from decimal import Decimal as D
        self.assertAlmostEqual(float(D(summary["net_equity_change"])),float(D(summary["realized_net_pnl"])+D(summary["unrealized_pnl"])-D(summary["open_entry_fees"])),places=18)

    def test_utc_month_boundary_selection(self):
        from backtester.common import timestamp
        a=timestamp("2024-02-01T00:00:00Z");b=timestamp("2024-03-01T00:00:00Z")
        self.assertEqual((b-a)//86400000,29)
        c=RunConfig(start_ms=a,end_ms=b)
        self.assertEqual(c.end_ms-c.start_ms,29*86400000)


if __name__=="__main__":unittest.main()
