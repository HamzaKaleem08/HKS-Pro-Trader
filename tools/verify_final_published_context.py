"""Final live three-day SMC parity, unchanged stored data, and browser restart.

Only the disposable QA profile and published static site are accessed. Actual
strategy code executes solely in the opaque Pyodide worker, never host Python.
"""
import argparse,contextlib,csv,gzip,hashlib,json,os,re,tempfile,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from verify_context_browser import run_form,wait_activated,storage_snapshot
from verify_consent_browser import reconcile,save_gzip

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
URL='https://hks-pro-trader-browser-staging.pages.dev/?sandbox=completed-context-v2'
ap=argparse.ArgumentParser();ap.add_argument('--profile',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
out=args.output;out.mkdir(parents=True,exist_ok=False)
record={'url':URL,'strategy_file_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),'runs':{},'page_errors':[],
        'physical_android_tested':False,'trading_orders':False,'account_credentials_used':False}
try:
 with tempfile.TemporaryDirectory(prefix='hks-final-live-context-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
    env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
    env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
    options=dict(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env,
        proxy={'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']},timeout=45000,
        viewport={'width':1440,'height':1000},accept_downloads=True)
    context=p.chromium.launch_persistent_context(str(args.profile.resolve()),**options);cleanup.callback(context.close)
    page=context.pages[0] if context.pages else context.new_page();page.set_default_timeout(45000)
    page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
    response=page.goto(URL,wait_until='networkidle',timeout=60000);assert response.status==200
    page.wait_for_function('()=>!!window.HKSStudio',timeout=60000);assert page.evaluate('crossOriginIsolated')
    wait_activated(page,re.search(r"const CACHE='([^']+)'",(ROOT/'web/sw.js').read_text()).group(1))
    record['http_status']=response.status;record['runtime_source_hash']=page.evaluate('HKSStudio.sourceHash')
    record['before_data']=storage_snapshot(page)
    info=page.evaluate('''async code=>{const c=new HKSStudio.SandboxClient();const info=await c.init(code);c.stop();return info;}''',SOURCE)
    assert info['contextContract']=='HKS_BROWSER_COMPLETED_CONTEXT/2' and info['contextTimeframes']==['15m','1h'] and info['origin']=='null';record['actual_context_api']=info
    requests=[];page.on('request',lambda r:requests.append(r.url))
    for mode in ['shared','individual']:
        print('FINAL PUBLISHED THREE-DAY RUN',mode,flush=True);first=len(requests)
        run_form(page,mode,'2025-11-02T00:00','2025-11-05T00:00')
        assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
        answer=page.evaluate('HKSStudio.result');r=answer['result']
        previous=json.loads(gzip.decompress((ROOT/'deployment/smc-context-v2-20261019/live-complete'/(mode+'-genuine-result.json.gz')).read_bytes()))
        assert r==previous['result'],'Full three-day financial result changed after offline routing correction'
        save_gzip(out/(mode+'-genuine-result.json.gz'),answer)
        assert page.input_value('#definition')==SOURCE and r['config']['allow_uncertified_futures'] is True
        assert not r['synthetic'] and r['exchange']=='BINANCE' and r['market']=='USDT_LINEAR_PERPETUAL'
        with page.expect_download() as dl:page.click('#exportTrades')
        target=out/(mode+'-trades.csv');dl.value.save_as(target);assert len(list(csv.DictReader(target.open())))==len(r['trades'])
        page.locator('#trades tbody button').first.click();assert page.locator('#tradeDialog').is_visible();page.click('#closeDetail')
        page.locator('#result').screenshot(path=str(out/(mode+'-live-results.png')))
        record['runs'][mode]={'closed':len(r['trades']),'open':len(r['open_positions']),'result_hash':r['result_hash'],
            'accounts':r['accounts'],'full_financial_parity':True,'journal_detail_and_csv':True,
            'independent_reconciliation':reconcile(r),'metrics':answer['metrics'],
            'candle_network_requests':sum('/candles/' in u for u in requests[first:])}
        assert record['runs'][mode]['candle_network_requests']==0,'Verified cached candles were needlessly downloaded'
        page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=60000)
        assert page.evaluate('HKSStudio.result.result.result_hash')==r['result_hash'] and page.input_value('#definition')==SOURCE
        assert page.is_checked('#diagnostic');record['runs'][mode]['reload_persistence']=True
        print('FINAL LIVE PASS',mode,r['result_hash'],flush=True)
    # Offline reopening is a report/storage check, not a claim of fully offline
    # Python execution. The separate offline Python deadline is disclosed.
    expected=record['runs']['individual']['result_hash']
    context.set_offline(True);page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=60000)
    assert page.evaluate('HKSStudio.result.result.result_hash')==expected;record['versioned_offline_report_reload']=True
    context.set_offline(False)
    page.set_viewport_size({'width':412,'height':915});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(out/'mobile-emulation.png'),full_page=True);record['mobile_emulation']=True
    context.close()
    # A genuinely new Chromium process reopens the persisted QA workspace.
    context=p.chromium.launch_persistent_context(str(args.profile.resolve()),**options);cleanup.callback(context.close)
    page=context.pages[0] if context.pages else context.new_page();page.goto(URL,wait_until='networkidle',timeout=60000)
    page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=60000)
    assert page.evaluate('HKSStudio.result.result.result_hash')==expected and page.input_value('#definition')==SOURCE and page.is_checked('#diagnostic')
    record['new_browser_process_restore']=True
    after=storage_snapshot(page)
    for original in record['before_data']['datasets']:
        assert original in after['datasets'],'Existing verified data was overwritten'
    for original in record['before_data']['jobs']:
        assert original in after['jobs'],'Existing historical job was overwritten'
    assert record['before_data']['candles']==after['candles']
    record['existing_reports_jobs_candles_preserved']=True
    assert not record['page_errors'],record['page_errors'];record['passed']=True
except BaseException as ex:record.update(passed=False,failure=repr(ex));raise
finally:(out/'FINAL_LIVE_EVIDENCE.json').write_text(json.dumps(record,indent=2,default=str))
