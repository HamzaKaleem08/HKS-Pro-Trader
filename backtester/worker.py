"""One bounded replay subprocess; accepts structured definitions, never code."""
import json
from pathlib import Path
import sys


def apply_limits():
    try:
        import resource
    except ImportError:
        return "UNAVAILABLE_ON_THIS_PLATFORM"
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(35,35))
    resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    return "LINUX_RLIMITS_APPLIED"


def main():
    limits = apply_limits()
    from .common import canonical
    from .config import RunConfig
    from .data import load_dataset
    from .errors import ValidationError
    from .simulation import simulate
    from .storage import MAX_RESULT_BYTES
    from .strategies import build_strategy
    request = Path(sys.argv[1])
    output = Path(sys.argv[2])
    if request.stat().st_size > 16*1024:
        raise RuntimeError("bounded worker request exceeded")
    try:
        raw = json.loads(request.read_text())
        result = simulate(load_dataset(raw["dataset_path"]),build_strategy(raw["definition"]),
                          RunConfig.from_dict(raw["config"]),raw["symbols"])
        if len(canonical(result).encode()) > MAX_RESULT_BYTES - 4096:
            raise ValidationError("16 MiB result bound exceeded; no partial report accepted")
        value = {"ok":True,"result":result,"worker_limits":limits}
    except ValidationError as exc:
        value = {"ok":False,"error":str(exc)}
    except (MemoryError,OverflowError):
        value = {"ok":False,"error":"worker memory/number bound exceeded"}
    except Exception:
        value = {"ok":False,"error":"internal worker failure; no result accepted"}
    with output.open("x") as f:
        f.write(canonical(value))


if __name__ == "__main__":
    main()
