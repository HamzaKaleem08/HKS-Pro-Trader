"""Actual browser Context delivery, old-cache upgrade, and unchanged SMC replay.

Uses only disposable browser state. Exact strategy executes in opaque Pyodide,
never host Python. No account data, exchange access, or deployment in this tool.
"""
import argparse,contextlib,csv,gzip,hashlib,importlib.util,json,os,re,tempfile,threading,time
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
from verify_smc_browser import synthetic_cases,check_decision
from verify_consent_browser import reconcile,save_gzip

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
CONTRACT='HKS_BROWSER_COMPLETED_CONTEXT/2'

def run_form(page,mode,start,end):
    page.fill('#definition',SOURCE);page.fill('#strategyName','HKS Legacy SMC Reverse — compatibility V1')
    page.select_option('#dataset','binance-november-2025')
    page.fill('#start',start);page.fill('#end',end);page.select_option('#mode',mode)
    if not page.locator('details.advanced').evaluate('(x)=>x.open'):page.click('details.advanced > summary')
    for name,value in [('risk','0.01'),('maxPositions','3'),('fees','10'),('slippage','2')]:page.fill('#'+name,value)
    page.check('#diagnostic');page.check('#trusted');previous=page.evaluate('HKSStudio.job?.id');page.click('#runButton')
    deadline=time.monotonic()+180;last=None
    while True:
        state=page.evaluate('''()=>({running:HKSStudio.running,id:HKSStudio.job?.id,status:HKSStudio.job?.status,
          stage:document.getElementById('jobStage').textContent,message:document.getElementById('message').textContent})''')
        if state['stage']!=last:
            print('UI',state['stage'],flush=True);last=state['stage']
        if not state['running'] and (state['stage'].startswith('REJECTED') or state.get('id')!=previous and state.get('status') in ['COMPLETE','FAILED','CANCELLED']):return
        if time.monotonic()>deadline:raise TimeoutError('Replay did not finish: '+json.dumps(state))
        page.wait_for_timeout(250)

def wait_activated(page,expected):
    # Playwright wait_for_function does not await an async predicate's result.
    # Explicitly await each evaluate so a pending Promise cannot count as PASS.
    deadline=time.monotonic()+120
    while True:
        ok=page.evaluate('''async expected=>{const r=await navigator.serviceWorker.getRegistration();
          const keys=await caches.keys();return r?.active?.state==='activated'&&!r.installing&&!r.waiting&&
          keys.includes(expected)&&!keys.some(k=>k.startsWith('hks-premium-static-')&&k!==expected);}''',expected)
        if ok:return
        if time.monotonic()>deadline:raise TimeoutError('Actual service-worker activation did not complete')
        page.wait_for_timeout(150)

