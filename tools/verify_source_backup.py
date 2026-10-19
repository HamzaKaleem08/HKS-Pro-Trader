"""Portable standard-library source-backup verifier. No network or execution."""
from pathlib import Path,PurePosixPath
import hashlib,json,sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text())
    records=manifest['files'];expected={**records}
    sums={}
    for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
        digest,name=line.split('  ',1);sums[name]=digest
    assert set(sums)==set(records)|{'SOURCE_MANIFEST.json'},'Checksum inventory mismatch'
    for name,digest in sums.items():
        rel=PurePosixPath(name)
        assert not rel.is_absolute() and '..' not in rel.parts and '\\' not in name,'Unsafe source path'
        p=ROOT/str(rel);assert p.is_file() and not p.is_symlink(),name
        raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest,name
        if name in records:assert len(raw)==records[name]['bytes'] and digest==records[name]['sha256'],name
    kernel=json.loads((ROOT/'web/kernel.json').read_text())
    for name,source in kernel.items():
        assert (ROOT/'runtime'/name).read_text()==source,'Readable/embedded kernel mismatch: '+name
    pins=json.loads((ROOT/'evidence/KERNEL_SOURCE_PINS.json').read_text())['source_sha256']
    assert len(pins)==13 and all(hashlib.sha256(kernel[n].encode()).hexdigest()==h for n,h in pins.items())
    assert hashlib.sha256((ROOT/'examples/hks_legacy_smc_reverse.py').read_bytes()).hexdigest()==manifest['verified_strategy_sha256']
    runtime=json.loads((ROOT/'web/runtime-manifest.json').read_text())
    for name,digest in runtime['assets'].items():assert hashlib.sha256((ROOT/'web'/name).read_bytes()).hexdigest()==digest,name
    excluded={x['path'] for x in json.loads((ROOT/'HISTORICAL_DATA_EXCLUSIONS.json').read_text())['excluded_files']}
    assert not excluded.intersection(records),'Historical cache committed as source'
    for name in records:
        p=PurePosixPath(name)
        assert not any(x in p.parts for x in ['.git','.wrangler','.venv','node_modules','__pycache__','browser-profiles'])
        assert p.suffix.lower() not in ['.db','.sqlite','.sqlite3','.key','.pem'],name
    print(json.dumps({'passed':True,'payload_files_verified':len(records),'manifest_sha256':sums['SOURCE_MANIFEST.json'],
       'readable_kernel_modules':len(kernel),'original_financial_source_pins':len(pins),
       'verified_strategy_sha256':manifest['verified_strategy_sha256'],
       'published_deployment':manifest['published_deployment']['id'],'historical_files_excluded':len(excluded)},indent=2))

if __name__=='__main__':main()
