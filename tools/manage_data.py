"""Owner-local data-cache commands. Never prints secret DATABASE_URL values."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backtester.cache import HistoricalCache
from backtester.common import canonical
from backtester.errors import ValidationError
from backtester.settings import storage


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--state",default=".backtester-state")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("inventory")
    a=sub.add_parser("import");a.add_argument("file");a.add_argument("--metadata",required=True);a.add_argument("--checksum")
    a=sub.add_parser("plan");a.add_argument("--metadata",required=True);a.add_argument("--start",required=True);a.add_argument("--end",required=True)
    a=sub.add_parser("recover");a.add_argument("--confirm-workers-stopped",action="store_true",required=True)
    args=p.parse_args();store=storage(args.state);cache=HistoricalCache(store)
    if args.command=="inventory":result=cache.inventory()
    elif args.command=="recover":cache.recover_interrupted();result={"interrupted_jobs":store.recover_interrupted(),"imports_recovered":True}
    elif args.command=="plan":result={"missing":cache.missing(json.loads(Path(args.metadata).read_text()),args.start,args.end)}
    else:
        metadata=json.loads(Path(args.metadata).read_text());checksum=Path(args.checksum).read_text() if args.checksum else None
        with Path(args.file).open("rb") as f:result=cache.ingest(f,Path(args.file).name,metadata,checksum)
    print(canonical(result))


if __name__=="__main__":
    try:main()
    except (ValidationError,ValueError,OSError):
        print("Data operation failed. Check file validation, secure database configuration and bounded limits; no secret configuration is printed.",file=sys.stderr);raise SystemExit(2)
