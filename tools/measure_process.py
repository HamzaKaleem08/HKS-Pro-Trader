"""Stdlib-only Linux process/resource measurement, preserving the child exit code."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--receipt",required=True);p.add_argument("--log",required=True);p.add_argument("command",nargs=argparse.REMAINDER)
    args=p.parse_args();command=args.command[1:] if args.command[:1]==["--"] else args.command
    started=time.monotonic()
    with Path(args.log).open("x") as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt={"exit_code":result.returncode,"wall_seconds":time.monotonic()-started,"child_user_cpu_seconds":usage.ru_utime,
             "child_system_cpu_seconds":usage.ru_stime,"child_tree_max_rss_bytes_linux":usage.ru_maxrss*1024,
             "memory_scope":"Linux wait/resource child-tree maximum RSS; not the sum of simultaneous parent/child resident sets",
             "command":command}
    with Path(args.receipt).open("x") as f:json.dump(receipt,f,indent=2)
    print(json.dumps(receipt,indent=2));return result.returncode


if __name__=="__main__":raise SystemExit(main())
