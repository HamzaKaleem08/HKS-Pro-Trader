import json
import os
from pathlib import Path
import shutil
import tempfile

from .common import identifier
from .data import confined, coverage, load_dataset
from .errors import ValidationError


def dataset_path(root, dataset_id):
    identifier(dataset_id)
    root = Path(root).resolve()
    p = root / dataset_id
    if p.is_symlink() or not p.is_dir() or p.resolve().parent != root:
        raise ValidationError("unknown dataset")
    return p


def list_datasets(root):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or not p.is_dir() or p.is_symlink():
            continue
        try:
            ds = load_dataset(dataset_path(root,p.name))
            if ds.dataset_id != p.name:
                raise ValidationError("dataset directory/manifest identity mismatch")
            result.append({"id":ds.dataset_id,"market":ds.market,"exchange":ds.exchange,"synthetic":ds.synthetic,
                           "interval":ds.interval,"coverage":coverage(ds),"warnings":ds.warnings,"dataset_hash":ds.content_hash})
        except (ValidationError,OSError):
            result.append({"id":p.name,"invalid":True,"error":"Dataset failed integrity validation; inspect locally before use"})
    return result


def import_bundle(source, catalog_root):
    """Trusted owner CLI only, copying verified files to a new catalog directory."""
    source = Path(source)
    ds = load_dataset(source)
    root = Path(catalog_root).resolve()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination = root / ds.dataset_id
    if destination.exists():
        raise ValidationError("dataset ID already exists; existing inputs are never overwritten")
    staging = Path(tempfile.mkdtemp(prefix=".intake-",dir=root))
    manifest = json.loads((source/"manifest.json").read_text())
    for name in ["manifest.json"]+[x["file"] for x in manifest["files"]]:
        shutil.copyfile(confined(source,name),staging/name)
    copied = load_dataset(staging)
    if copied.content_hash != ds.content_hash:
        raise ValidationError("copied dataset integrity mismatch; staging preserved")
    os.rename(staging,destination)
    return ds
