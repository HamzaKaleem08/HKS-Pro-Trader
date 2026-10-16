"""Portable unittest runner with actual machine-readable results and exit status."""
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tests_backtester"))


def main():
    out=ROOT/"evidence"/"v2-tests"
    out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    tests=unittest.defaultTestLoader.discover(str(ROOT/"tests_backtester"))
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(tests)
    (out/"UNITTEST.log").write_text(log.getvalue())
    receipt={"timestamp_utc":datetime.now(timezone.utc).isoformat(),"python":sys.version,"tests_run":result.testsRun,
             "passed":result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped)-len(result.expectedFailures)-len(result.unexpectedSuccesses),
             "failures":[t.id() for t,_ in result.failures],"errors":[t.id() for t,_ in result.errors],
             "skipped":[{"test":t.id(),"reason":r} for t,r in result.skipped],
             "expected_failures":len(result.expectedFailures),"unexpected_successes":len(result.unexpectedSuccesses),
             "wall_seconds":time.monotonic()-started,"successful":result.wasSuccessful()}
    (out/"TEST_RESULTS.json").write_text(json.dumps(receipt,indent=2))
    print(log.getvalue());print(json.dumps(receipt,indent=2));return 0 if result.wasSuccessful() else 1


if __name__=="__main__":raise SystemExit(main())
