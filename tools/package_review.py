"""Freeze the tested staging build and verify static/review archives locally."""
from pathlib import Path
import datetime,difflib,hashlib,json,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/workspace/HKS-Pro-Trader-v4-browser-probe-20261017')
sha=lambda b:hashlib.sha256(b).hexdigest()

def main():
 r=json.loads((ROOT/'evidence/cloudflare-runtime-final/BROWSER_RESULTS.json').read_text())
 b=json.loads((ROOT/'evidence/BENCHMARK_RESULTS.json').read_text())
 assert r['status']=='PASS' and r['passed_checks']==28
 assert 'Ran 25 tests' in (ROOT/'evidence/UNIT_TESTS_FINAL.log').read_text()
 measured=b['actual_workload'];runtime=r['build']['build_id']
 result=f'''# Final staging implementation report

Status: WORKING BOUNDED STATIC CANDIDATE; NOT PUBLISHED.
Build: {runtime}. Cloudflare authorization is missing. No live URL exists.

## Implemented and actually tested

The actual approved premium V4 HTML/CSS is connected to browser Python workers,
not a mockup or JSON-only editor. The preserved V4 Decimal financial modules and
strategy API remain pinned byte-for-byte. Strategy validation, immutable local
versions, custom Python entry/exit management, ATR, trailing, reductions, both
wallet modes, charts, costs, complete searchable/paginated journals, details and
CSV exports are functional. Saving/testing never activates any execution engine.

All20 genuine Binance USD-M November2025 1m source chunks (864,000 candles) are
bundled, checksum-validated and cached once per device. Each request streams the
local gzip input to select an explicit bounded range, then the unchanged Python
loader independently validates it. This is bounded input staging plus chunked
computation; NOT a completed multi-year streaming input/output financial kernel.

The trusted financial loop is mechanically scheduled as a generator. Its financial
body is unchanged. At completed global timestamp boundaries it serializes typed
JSON state: open/partial positions, pending orders/stop updates, wallet balances,
risk, marks, history, signals, counts and journals. Opaque strategy recovery bytes
preserve supported deterministic Python state in the isolated realm only. New
interpreter restores were verified at all4 boundaries of the partial fixture.
Checkpoint hashes/source/config/data bindings and Web Locks prevent unsafe or
concurrent resumes. Cancel/reload/resume on genuine candles produced exactly the
same complete result as the original V4 reference, with fewer callbacks after
resume. Unsupported nondeterministic/native/class/closure state is not certified.

Original V4:128 source hashes unchanged; browser proof:73 unchanged; both preserved
ZIP hashes and CRCs independently reverified. No original files were overwritten.

## Actual verification

25 unit/integrity tests passed;0failed;0skipped.
28 actual Chromium browser integration checks passed;0failed. They ran against
Cloudflare Pages' local workerd runtime, including its extensionless .html routing
and CSP. They are not a public deployment test. All12 successful frozen native V4
raw result objects/hashes matched exactly;2 invalid fixtures were rejected.
A hand-calculated1unit partial exit reproduces $1,017.50 ending equity.
Desktop Chromium and Android viewport/touch emulation ran. Physical Android did
not run. No browser sandbox bypass was used.

Warm-cache genuine20-symbol6-hour replay: {measured['input_candles_including_warmup']:,} input candles,
{measured['calls']:,} strategy callbacks, {measured['exit_segments']} exit segments.
Calculation: {measured['calculation_seconds']:.3f}s; workers including initialization/checkpoints:
{measured['worker_wall_seconds']:.3f}s; including local-cache composition: {measured['including_local_cache_composition_seconds']:.3f}s.
Zero candle downloads on the warm run. Cash/equity reconciliation residuals zero.
The full QA session peaked at {b['full_test_session_chromium_peak_pss_mib']:.1f}MiB Chromium PSS
across multiple processes. Sample Wasm heaps totaled {b['wasm_heaps_for_sample_mib']:.2f}MiB;
this excludes the rest of the browser and is not a memory cap.

## Mandatory limits still unresolved

The20coins×4years /30–60minute target is NOT achieved or benchmarked. It is disabled.
No four-year dataset was acquired.42,076,800 one-minute events would be required
before listing-eligibility adjustments. A naive linear calculation-only projection
from the measured sample is approximately{b['naive_calculation_only_hours_if_linear']:.1f}hours, NOT a supported run.
Current200,000-input-candle /10,000-entry /32MiB-CSV limits remain. No periods or
journals are truncated to make a request succeed. Both funds/accounting modes use
the same preserved kernel. Funding/liquidation/historical filters remain uncertified.

Browser RAM cannot be hard-limited; trusted Python only. State is per device/profile,
not authenticated cloud accounts, not synchronized between phone/laptop and not an
external backup. Browser eviction/background termination remains possible. See README.

## Deployment blocker and exact next owner action

Wrangler4.151.1: "You are not authenticated. Please run `wrangler login`."
Cloudflare API is reachable but no token/account binding is set in this process.
Secure configuration requirements have been saved. Owner must supply the selected
account's Pages Edit API token and account ID in environment settings, not chat.
Then reuse web/ for the already-authorized free Pages staging deployment and verify
HTTPS Python/results/persistence on the actual URL. No further feature work or
production Replit change is required to publish the bounded candidate.

Public payload: {r['build']['files']}files /{r['build']['bytes']:,}bytes, static-only.
No Functions, R2, server, paid service, billing activation, GitHub push, live/demo
orders, private HKS/ABG source, holdout data or production modification occurred.
'''
 (ROOT/'IMPLEMENTATION_REPORT.md').write_text(result)
 tests='''# Actual final test evidence

- `python -m unittest discover -s tests -v`:25passed,0failed,0skipped.
  `evidence/UNIT_TESTS_FINAL.log`. Includes13 preserved feasibility tests and12
  new checkpoint tests. Original326-test server baseline was NOT rerun or added
  to these counts; it remains historical evidence in the preserved V4 candidate.
- `python tools/verify_staging.py --origin http://127.0.0.1:8098 --output evidence/cloudflare-runtime-final`:
  28PASS integration checks,0failed; ordinary Chromium OS sandbox enabled.
  Playwright + actual local Pages/workerd; no real Android device or public site.
- All12 successful original native fixture results match whole-object and hash;
  both invalid fixtures rejected. No simulated market-data downloads occurred.
- `node --check` ran for app/client/strategy worker; Python module compile checks ran.
- Source/package secret-pattern scan and original/source/archive hash checks are
  in `evidence/PUBLICATION_SAFETY_SCAN.json` and `evidence/FINAL_PRESERVATION.json`.

Earlier attempts are retained, not overwritten: browser-run-1 completed20checks
then its Playwright string wait violated app CSP. The QA predicate was corrected
without changing CSP. browser-run-2 completed27checks on the static mirror. Final
run completed28checks on the actual Cloudflare local runtime. These are not added
together. No mandatory current test is failing. Public deployment and physical
Android remain UNVERIFIED, not passed.

Final browser checks:

'''
 tests+='\n'.join('- '+s for s in r['checks'])+'\n'
 (ROOT/'TEST_RESULTS.md').write_text(tests)
 # Scope the patch to the separate browser proof, never the server application.
 sources=[p for p in ROOT.rglob('*') if p.is_file() and not any(part in {'.wrangler','__pycache__','delivery','node_modules','.git'} for part in p.relative_to(ROOT).parts)]
 tracked=[p for p in sources if p.relative_to(ROOT).parts[0]!='evidence' and p.name not in {'SOURCE_SHA256.json','REVIEW_MANIFEST.json','BROWSER_STAGING_REVIEW.patch'}]
 patch=[];changed=[]
 for p in sorted(tracked):
  rel=str(p.relative_to(ROOT));old=BASE/rel
  if old.exists() and old.read_bytes()==p.read_bytes():continue
  changed.append(rel)
  try:new=p.read_text();before=old.read_text() if old.is_file() else ''
  except UnicodeError:continue
  patch.extend(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old.exists() else '/dev/null',tofile='b/'+rel))
 (ROOT/'BROWSER_STAGING_REVIEW.patch').write_text(''.join(patch))
 (ROOT/'CHANGED_FILES.json').write_text(json.dumps({'base':'Preserved standalone browser proof (not the V4 server tree)','changed_or_added':changed},indent=2))
 delivery=ROOT/'delivery';delivery.mkdir(exist_ok=True)
 for name in ['HKS_V4_PAGES_STATIC_STAGING.zip','HKS_V4_PAGES_SOURCE_REVIEW.zip','DELIVERY_RECEIPT.json']:
  if (delivery/name).exists():raise FileExistsError('Refusing to overwrite frozen delivery '+name)
 # Freeze source and complete evidence, excluding receipts that refer to archives.
 files={}
 for p in ROOT.rglob('*'):
  if not p.is_file() or any(part in {'.wrangler','__pycache__','delivery','node_modules','.git'} for part in p.relative_to(ROOT).parts):continue
  if p.name in {'SOURCE_SHA256.json','REVIEW_MANIFEST.json'}:continue
  files[str(p.relative_to(ROOT))]=sha(p.read_bytes())
 (ROOT/'SOURCE_SHA256.json').write_text(json.dumps({'schema_version':1,'build_id':runtime,'files':files},indent=2,sort_keys=True))
 paths=[ROOT/n for n in files]+[ROOT/'SOURCE_SHA256.json']
 receipts=[]
 for name,members,base in [('HKS_V4_PAGES_STATIC_STAGING.zip',[p for p in (ROOT/'web').rglob('*') if p.is_file()],ROOT/'web'),('HKS_V4_PAGES_SOURCE_REVIEW.zip',paths,ROOT)]:
  target=delivery/name
  with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
   for p in sorted(members):z.write(p,str(p.relative_to(base)))
  with zipfile.ZipFile(target) as z,tempfile.TemporaryDirectory(prefix='hks-pages-verify-',dir='/tmp') as temp:
   if z.testzip():raise AssertionError('ZIP CRC error')
   for info in z.infolist():
    if Path(info.filename).is_absolute() or '..' in Path(info.filename).parts:raise AssertionError('Unsafe ZIP path')
   z.extractall(temp)
   for p in members:
    if sha((Path(temp)/p.relative_to(base)).read_bytes())!=sha(p.read_bytes()):raise AssertionError('Independent extraction mismatch')
  receipts.append({'file':str(target),'bytes':target.stat().st_size,'sha256':sha(target.read_bytes()),'members':len(members),'crc_verified':True,'independent_extraction_all_members_verified':True})
 (delivery/'DELIVERY_RECEIPT.json').write_text(json.dumps({'build_id':runtime,'files':receipts,'publication':'LOCAL ONLY; no ChatGPT artifact publication or downloadable URL claimed','cloudflare_site':'NOT DEPLOYED; owner authorization missing','frozen_source_count':len(files)},indent=2))
 print(json.dumps({'verified_source_files':len(files),'changed_text_files':len(changed),'archives':receipts},indent=2))
if __name__=='__main__':main()