def storage_snapshot(page):
    return page.evaluate('''async()=>({datasets:await HKSStudio.store.all('datasets'),
      jobs:await HKSStudio.store.all('jobs'),versions:await HKSStudio.store.all('versions'),
      settings:await HKSStudio.store.all('settings'),candles:await Promise.all((await HKSStudio.store.all('datasets'))
       .filter(x=>x.id.startsWith('BINANCE_USDM_')).map(async x=>{const d=await HKSStudio.store.readDataset(x.id);return {id:d.id,hash:d.hash,bytes:d.bytes.byteLength};}))})''')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--published',action='store_true')
    ap.add_argument('--await-publication',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--profile',type=Path)
    ap.add_argument('--entry-query',action='store_true')
    ap.add_argument('--three-day',action='store_true');ap.add_argument('--all-fixtures',action='store_true')
    args=ap.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=False)
    record={'published':args.published,'strategy_file_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),
       'strategy_unchanged':True,'page_errors':[],'runs':{},'synthetic_checks':[],'frozen_parity':[],
       'owner_data_accessed':False,'physical_android_tested':False}
    try:
      with tempfile.TemporaryDirectory(prefix='hks-context-v2-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
        current={}
        if args.published:origin='https://hks-pro-trader-browser-staging.pages.dev'
        else:
            spec=importlib.util.spec_from_file_location('context_headers',ROOT/'serve.py');server_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(server_module)
            current['web']=Path('/workspace/HKS-Pro-Trader-browser-consent-fix-20261018/web')
            assert "Context.candles=" not in (current['web']/'strategy-worker.js').read_text()
            class Handler(server_module.Handler):
                def __init__(self,*a,**kw):SimpleHTTPRequestHandler.__init__(self,*a,directory=str(current['web']),**kw)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
            cleanup.callback(server.server_close);cleanup.callback(server.shutdown)
            origin=f'http://127.0.0.1:{server.server_port}'
        record['url']=origin
        env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
        env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
        options=dict(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env,timeout=45000)
        if args.published:options['proxy']={'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}
        print('STARTING disposable sandboxed browser',flush=True)
        if args.profile:
            context=p.chromium.launch_persistent_context(str(args.profile.resolve()),viewport={'width':1440,'height':1000},accept_downloads=True,**options)
        else:
            browser=p.chromium.launch(**options);cleanup.callback(browser.close)
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        print('BROWSER STARTED',flush=True);cleanup.callback(context.close)
        page=context.pages[0] if context.pages else context.new_page();page.set_default_timeout(45000)
        page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
        requests=[];page.on('request',lambda r:requests.append(r.url))
        if args.profile and args.entry_query:
            # Inspect authentic old CacheStorage before entering the updated
            # app. The versioned entry is a normal same-origin navigation, not
            # route interception, cache deletion, or replacement test assets.
            page.goto(origin+'/style.css?context-inventory',wait_until='networkidle',timeout=60000)
            record['old_cached_runtime']=page.evaluate('''async()=>{const rows=[];for(const key of await caches.keys()){
              const c=await caches.open(key),r=await c.match('/strategy-worker.js');
              if(r){const text=await r.text();rows.push({cache:key,has_monkeypatch:text.includes('Context.candles='),has_context_class_import:text.includes('from browser_context_api import Context')});}}
              return rows;}''')
            record['old_storage']=page.evaluate('''async()=>{const {CandleStore}=await import('./storage.js?context-inventory');const s=await new CandleStore().init();
              return {datasets:await s.all('datasets'),jobs:await s.all('jobs'),versions:await s.all('versions'),settings:await s.all('settings'),
              candles:await Promise.all((await s.all('datasets')).filter(x=>x.id.startsWith('BINANCE_USDM_')).map(async x=>{const d=await s.readDataset(x.id);return {id:d.id,hash:d.hash,bytes:d.bytes.byteLength};}))};}''')
        entry=origin+('/?sandbox=completed-context-v2' if args.entry_query else '/')
        response=page.goto(entry,wait_until='networkidle',timeout=60000);assert response.status==200
        print('OPENED',origin,flush=True)
        try:page.wait_for_function('()=>!!window.HKSStudio',timeout=45000)
        except BaseException:
            record['startup_failure']=page.evaluate('''async()=>({message:document.getElementById('message')?.textContent,
              runtime:document.getElementById('runtimeStatus')?.textContent,caches:await caches.keys(),
              registration:await (async()=>{const r=await navigator.serviceWorker.getRegistration();return {active:r?.active?.state,installing:r?.installing?.state,waiting:r?.waiting?.state};})()})''')
            page.screenshot(path=str(out/'startup-failure.png'),full_page=True);print('STARTUP FAILED',record['startup_failure'],flush=True);raise
        assert page.evaluate('crossOriginIsolated')
        print('APP READY',flush=True)
        record['http_status']=response.status;record['before_source_hash']=page.evaluate('HKSStudio.sourceHash')
        if args.profile and args.entry_query:
            assert record['old_storage']==storage_snapshot(page),'Versioned entry modified saved owner state'
            record['non_destructive_cached_upgrade']=True
            record['entry_url']=entry
        if not args.published:
            run_form(page,'shared','2025-11-02T23:00','2025-11-03T03:00')
            record['old_error']=page.inner_text('#message')
            assert page.evaluate('HKSStudio.job.status')=='FAILED' and "has no attribute 'candles'" in record['old_error'],record['old_error']
            page.screenshot(path=str(out/'old-context-failure.png'),full_page=True)
            print('REPRODUCED authentic old Context missing candles',flush=True)
        elif args.await_publication:
            # Warm only genuine BTC/ETH and establish an ordinary old static
            # cache before publication. Never replace a service worker by test code.
            page.evaluate('''async()=>{for(const m of HKSStudio.months.filter(m=>['BTCUSDT','ETHUSDT'].includes(m.symbol)))await HKSStudio.cache(m);
              await HKSStudio.store.put('settings',{id:'context-upgrade-marker',value:'must-remain'});}''')
        if not args.published or args.await_publication:
            page.evaluate('async()=>await navigator.serviceWorker.ready')
            old=storage_snapshot(page);save_gzip(out/'before-storage.json.gz',old)
            record['before_cache_keys']=page.evaluate('async()=>await caches.keys()')
            if args.await_publication:
                print('READY FOR PUBLICATION: old published browser and verified candle cache retained',flush=True)
                deadline=time.monotonic()+1200
                while not args.await_publication.exists():
                    if time.monotonic()>deadline:raise TimeoutError('Publication approval/run did not complete')
                    page.wait_for_timeout(500)
            else:current['web']=ROOT/'web'
            page.evaluate('''async()=>{const r=await navigator.serviceWorker.getRegistration();await r.update();}''')
            expected=re.search(r"const CACHE='([^']+)'",(ROOT/'web/sw.js').read_text()).group(1)
            wait_activated(page,expected)
            page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=90000)
            after=storage_snapshot(page);save_gzip(out/'after-storage.json.gz',after)
            assert old==after,'Upgrade mutated IDB/OPFS data'
            record['non_destructive_cached_upgrade']=True
            print('PASS actual cached-browser upgrade; every dataset/job/version/setting unchanged',flush=True)
        record['source_hash']=page.evaluate('HKSStudio.sourceHash')
        assert 'Context API v2' in page.inner_text('#runtimeStatus'),page.inner_text('#runtimeStatus')
        info=page.evaluate('''async code=>{window.apiProbe=new HKSStudio.SandboxClient();return await apiProbe.init(code);}''',SOURCE)
        assert info['contextContract']==CONTRACT and info['contextTimeframes']==['15m','1h'] and info['origin']=='null',info
        record['verified_context_api']=info
        for case in synthetic_cases():
            answer=page.evaluate('async row=>JSON.parse(await apiProbe.step(row))',case['frame'])
            if case.get('error'):assert answer.get('error'),answer
            else:assert not answer.get('error'),answer;check_decision(answer['decision'],case['expected'])
            record['synthetic_checks'].append({'case':case['label'],'passed':True})
        page.evaluate('apiProbe.stop()');print('PASS actual Pyodide checks:',len(record['synthetic_checks']),flush=True)
        windows=[('genuine','2025-11-02T00:00' if args.three_day else '2025-11-02T23:00',
                  '2025-11-05T00:00' if args.three_day else '2025-11-03T03:00','LONG'),
                 ('reverse-short','2025-11-17T14:00','2025-11-17T16:00','SHORT')]
        for name,start,end,side in windows:
          for mode in ['shared','individual']:
            page.evaluate('''()=>{window.testCheckpoint=null;window.addEventListener('hks-checkpoint',async e=>{
             if(!window.testCheckpoint){window.testCheckpoint={pending:true};const job=structuredClone(HKSStudio.job);
             window.testCheckpoint={job,snapshot:await HKSStudio.store.checkpoint(job)};}});}''')
            first=len(requests)
            print('RUNNING',mode,name,start,end,flush=True)
            try:run_form(page,mode,start,end)
            except BaseException:
                record['last_visible_state']=page.evaluate('''()=>({stage:document.getElementById('jobStage').textContent,message:document.getElementById('message').textContent,job:HKSStudio.job})''')
                print('RUN FAILED',record['last_visible_state'],flush=True);raise
            assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
            answer=page.evaluate('HKSStudio.result');r=answer['result'];key=mode+'-'+name
            save_gzip(out/(key+'-result.json.gz'),answer)
            assert not r['synthetic'] and r['exchange']=='BINANCE' and r['market']=='USDT_LINEAR_PERPETUAL'
            assert all(t['target'] is None for t in r['trades']+r['open_positions'])
            if not args.three_day or name=='reverse-short':
                expected=json.loads(gzip.decompress((ROOT/'evidence/smc-compat-v1/browser'/(key+'-result.json.gz')).read_bytes()))['result']
                assert r==expected,'Frozen complete result parity mismatch: '+key
            audit=reconcile(r)
            record['runs'][key]={'closed':len(r['trades']),'open':len(r['open_positions']),'result_hash':r['result_hash'],
              'accounts':r['accounts'],'strategy_version':r['strategy_version'],'side_counts':{s:sum(x['side']==s for x in r['trades']+r['open_positions']) for s in ['LONG','SHORT']},
              'reconciliation':audit,'metrics':answer['metrics'],'source_hash':record['source_hash'],
              'candle_network_requests':sum('/candles/' in u for u in requests[first:])}
            if r['trades']:
                with page.expect_download() as download:page.click('#exportTrades')
                target=out/(key+'-trades.csv');download.value.save_as(target)
                assert len(list(csv.DictReader(target.open())))==len(r['trades'])
                page.locator('#trades tbody button').first.click();assert page.locator('#tradeDialog').is_visible();page.click('#closeDetail')
                record['runs'][key]['journal_detail_and_csv']=True
            else:
                page.click('#exportTrades');assert 'No records to export' in page.inner_text('#message')
                record['runs'][key]['csv']='CONTROLLED_NO_CLOSED_TRADES'
            if name=='genuine' and mode=='individual':
                sample=page.evaluate('window.testCheckpoint');assert sample and sample.get('snapshot')
                save_gzip(out/'restart-checkpoint.json.gz',sample)
            page.screenshot(path=str(out/(key+'.png')),full_page=True)
            page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=90000)
            assert page.evaluate('HKSStudio.result.result.result_hash')==r['result_hash']
            assert page.input_value('#definition')==SOURCE and page.is_checked('#diagnostic')
            record['runs'][key]['reload_persistence']=True
            print('COMPLETE',key,len(r['trades']),'closed',len(r['open_positions']),'open',r['result_hash'],flush=True)
        sample=json.loads(gzip.decompress((out/'restart-checkpoint.json.gz').read_bytes()));sample['job'].update(id='context-v2-resume',status='CANCELLED')
        page.evaluate('''async x=>{await HKSStudio.store.saveCheckpoint(x.job,x.snapshot);await HKSStudio.showJob(x.job.id);}''',sample)
        page.check('#trusted');page.check('#diagnostic');page.click('#retry')
        page.wait_for_function('()=>!HKSStudio.running&&["COMPLETE","FAILED"].includes(HKSStudio.job?.status)',timeout=300000)
        assert page.evaluate('HKSStudio.job.status')=='COMPLETE',page.inner_text('#message')
        answer=page.evaluate('HKSStudio.result');expected=json.loads(gzip.decompress((out/'individual-genuine-result.json.gz').read_bytes()))
        assert answer['result']==expected['result'];save_gzip(out/'resumed-result.json.gz',answer)
        record['checkpoint_full_result_parity']=True
        if args.all_fixtures:
            baselines=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())
            for entry in json.loads((ROOT/'web/catalog.json').read_text()):
                a=page.evaluate('''async id=>{try{return await new HKSStudio.BrowserEngine().run(await HKSStudio.fixture(id));}catch(e){return {ok:false,error:e.message};}}''',entry['id'])
                e=baselines[entry['id']];assert a['ok']==e['ok'],(entry['id'],a.get('error'))
                if a['ok']:assert a['result']==e['result'],entry['id']
                record['frozen_parity'].append({'id':entry['id'],'passed':True});print('FROZEN PARITY PASS',entry['id'],flush=True)
        context.set_offline(True);page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=90000)
        assert page.evaluate('HKSStudio.result.result.result_hash')==expected['result']['result_hash']
        record['offline_reload_preserves_result']=True;context.set_offline(False)
        page.set_viewport_size({'width':412,'height':915});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(out/'mobile-emulation.png'),full_page=True);record['mobile_emulation']=True
        assert not record['page_errors'],record['page_errors'];record['passed']=True
    except BaseException as ex:
      record.update(passed=False,failure=repr(ex));raise
    finally:(out/'BROWSER_EVIDENCE.json').write_text(json.dumps(record,indent=2,default=str))

if __name__=='__main__':main()
