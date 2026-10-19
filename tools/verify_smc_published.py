"""Owner-authorized published-site SMC verification; disposable browser state only.

No host strategy execution, exchange requests, account secrets or publication.
Before/after profiles may be reused to verify a non-destructive site upgrade.
"""
import argparse,contextlib,csv,gzip,hashlib,json,os,re,tempfile,time
from pathlib import Path
from decimal import Decimal as D
from playwright.sync_api import sync_playwright
from verify_consent_browser import reconcile,save_gzip
from verify_smc_browser import synthetic_cases,check_decision

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://hks-pro-trader-browser-staging.pages.dev'
SOURCE=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
EXPECTED=json.loads((ROOT/'evidence/smc-compat-v1/browser/BROWSER_EVIDENCE.json').read_text())

def wait_job(page,before,timeout=300000):
    page.wait_for_function('id=>!HKSStudio.running&&HKSStudio.job?.id!==id&&["COMPLETE","FAILED","CANCELLED"].includes(HKSStudio.job?.status)',arg=before,timeout=timeout)

def run_form(page,mode,start,end):
    page.fill('#definition',SOURCE);page.fill('#strategyName','HKS Legacy SMC Reverse — compatibility V1')
    page.select_option('#dataset','binance-november-2025')
    page.fill('#start',start);page.fill('#end',end);page.select_option('#mode',mode)
    if not page.locator('details.advanced').evaluate('(x)=>x.open'):page.click('details.advanced > summary')
    for name,value in [('risk','0.01'),('maxPositions','3'),('fees','10'),('slippage','2')]:page.fill('#'+name,value)
    page.check('#diagnostic');page.check('#trusted')
    previous=page.evaluate('HKSStudio.job?.id');page.click('#runButton');wait_job(page,previous)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['before','after','fresh'],required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--profile',type=Path,required=True)
    ap.add_argument('--short',action='store_true');ap.add_argument('--regression-only',action='store_true')
    ap.add_argument('--ephemeral',action='store_true');args=ap.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=False);args.profile.mkdir(parents=True,exist_ok=True)
    record={'phase':args.phase,'url':ORIGIN,'strategy_file_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),
        'strategy_version':'PYTHON_V1_3fe0dbe04e6fb837d0cfaacc3b031b521c55d36acee0253fc546a06563e159f8',
        'page_errors':[],'runs':{},'synthetic_checks':[],'frozen_parity':[],'physical_android_tested':False,
        'trading_orders':False,'credentials_supplied_to_browser':False}
    try:
        with tempfile.TemporaryDirectory(prefix='hks-smc-live-xdg-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
            environment={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
            environment.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
            options=dict(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=environment,
                proxy={'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']},timeout=45000)
            if args.ephemeral:
                browser=p.chromium.launch(**options);cleanup.callback(browser.close)
                context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            else:context=p.chromium.launch_persistent_context(str(args.profile.resolve()),viewport={'width':1440,'height':1000},accept_downloads=True,**options)
            cleanup.callback(context.close)
            page=context.pages[0] if context.pages else context.new_page();page.set_default_timeout(45000)
            page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
            requests=[];page.on('request',lambda r:requests.append(r.url))
            response=page.goto(ORIGIN,wait_until='networkidle',timeout=60000)
            record['http_status']=response.status
            headers=response.all_headers()
            record['headers']={k:headers.get(k) for k in ['content-type','cross-origin-opener-policy',
                'cross-origin-embedder-policy','cross-origin-resource-policy','content-security-policy']}
            assert response.status==200,{'status':response.status,'body':page.inner_text('body')[:500]}
            page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
            assert page.evaluate('crossOriginIsolated')
            if args.phase!='before':
                # Await the site's own normal service-worker update and reload.
                # Do not clear caches/storage or disable its isolation policies.
                page.evaluate('''async()=>{const r=await navigator.serviceWorker.getRegistration();if(r)await r.update();}''')
                expected_cache=re.search(r"const CACHE='([^']+)'",(ROOT/'web/sw.js').read_text()).group(1)
                page.wait_for_function('''async expected=>{const keys=await caches.keys();const r=await navigator.serviceWorker.getRegistration();
                    return keys.includes(expected)&&!keys.some(k=>k.startsWith('hks-premium-static-')&&k!==expected)
                        &&r?.active?.state==='activated'&&!r.installing&&!r.waiting;}''',arg=expected_cache,timeout=120000)
                page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
            record['sourceHash']=page.evaluate('HKSStudio.sourceHash')
            if args.phase!='before':assert record['sourceHash']==EXPECTED['sourceHash'],record['sourceHash']
            record['assets']={}
            names=['app.js','strategy-worker.js','kernel.json','sw.js','client.js','storage.js','financial-worker.js','sandbox.html','replay-consent.js','style.css','boot.js']
            for name in names:
                result=page.evaluate('''async name=>{const r=await fetch(name,{cache:'no-store'});return {status:r.status,text:await r.text()};}''',name)
                assert result['status']==200,(name,result['status'])
                raw=result['text'].encode();(out/name).write_bytes(raw)
                record['assets'][name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
                if args.phase!='before':assert raw==(ROOT/'web'/name).read_bytes(),name
            if args.phase=='before':
                assert 'Context.candles=' not in (out/'strategy-worker.js').read_text()
                run_form(page,'shared','2025-11-02T23:00','2025-11-03T03:00')
                job=page.evaluate('HKSStudio.job');record['failed_job']=job;record['visible_error']=page.inner_text('#message')
                assert job['status']=='FAILED' and "has no attribute 'candles'" in job['error'],job
                record['exact_failure_reproduced']=True
                record['cache_before']=page.evaluate('async()=>await HKSStudio.store.all("datasets")')
                page.screenshot(path=str(out/'exact-live-failure.png'),full_page=True)
                print('EXACT LIVE FAILURE REPRODUCED:',record['visible_error'],flush=True)
            else:
                # Hash-read all pre-existing candle records; never overwrite them.
                cached=page.evaluate('''async()=>{const rows=await HKSStudio.store.all('datasets');
                    const values=[];for(const row of rows.filter(x=>x.id.startsWith('BINANCE_USDM_'))){
                        const x=await HKSStudio.store.readDataset(row.id);values.push({id:x.id,hash:x.hash,bytes:x.bytes.byteLength});}return values;}''')
                record['retained_candle_cache']=cached
                if args.phase=='after':assert len(cached)>=2,'Pre-upgrade verified candle cache not retained'
                if args.phase=='fresh':
                    info=page.evaluate('async code=>{window.smcProbe=new HKSStudio.SandboxClient();return await smcProbe.init(code);}',SOURCE)
                    assert info['origin']=='null';record['opaque_strategy_origin']=info['origin']
                    for case in synthetic_cases():
                        answer=page.evaluate('async f=>JSON.parse(await smcProbe.step(f))',case['frame'])
                        if case.get('error'):assert answer.get('error'),answer
                        else:assert not answer.get('error'),answer;check_decision(answer['decision'],case['expected'])
                        record['synthetic_checks'].append({'name':case['label'],'passed':True})
                    page.evaluate('smcProbe.stop()')
                if args.phase=='after' and not args.short:
                    windows=[('genuine','2025-11-02T00:00','2025-11-05T00:00','LONG'),
                             ('reverse-short','2025-11-17T14:00','2025-11-17T16:00','SHORT')]
                else:
                    windows=[('genuine','2025-11-02T23:00','2025-11-03T03:00','LONG'),
                             ('reverse-short','2025-11-17T14:00','2025-11-17T16:00','SHORT')]
                if args.regression_only:windows=[]
                for name,start,end,side in windows:
                    for mode in ('shared','individual'):
                        begin=len(requests)
                        if args.phase=='after' and name=='genuine' and mode=='individual':
                            page.evaluate('''()=>{window.smcCheckpoint=null;window.addEventListener('hks-checkpoint',async e=>{
                                if(e.detail.next_ms>=Date.parse('2025-11-03T00:00:00Z')&&!window.smcCheckpoint){
                                    window.smcCheckpoint={pending:true};const job=structuredClone(HKSStudio.job);
                                    window.smcCheckpoint={job,snapshot:await HKSStudio.store.checkpoint(job)};}});}''')
                        run_form(page,mode,start,end)
                        assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
                        answer=page.evaluate('HKSStudio.result');r=answer['result'];positions=r['trades']+r['open_positions']
                        assert not r['synthetic'] and r['exchange']=='BINANCE' and r['market']=='USDT_LINEAR_PERPETUAL'
                        assert positions and all(t['side']==side and t['target'] is None for t in positions)
                        assert r['strategy_version']==record['strategy_version']
                        check=reconcile(r)
                        key=mode+'-'+name;save_gzip(out/(key+'-result.json.gz'),answer)
                        record['runs'][key]={'closed':len(r['trades']),'open':len(r['open_positions']),
                            'result_hash':r['result_hash'],'accounts':r['accounts'],'metrics':answer['metrics'],
                            'reconciliation':check,'requests_for_candles':sum('/candles/' in u for u in requests[begin:])}
                        if args.phase=='after' and name=='genuine':assert record['runs'][key]['requests_for_candles']==0
                        if args.phase=='fresh' or name=='reverse-short':
                            expected_file=ROOT/'evidence/smc-compat-v1/browser'/((mode+'-genuine-result' if name=='genuine' else mode+'-reverse-short-result')+'.json.gz')
                            expected=json.loads(gzip.decompress(expected_file.read_bytes()))['result']
                            assert r==expected,'Live/local complete financial result mismatch: '+key
                            record['runs'][key]['exact_local_parity']=True
                        if r['trades']:
                            with page.expect_download() as dl:page.click('#exportTrades')
                            path=out/(key+'-trades.csv');dl.value.save_as(path)
                            assert len(list(csv.DictReader(path.open())))==len(r['trades'])
                            record['runs'][key]['csv_export']=True
                        else:
                            page.click('#exportTrades')
                            assert 'No records to export' in page.inner_text('#message')
                            record['runs'][key]['csv_export']='NO_CLOSED_TRADES_CONTROLLED_EMPTY_STATE'
                        if args.phase=='after' and name=='genuine' and mode=='individual':
                            snapshot=page.evaluate('window.smcCheckpoint');assert snapshot and 'snapshot' in snapshot
                            save_gzip(out/'restart-checkpoint.json.gz',snapshot)
                        page.screenshot(path=str(out/(key+'.png')),full_page=True)
                        h=r['result_hash'];page.reload(wait_until='networkidle');page.wait_for_function('()=>!!HKSStudio.result',timeout=60000)
                        assert page.evaluate('HKSStudio.result.result.result_hash')==h
                        assert page.input_value('#definition')==SOURCE and page.is_checked('#diagnostic')
                        record['runs'][key]['reload_persistence']=True
                        print(args.phase,key,'COMPLETE',len(r['trades']),'closed',len(r['open_positions']),'open',h,flush=True)
                if args.phase=='after':
                    sample=json.loads(gzip.decompress((out/'restart-checkpoint.json.gz').read_bytes()))
                    sample['job'].update(id='smc-live-independent-restart',status='CANCELLED')
                    page.evaluate('''async x=>{await HKSStudio.store.saveCheckpoint(x.job,x.snapshot);await HKSStudio.showJob(x.job.id);}''',sample)
                    page.check('#trusted');page.check('#diagnostic');page.click('#retry')
                    page.wait_for_function('()=>!HKSStudio.running&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)',timeout=300000)
                    assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
                    answer=page.evaluate('HKSStudio.result');expected=json.loads(gzip.decompress((out/'individual-genuine-result.json.gz').read_bytes()))
                    assert answer['result']==expected['result'];save_gzip(out/'restarted-genuine-result.json.gz',answer)
                    record['restart']={'exact_full_result_parity':True,'result_hash':answer['result']['result_hash']}
                    print('LIVE CHECKPOINT RESTART: exact full-result parity',flush=True)
                if args.phase=='fresh':
                    baselines=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())
                    for entry in json.loads((ROOT/'web/catalog.json').read_text()):
                        a=page.evaluate('''async id=>{try{return await new HKSStudio.BrowserEngine().run(await HKSStudio.fixture(id));}catch(e){return {ok:false,error:e.message};}}''',entry['id'])
                        e=baselines[entry['id']]
                        row={'id':entry['id'],'actual_ok':a['ok'],'expected_ok':e['ok'],'error':a.get('error')}
                        record['frozen_parity'].append(row)
                        assert a['ok']==e['ok'],(entry['id'],a.get('error'))
                        if a['ok']:assert a['result']==e['result'],entry['id']
                        row['passed']=True
                        print('LIVE FROZEN PARITY:',entry['id'],'PASS',flush=True)
                    page.set_viewport_size({'width':412,'height':915});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(out/'mobile-emulation.png'),full_page=True)
                    record['mobile_emulation_no_overflow']=True
                assert not record['page_errors'],record['page_errors']
            record['passed']=True
    except BaseException as ex:
        record['passed']=False;record['failure']=repr(ex);raise
    finally:
        (out/'LIVE_EVIDENCE.json').write_text(json.dumps(record,indent=2,default=str))

if __name__=='__main__':main()
