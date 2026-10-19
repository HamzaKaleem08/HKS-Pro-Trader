"""Generate owner review diff/hashes; no deployment, source mutation or research."""
from datetime import datetime,timezone
import difflib,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path('/workspace/HKS-Pro-Trader-browser-consent-fix-20261018')
FILES=['browser_adapter.py','tools/build_static.py','web/app.js','web/index.html',
       'web/kernel.json','web/strategy-worker.js','web/sw.js',
       'runtime/backtester/browser_context.py','examples/hks_legacy_smc_reverse.py',
       'tests/test_completed_context.py','tests/test_smc_compat.py',
       'tools/_kernel_for_tests.py','tools/smc_reference.py','tools/smc_cached_evidence.py',
       'tools/verify_smc_browser.py','tools/reconcile_smc_results.py','tools/build_smc_review.py',
       'SMC_REVERSE_COMPATIBILITY.md','SMC_COMPATIBILITY_REPORT.md']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    baseline=json.loads((ROOT/'review/smc-compat-v1/BASELINE.json').read_text())
    unchanged=[];missing=[];changed=[]
    for name,expected in baseline['source_files'].items():
        p=ORIGINAL/name
        if not p.is_file():missing.append(name)
        elif sha(p)!=expected:changed.append(name)
        else:unchanged.append(name)
    assert not missing and not changed,{'original_missing':missing,'original_changed':changed}
    sources=json.loads((ROOT/'web/kernel.json').read_text())
    pins=json.loads((ROOT/'evidence/KERNEL_SOURCE_PINS.json').read_text())['source_sha256']
    assert all(hashlib.sha256(sources[name].encode()).hexdigest()==expected for name,expected in pins.items())
    records={};patch=[]
    for name in FILES:
        path=ROOT/name;old=ORIGINAL/name
        assert path.is_file(),name
        records[name]={'sha256':sha(path),'bytes':path.stat().st_size,
                       'previous_sha256':sha(old) if old.is_file() else None}
        before=old.read_text().splitlines(keepends=True) if old.is_file() else []
        after=path.read_text().splitlines(keepends=True)
        for line in difflib.unified_diff(before,after,fromfile='a/'+name if old.is_file() else '/dev/null',tofile='b/'+name):
            patch.append(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n')
    (ROOT/'SMC_REVERSE_COMPATIBILITY.patch').write_text(''.join(patch))
    record={'created_at':datetime.now(timezone.utc).isoformat(), 'deployed':False,
        'original_workspace':str(ORIGINAL),'original_files_reverified_unchanged':len(unchanged),
        'pinned_financial_modules_unchanged':pins,'review_files':records,
        'patch':{'sha256':sha(ROOT/'SMC_REVERSE_COMPATIBILITY.patch'),'bytes':(ROOT/'SMC_REVERSE_COMPATIBILITY.patch').stat().st_size}}
    (ROOT/'SMC_SOURCE_SHA256.json').write_text(json.dumps(record,indent=2))
    print(json.dumps({'original_files_unchanged':len(unchanged),'financial_modules_unchanged':len(pins),
        'review_files':len(records),'patch_sha256':record['patch']['sha256']},indent=2))

if __name__=='__main__':main()
