import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .common import canonical
from .errors import ResourceLimit, ValidationError
from .storage import MAX_RESULT_BYTES


def run_worker(dataset_path, definition, config, symbols, scratch_dir, timeout=40):
    """No web credentials are inherited by the child. No shell or uploaded code."""
    with tempfile.TemporaryDirectory(prefix="replay-",dir=scratch_dir) as tmp:
        root = Path(tmp)
        request, response = root/"request.json",root/"response.json"
        request.write_text(canonical({"dataset_path":str(dataset_path),"definition":definition,"config":config,"symbols":symbols}))
        project = Path(__file__).resolve().parents[1]
        env = {k:os.environ[k] for k in ("PATH","LANG","SYSTEMROOT","WINDIR") if k in os.environ}
        env.update({"PYTHONPATH":str(project),"PYTHONDONTWRITEBYTECODE":"1"})
        with (root/"stderr.log").open("wb") as err:
            p = subprocess.Popen([sys.executable,"-m","backtester.worker",str(request),str(response)],
                                 cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                 stderr=err,start_new_session=(os.name=="posix"))
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name=="posix": os.killpg(p.pid,signal.SIGKILL)
                else: p.kill()
                p.wait()
                raise ResourceLimit("worker 40-second wall limit reached; no partial result accepted") from None
        if p.returncode != 0 or not response.exists():
            raise ResourceLimit("worker resource/startup failure; no partial result accepted")
        if response.stat().st_size > MAX_RESULT_BYTES:
            raise ResourceLimit("worker output bound exceeded")
        try:
            value = json.loads(response.read_text())
        except (UnicodeError,ValueError):
            raise ValidationError("invalid worker result") from None
        if not value.get("ok"):
            raise ValidationError(value.get("error","worker failed"))
        return value["result"],value["worker_limits"]
