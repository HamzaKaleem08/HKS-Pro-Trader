"""Actual source-only synthetic UI/Pyodide smoke test; no external market data."""
import argparse,contextlib,csv,hashlib,importlib.util,json,os,re,shutil,tempfile,threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from decimal import Decimal
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--chromium',default=shutil.which('chromium') or shutil.which('google-chrome'))
 ap.add_argument('--data-root',type=Path,help='Separate preserved source root containing the excluded startup fixture; never copied into Git')
 ap.add_argument('--output',type=Path,default=ROOT/'qa-output/source-browser');args=ap.parse_args()
 if not args.chromium:raise SystemExit('Provide --chromium with an installed, normally sandboxed Chrome/Chromium executable')
 out=args.output;out.mkdir(parents=True,exist_ok=False);record={'synthetic_only':True,'market_downloads':False,'page_errors':[]}
 try:
  with tempfile.TemporaryDirectory(prefix='hks-source-browser-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
   # Preserve exact published app bytes. Its fresh-profile bootstrap requires
   # this excluded genuine fixture even when the selected replay is synthetic.
   # Restore it only in disposable test storage, never in the source checkout.
   serve_root=Path(temp)/'app';shutil.copytree(ROOT/'web',serve_root/'web')
   fixture='web/fixtures/genuine_2coin_1day.json.gz'
   original=(args.data_root or ROOT)/fixture
   if not original.is_file():raise RuntimeError('Published UI bootstrap requires excluded '+fixture+'; provide --data-root with separately preserved checksum-matching data')
   excluded=json.loads((ROOT/'HISTORICAL_DATA_EXCLUSIONS.json').read_text())['excluded_files']
   wanted=next(x for x in excluded if x['path']==fixture);raw=original.read_bytes()
   assert len(raw)==wanted['bytes'] and hashlib.sha256(raw).hexdigest()==wanted['sha256'],'Startup fixture checksum mismatch'
   (serve_root/fixture).write_bytes(raw);record['excluded_startup_fixture_restored_only_in_temporary_storage']=True
   spec=importlib.util.spec_from_file_location('source_headers',ROOT/'serve.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
   m.ROOT=serve_root
   server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
   cleanup.callback(server.server_close);cleanup.callback(server.shutdown)
   origin=f'http://127.0.0.1:{server.server_port}'
   env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
   env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
   browser=p.chromium.launch(executable_path=args.chromium,headless=True,chromium_sandbox=True,env=env,timeout=45000);cleanup.callback(browser.close)
   record['browser_version']=browser.version
   context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True);cleanup.callback(context.close)
   page=context.new_page();page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
   page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
   assert page.evaluate('crossOriginIsolated')
   page.select_option('#dataset','synthetic_hand_partial')
   page.wait_for_function("()=>document.getElementById('definition').value.includes('reduce_fraction')",timeout=30000)
   page.check('#trusted');page.click('#runButton')
   page.wait_for_function('()=>!HKSStudio.running&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)',timeout=90000)
   assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
   answer=page.evaluate('HKSStudio.result');result=answer['result']
   expected=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())['synthetic_hand_partial']['result']
   assert result==expected and result['synthetic'] and len(result['trades'])==2
   assert Decimal(result['accounts']['SHARED']['ending_equity'])==Decimal('1017.5')
   with page.expect_download() as download:page.click('#exportTrades')
   target=out/'synthetic-partial-trades.csv';download.value.save_as(target);assert len(list(csv.DictReader(target.open())))==2
   page.locator('#trades tbody button').first.click();assert page.locator('#tradeDialog').is_visible();page.click('#closeDetail')
   page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=60000)
   assert page.evaluate('HKSStudio.result.result.result_hash')==result['result_hash']
   source=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
   info=page.evaluate('''async code=>{const s=new HKSStudio.SandboxClient();const info=await s.init(code);s.stop();return info;}''',source)
   assert info['contextContract']=='HKS_BROWSER_COMPLETED_CONTEXT/2' and info['contextTimeframes']==['15m','1h'] and info['origin']=='null'
   page.set_viewport_size({'width':412,'height':915});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   record.update(passed=True,financial_result_exact=True,result_hash=result['result_hash'],closed_exit_segments=2,
    ending_synthetic_equity='1017.5',csv_and_details=True,reload_restores_report=True,
    context_api=info,mobile_viewport_no_overflow=True,physical_android_tested=False)
   assert not record['page_errors'];print(json.dumps(record,indent=2))
 except BaseException as e:record.update(passed=False,failure=repr(e));raise
 finally:(out/'SOURCE_BROWSER_EVIDENCE.json').write_text(json.dumps(record,indent=2))

if __name__=='__main__':main()
