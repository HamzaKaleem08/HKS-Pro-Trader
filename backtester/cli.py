"""Owner-local import/run/export tools. No market acquisition or trading actions."""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from .catalog import import_bundle,dataset_path
from .common import canonical,timestamp
from .config import RunConfig
from .data import coverage,load_dataset
from .errors import ValidationError
from .jobs import run_worker
from .reports import build_reports,csv_report
from .storage import Store
from .strategies import DEMO_DEFINITION


def init_demo(state):
    """Explicitly synthetic, deterministic two-symbol fixtures. Never live data."""
    state=Path(state)
    store=Store(state)
    version=store.save_strategy(DEMO_DEFINITION)
    destination=state/"datasets"/"synthetic-demo"
    if destination.exists():
        load_dataset(destination)
        return version
    with tempfile.TemporaryDirectory(prefix="hks-synthetic-") as tmp:
        root=Path(tmp); files=[]; first=timestamp("2025-11-01T00:00:00Z")
        for sym,phase in (("BTCUSDT",0),("ETHUSDT",12)):
            path=root/(sym+".csv")
            with path.open("w",newline="") as f:
                writer=csv.writer(f);writer.writerow(["open_time","open","high","low","close","volume"])
                last=Decimal(100)
                for i in range(960):
                    j=(i+phase)%40
                    price=Decimal(90)+Decimal(j if j<=20 else 40-j)
                    writer.writerow([first+i*60000,last,max(last,price)+Decimal(".2"),min(last,price)-Decimal(".2"),price,1000])
                    last=price
            files.append({"symbol":sym,"file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        manifest={"schema_version":1,"dataset_id":"synthetic-demo","exchange":"SYNTHETIC", "market":"SPOT",
                  "interval":"1m","synthetic":True,"source":"Deterministic triangle-price engine/UI fixture; NOT market history",
                  "retrieved_at":"2025-12-01T00:00:00Z","files":files}
        (root/"manifest.json").write_text(canonical(manifest))
        import_bundle(root,state/"datasets")
    return version


def export_run(store,run_id,destination):
    r=store.get_job(run_id)["result"]
    if r is None:raise ValidationError("run has no complete result")
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    (destination/"result.json").write_text(canonical(r))
    (destination/"report.json").write_text(canonical(build_reports(r)))
    for kind in ("trades","coins","decisions"):
        (destination/(kind+".csv")).write_text(csv_report(r,kind),newline="")
    files={p.name:{"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(destination.iterdir())}
    (destination/"SHA256_MANIFEST.json").write_text(canonical(files))
    return files


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state",default=".backtester-state",help="separate new research state; never a live wallet directory")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("init-demo")
    p=sub.add_parser("validate");p.add_argument("bundle")
    p=sub.add_parser("import");p.add_argument("bundle")
    p=sub.add_parser("run");p.add_argument("--dataset",required=True);p.add_argument("--version",required=True);p.add_argument("--config",required=True);p.add_argument("--symbols",nargs="+",required=True)
    p=sub.add_parser("export");p.add_argument("run_id");p.add_argument("destination")
    p=sub.add_parser("serve");p.add_argument("--port",type=int,default=8081)
    p=sub.add_parser("recover-interrupted");p.add_argument("--confirm-workers-stopped",action="store_true",required=True)
    args=parser.parse_args(argv)
    try:
        state=Path(args.state).resolve()
        if args.command=="init-demo":
            print(canonical({"synthetic":True,"version":init_demo(state)}))
        elif args.command=="validate":
            ds=load_dataset(args.bundle);print(canonical({"dataset_hash":ds.content_hash,"coverage":coverage(ds),"warnings":ds.warnings}))
        elif args.command=="import":
            ds=import_bundle(args.bundle,state/"datasets");print(canonical({"imported":ds.dataset_id,"dataset_hash":ds.content_hash}))
        elif args.command=="run":
            store=Store(state); definition=store.get_strategy(args.version)
            p=Path(args.config)
            if p.stat().st_size>16000:raise ValidationError("config exceeds 16 KiB")
            config=RunConfig.from_dict(json.loads(p.read_text()))
            job=store.begin_job()
            try:
                r,limits=run_worker(dataset_path(state/"datasets",args.dataset),definition,json.loads(p.read_text()),args.symbols,state)
                store.finish_job(job,r)
            except Exception:
                store.finish_job(job,error="CLI worker failed; no partial result accepted")
                raise
            print(canonical({"id":job,"worker_limits":limits,"result_hash":r["result_hash"],**build_reports(r)}))
        elif args.command=="export":print(canonical(export_run(Store(state),args.run_id,args.destination)))
        elif args.command=="recover-interrupted":
            print(canonical({"recovered":Store(state).recover_interrupted()}))
        elif args.command=="serve":
            if not 1024<=args.port<=65535:raise ValidationError("local port must be 1024–65535")
            from .web import create_app
            create_app(state_dir=state,port=args.port).run(host="127.0.0.1",port=args.port,threaded=True,use_reloader=False,debug=False)
    except (ValidationError,ValueError,OSError) as exc:
        print("Backtester stopped: "+str(exc),file=sys.stderr)
        return 2
    return 0


if __name__=="__main__":raise SystemExit(main())
