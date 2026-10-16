"""Small demonstration using existing owner-supplied official Futures archives.

No downloads. Never calls a prior HKS kernel or changes its archived results.
Uses only BTC/ETH 15m archives, converting exact original OHLCV to the new format.
"""
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from backtester.catalog import import_bundle,dataset_path
from backtester.cli import export_run
from backtester.common import canonical,digest,timestamp
from backtester.data import load_dataset
from backtester.jobs import run_worker
from backtester.reports import build_reports
from backtester.storage import Store
from backtester.strategies import DEMO_DEFINITION


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--state",required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    source_receipts=[]
    with tempfile.TemporaryDirectory(prefix="hks-original-data-conversion-") as tmp:
        root=Path(tmp);files=[]
        for sym in ("BTCUSDT","ETHUSDT"):
            name=f"{sym}-15m-2026-09.zip"
            original=args.source/name;sidecar=args.source/(name+".CHECKSUM")
            raw_hash=hashlib.sha256(original.read_bytes()).hexdigest()
            check=sidecar.read_text().split()
            assert len(check)==2 and check[0].lower()==raw_hash and check[1].lstrip("*")==name,"official sidecar mismatch"
            with zipfile.ZipFile(original) as archive:
                expected=f"{sym}-15m-2026-09.csv"
                assert archive.namelist()==[expected],"unexpected archive contents"
                assert archive.testzip() is None,"CRC mismatch"
                with archive.open(expected) as f,(root/(sym+".csv")).open("w",newline="") as dest:
                    reader=csv.reader(io.TextIOWrapper(f,encoding="utf-8-sig"))
                    writer=csv.writer(dest);writer.writerow(["open_time","open","high","low","close","volume"])
                    rows=0;last=None
                    for line in reader:
                        if rows==0 and line and line[0] in ("open_time","open_time_ms"):continue
                        assert len(line)==12,"native 12-field Binance format required"
                        t=int(line[0]);assert int(line[6])==t+899999,"native close timestamp mismatch"
                        assert t==timestamp("2026-09-01T00:00:00Z")+rows*900000,"gap/duplicate/misalignment"
                        writer.writerow([line[0],*line[1:6]]);rows+=1;last=t
                    assert rows==2880 and last+900000==timestamp("2026-10-01T00:00:00Z")
            p=root/(sym+".csv")
            files.append({"symbol":sym,"file":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
            source_receipts.append({"symbol":sym,"archive":name,"bytes":original.stat().st_size,"sha256":raw_hash,
                                    "sidecar_sha256":hashlib.sha256(sidecar.read_bytes()).hexdigest(),"rows":rows,
                                    "source_url":f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/15m/{name}",
                                    "original_download_timestamp":None,"verified_locally_utc":datetime.now(timezone.utc).isoformat()})
        manifest={"schema_version":1,"dataset_id":"binance-um-btc-eth-september2026-15m","exchange":"BINANCE_USD_M",
                  "market":"USDT_LINEAR_PERPETUAL","interval":"15m","synthetic":False,"retrieved_at":None,
                  "source":"Owner-supplied Binance USD-M Futures monthly klines; original ZIP/.CHECKSUM verified offline. Diagnostic price replay only; original download receipt unavailable.",
                  "files":files,"source_archives":source_receipts}
        (root/"manifest.json").write_text(canonical(manifest))
        ds=import_bundle(root,args.state/"datasets")
    store=Store(args.state);version=store.save_strategy(DEMO_DEFINITION);results={}
    for mode in ("individual","shared"):
        config={"start_ms":"2026-09-02T00:00:00Z","end_ms":"2026-09-05T00:00:00Z","mode":mode,
                "initial_capital":"1000","fee_bps":"10","slippage_bps":"2","risk_fraction":".01",
                "allocation_fraction":".25","end_policy":"KEEP_OPEN"}
        config["allow_uncertified_futures"]=True
        job=store.begin_job();start=time.monotonic()
        result,limits=run_worker(dataset_path(args.state/"datasets",ds.dataset_id),DEMO_DEFINITION,config,["BTCUSDT","ETHUSDT"],args.state)
        store.finish_job(job,result);elapsed=time.monotonic()-start
        # Independent identical rerun proves output stability; no historical rules tuned.
        repeated,_=run_worker(dataset_path(args.state/"datasets",ds.dataset_id),DEMO_DEFINITION,config,["BTCUSDT","ETHUSDT"],args.state)
        assert result==repeated,"non-deterministic replay"
        exported=export_run(store,job,args.output/mode)
        results[mode]={"job_id":job,"wall_seconds_first_worker":elapsed,"worker_limits":limits,
                       "result_hash":result["result_hash"],"repeatability":"EXACT_RESULT_EQUALITY",
                       "reconciliation":result["reconciliation"],**build_reports(result),"exported_files":exported}
    receipt={"status":"DIAGNOSTIC_ONLY","strategy_version":version,"strategy_definition":DEMO_DEFINITION,
             "historical_strategy_parity":"NOT VERIFIED — demonstration strategy only",
             "input_dataset_hash":ds.content_hash,"sources":source_receipts,"coverage":"5760 original 15m candles across two contracts; 30 days of source data",
             "actual_evaluation":"2026-09-02T00:00:00Z through 2026-09-05T00:00:00Z, 3 days, plus causal indicator warm-up",
             "results":results,"limitations":["No funding data modeled; null, never silently zero","Historical exchange filters/leverage not certified",
                                               "15m conservative OHLC fills, no 1m refinement","No authentic Normal/Reverse strategy claim","Already-inspected data, not independent validation"]}
    (args.output/"EXAMPLE_RESULTS.json").write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":main()
