"""Genuine local Chromium regression; never executes user Python on the host.

Requires separately preserved checksum-matching public candle data. All browser
storage is disposable. No downloads, credentials, deployments or orders.
"""
import argparse,contextlib,csv,gzip,hashlib,importlib.util,json,os,re,shutil,threading,time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,unquote
from verify_consent_browser import reconcile
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
START=1764288000000  # 2025-11-28T00:00:00Z
END=1764547200000    # 2025-12-01T00:00:00Z
INSTRUMENT=r'''(()=>{
window.__resetQA=()=>window.__qa={events:[],trace:[],callbackMs:0,callbackMaxMs:0,snapshotMs:0,persistMs:0,latencyMs:0,progress:[]};__resetQA();
const Original=window.Worker;window.Worker=class extends Original{constructor(url,...args){super(url,...args);if(String(url).includes('financial-worker'))this.addEventListener('message',({data:d})=>{if(['loaded','checkpoint','progress','done','fatal'].includes(d.type))__qa.events.push({type:d.type,at:performance.now(),loaded:d.loaded,metrics:d.metrics,next_ms:d.next_ms??d.snapshot?.next_ms,error:d.error});});}};
})();'''
INSTALL=r'''()=>{
for(const name of ['step','control']){const old=HKSStudio.SandboxClient.prototype[name];HKSStudio.SandboxClient.prototype[name]=async function(...args){const t=performance.now();if(name==='step'){const f=typeof args[0]==='string'?JSON.parse(args[0]):args[0];__qa.trace.push([f.symbol,f.bars.at(-1).open_ms]);if(__qa.latencyMs)await new Promise(r=>setTimeout(r,__qa.latencyMs));}try{return await old.apply(this,args);}finally{const ms=performance.now()-t;if(name==='step'){__qa.callbackMs+=ms;__qa.callbackMaxMs=Math.max(__qa.callbackMaxMs,ms);}else __qa.snapshotMs+=ms;}};}
const save=HKSStudio.store.saveCheckpoint.bind(HKSStudio.store);HKSStudio.store.saveCheckpoint=async(...args)=>{const t=performance.now();try{return await save(...args);}finally{__qa.persistMs+=performance.now()-t;}};
const saveData=HKSStudio.store.saveDataset.bind(HKSStudio.store);HKSStudio.store.saveDataset=async(...args)=>{const t=performance.now();if(args[3]?.kind==='report'){const done=__qa.events.findLast(x=>x.type==='done');__qa.reportJSONAndGzipMs=done?t-done.at:null;__qa.compressedReportBytes=args[1].byteLength;}try{return await saveData(...args);}finally{if(args[3]?.kind==='report')__qa.reportWriteAndVerificationMs=performance.now()-t;}};
new MutationObserver(()=>__qa.progress.push(document.getElementById('jobProgress').value)).observe(document.getElementById('jobProgress'),{attributes:true,attributeFilter:['value']});
window.addEventListener('hks-checkpoint',e=>{if(window.__interruptAt&&e.detail.next_ms>=__interruptAt){window.__interruptAt=null;document.getElementById('cancel').click();}});
}'''


def save(path,value):
    raw=json.dumps(value,separators=(',',':')).encode()
    if path.suffix=='.gz':raw=gzip.compress(raw,mtime=0)
    temp=path.with_name(path.name+'.pending');temp.write_bytes(raw);temp.replace(path)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument('--suite',choices=['smoke','full','latency','synthetic'],default='full')
    ap.add_argument('--port',type=int,default=0);ap.add_argument('--latency-ms',type=int,default=15)
    ap.add_argument('--expect-timeout',action='store_true',help='Baseline stress reproduction only; not a successful backtest')
    ap.add_argument('--continue-from',type=Path,help='Reuse hash-verified COMPLETE controls only; preserve the original failure receipt')
    args=ap.parse_args();root=args.root.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    record={'suite':args.suite,'genuine_market':'BINANCE USD-M USDT perpetual Futures, diagnostic only',
            'start_utc':'2025-11-28T00:00:00Z','end_exclusive_utc':'2025-12-01T00:00:00Z',
            'physical_android_tested':False,'owner_browser_storage_accessed':False,'external_network_requests':False,
            'runs':{},'page_errors':[],'peak_chromium_rss_bytes':0}
    try:
      excluded=json.loads((root/'HISTORICAL_DATA_EXCLUSIONS.json').read_text())['excluded_files']
      for x in excluded:
        raw=(args.data_root/x['path']).read_bytes()
        assert len(raw)==x['bytes'] and hashlib.sha256(raw).hexdigest()==x['sha256'],x['path']
      record['verified_source_inputs']=len(excluded)
      original=(root/'examples/hks_legacy_smc_reverse.py').read_text()
      assert hashlib.sha256(original.encode()).hexdigest()=='d967f440b871d6fe14d0b65ad8c051fbd984fe366676f0be0117eddeb282d53e'
      record['strategy_sha256']=hashlib.sha256(original.encode()).hexdigest()
      with sync_playwright() as p,contextlib.ExitStack() as cleanup:
        spec=importlib.util.spec_from_file_location('checkpoint_headers',root/'serve.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        allow={x['path'] for x in excluded}
        class Handler(m.Handler):
          def translate_path(self,path):
            rel='web/'+unquote(urlsplit(path).path).lstrip('/')
            return str(args.data_root/rel) if rel in allow else super().translate_path(path)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start();cleanup.callback(server.server_close);cleanup.callback(server.shutdown)
        origin=f'http://127.0.0.1:{server.server_port}';record['local_origin']=origin
        env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
        env.update(XDG_CONFIG_HOME=str(out/'browser-config'),XDG_CACHE_HOME=str(out/'browser-cache'))
        options=dict(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env,timeout=45000,
                     viewport={'width':1440,'height':1000},accept_downloads=True)
        requests=[];current={};profile=out/'disposable-profile'
        def open_browser():
            context=p.chromium.launch_persistent_context(str(profile),**options);cleanup.callback(context.close)
            context.add_init_script(INSTRUMENT);page=context.pages[0];page.set_default_timeout(45000)
            page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
            page.on('request',lambda r:requests.append(r.url))
            page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
            page.evaluate(INSTALL)
            current.update(context=context,page=page)
            return page
        page=open_browser();symbols=sorted(page.evaluate('HKSStudio.months.map(x=>x.symbol)'))
        assert len(symbols)==20;record['symbols']=symbols;record['source_hash']=page.evaluate('HKSStudio.sourceHash')
        record['browser_version']=current['context'].browser.version
        t=time.monotonic();record['cold_cache']=page.evaluate('async()=>await HKSStudio.cacheAll()');record['cache_seconds']=time.monotonic()-t
        record['warm_cache']=page.evaluate('async()=>await HKSStudio.cacheAll()');assert record['warm_cache']=={'downloaded':0,'reused':20}
        fingerprint=page.evaluate("async()=> (await HKSStudio.store.all('datasets')).filter(x=>x.id.startsWith('BINANCE_USDM_')).map(x=>[x.id,x.hash,x.bytes]).sort()")
        def configure(coins,end=END,mode='individual'):
            request={'source':'binance-november-2025','definition':{'schema_version':1,'kind':'PYTHON_STRATEGY','name':'Exact OLD SMC Reverse','code':original},
              'symbols':coins,'interval':'1m','config':{'start_ms':START,'end_ms':end,'mode':mode,'initial_capital':'1000',
              'fee_bps':'10','slippage_bps':'2','risk_fraction':'0.01','max_positions':3,'end_policy':'KEEP_OPEN','allow_uncertified_futures':True}}
            page.evaluate('r=>HKSStudio.applyRequest(r)',request);page.check('#trusted');page.check('#diagnostic')
            return request
        def wait_finished(label,old_id=None):
            start=time.monotonic();last=-30
            while True:
                page.wait_for_timeout(500)
                state=page.evaluate('()=>({running:HKSStudio.running,id:HKSStudio.job?.id,status:HKSStudio.job?.status,stage:document.getElementById("jobStage").textContent,progress:document.getElementById("jobProgress").value})')
                elapsed=time.monotonic()-start
                if elapsed-last>=30:
                    print(label,round(elapsed,1),state['stage'],flush=True);last=elapsed
                    save(out/'CURRENT_STATUS.json',{'label':label,'seconds':elapsed,**state})
                try:
                    browser=current['context'].browser;session=browser.new_browser_cdp_session()
                    processes=session.send('SystemInfo.getProcessInfo')['processInfo'];session.detach()
                    rss=sum(int((Path('/proc')/str(x['id'])/'statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE') for x in processes if (Path('/proc')/str(x['id'])/'statm').exists())
                    record['peak_chromium_rss_bytes']=max(record['peak_chromium_rss_bytes'],rss)
                except Exception:pass
                if not state['running'] and state['id'] and state['id']!=old_id:return state,elapsed
                if elapsed>3600:raise TimeoutError('QA ceiling, not a raised engine limit: '+label)
        def collect(label,before,elapsed,expect='COMPLETE'):
            state=page.evaluate('HKSStudio.job');profile_stats=page.evaluate('__qa')
            item={'status':state['status'],'job':state['id'],'seconds':elapsed,'progress':page.evaluate("document.getElementById('jobProgress').value"),
                  'candle_network_requests':sum('/candles/' in u for u in requests[before:]),'profile_file':save(out/(label+'-profile.json.gz'),profile_stats)}
            record['runs'][label]=item;save(out/'EVIDENCE.json',record)
            assert item['candle_network_requests']==0,'Warm-cache candle redownload'
            assert state['status']==expect,(label,state.get('error'))
            if expect!='COMPLETE':return state,profile_stats
            answer=page.evaluate('HKSStudio.result');result=answer['result']
            item.update(result_hash=result['result_hash'],metrics=answer['metrics'],closed=len(result['trades']),open=len(result['open_positions']),
                        reconciliation=reconcile(result),result_file=save(out/(label+'-result.json.gz'),answer))
            if result['trades']:
                with page.expect_download() as d:page.click('#exportTrades')
                d.value.save_as(out/(label+'-trades.csv'))
                with (out/(label+'-trades.csv')).open() as f:assert len(list(csv.DictReader(f)))==len(result['trades'])
            assert len(profile_stats['trace'])==len({tuple(x) for x in profile_stats['trace']}),'Repeated callback timestamp'
            item['csv_verified']=True if result['trades'] else 'Not applicable: unchanged UI omits empty CSV exports';save(out/'EVIDENCE.json',record)
            return result,profile_stats
        def run(label,coins,end=END,interrupt=None,latency=0):
            old=page.evaluate('HKSStudio.job?.id');configure(coins,end);page.evaluate('__resetQA()');page.evaluate('ms=>__qa.latencyMs=ms',latency)
            if interrupt:page.evaluate('ms=>window.__interruptAt=ms',interrupt)
            before=len(requests);page.click('#runButton');state,elapsed=wait_finished(label,old)
            expected='CANCELLED' if interrupt else ('FAILED' if args.expect_timeout else 'COMPLETE')
            return collect(label,before,elapsed,expected)
        if args.suite=='latency':
            result,stats=run('twenty-symbol-latency',symbols,START+120*60000,latency=args.latency_ms)
            if args.expect_timeout:
                assert re.search('30-second chunk deadline exceeded|replay wall budget exceeded',result.get('error','')),result
                assert stats['trace'],'A cold-start failure is not a chunk-timeout reproduction'
                record['expected_baseline_resource_failure_reproduced']=True
        elif args.suite=='smoke':
            run('twenty-symbol-smoke',symbols,START+30*60000)
        elif args.suite=='synthetic':
            expected=json.loads((root/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())
            for name,oracle in expected.items():
                answer=page.evaluate('''async id=>{const b=await HKSStudio.fixture(id);try{return await new HKSStudio.BrowserEngine().run(b);}catch(e){return {ok:false,error:e.message};}}''',name)
                assert answer['ok']==oracle['ok'],(name,answer)
                if answer['ok']:assert answer['result']==oracle['result'],name
                record['runs'][name]={'passed':True,'expected_invalid':not oracle['ok']};save(out/'EVIDENCE.json',record)
        else:
            previous=None
            if args.continue_from:
                prior=args.continue_from.resolve();receipt=prior/'EVIDENCE.json'
                previous=json.loads(receipt.read_text())
                assert previous['source_hash']==record['source_hash'],'Cannot reuse another runtime identity'
                assert previous['strategy_sha256']==record['strategy_sha256']
                assert previous['symbols']==symbols
                assert previous['start_utc']==record['start_utc'] and previous['end_exclusive_utc']==record['end_exclusive_utc']
                record['preserved_previous_campaign']={'path':str(prior),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),
                    'passed':previous.get('passed'),'failure':previous.get('failure'),
                    'note':'Reuse only byte-verified complete controls; do not erase the prior strategy-response timeout.'}
                record['peak_chromium_rss_bytes']=max(record['peak_chromium_rss_bytes'],previous.get('peak_chromium_rss_bytes',0))
            def control(label,coins):
                item=previous.get('runs',{}).get(label) if previous else None
                if not item or item['status']!='COMPLETE':return run(label,coins)[0]
                for kind in ['profile','result']:
                    name=label+'-'+kind+'.json.gz';raw=(prior/name).read_bytes();info=item[kind+'_file']
                    assert len(raw)==info['bytes'] and hashlib.sha256(raw).hexdigest()==info['sha256'],name
                    shutil.copy2(prior/name,out/name)
                answer=json.loads(gzip.decompress((out/(label+'-result.json.gz')).read_bytes()))
                result=answer['result'];assert result['result_hash']==item['result_hash'] and result['symbols']==coins
                assert reconcile(result)==item['reconciliation']
                assert answer['metrics']['loaded']['loaded_candles']==len(coins)*(4320+1320)
                if result['trades']:
                    name=label+'-trades.csv';shutil.copy2(prior/name,out/name)
                    with (out/name).open() as f:assert len(list(csv.DictReader(f)))==len(result['trades'])
                record['runs'][label]={**item,'reused_verified_control_from':str(prior)}
                save(out/'EVIDENCE.json',record)
                return result
            combined=control('combined-20',symbols)
            batches=[]
            for i,coins in enumerate([symbols[:7],symbols[7:14],symbols[14:]]):batches.append(control('batch-'+str(i+1),coins))
            for symbol in symbols:
                batch=next(x for x in batches if symbol in x['symbols'])
                for field in ['accounts','signal_counts','reconciliation']:assert combined[field][symbol]==batch[field][symbol],(symbol,field)
                for field in ['trades','open_positions','decisions']:
                    assert [x for x in combined[field] if x['symbol']==symbol]==[x for x in batch[field] if x['symbol']==symbol],(symbol,field)
                assert [x for x in combined['equity_curve'] if x['account']==symbol]==[x for x in batch['equity_curve'] if x['account']==symbol],symbol
            record['combined_equals_7_7_6_per_symbol']=True
            stopped,_=run('interrupted-20',symbols,interrupt=START+(END-START)//4)
            snapshot=page.evaluate('async()=>await HKSStudio.store.checkpoint(HKSStudio.job)');cursor=snapshot['finance']['next_ms']
            assert cursor>START
            current['context'].close();page=open_browser();page.evaluate('async id=>await HKSStudio.showJob(id)',stopped['id'])
            assert page.evaluate("document.getElementById('jobProgress').value")>0
            before=len(requests);page.evaluate('__resetQA()');page.check('#trusted');page.check('#diagnostic');page.click('#retry')
            state,elapsed=wait_finished('resumed-20');resumed,trace=collect('resumed-20',before,elapsed)
            assert resumed==combined,'Uninterrupted/resumed full financial result mismatch'
            assert all(ts>=cursor for _,ts in trace['trace']),'A callback before the verified cursor was repeated'
            assert min(trace['progress'])>0,'Resumed UI progress reset to zero'
            record.update(resume_cursor=cursor,restored_strategy_and_financial_state_exact=True,no_callbacks_before_saved_cursor=True,
                          resumed_full_result_hash_equals_uninterrupted=True,resume_progress_never_reset=True,new_browser_process_resume=True)
            saved_hash=resumed['result_hash'];page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio?.result',timeout=60000)
            assert page.evaluate('HKSStudio.result.result.result_hash')==saved_hash;record['completed_report_reload']=True
        after=page.evaluate("async()=> (await HKSStudio.store.all('datasets')).filter(x=>x.id.startsWith('BINANCE_USDM_')).map(x=>[x.id,x.hash,x.bytes]).sort()")
        assert after==fingerprint;record['candle_cache_fingerprint_unchanged']=True
        assert not record['page_errors'],record['page_errors'];record['passed']=True
    except BaseException as e:record.update(passed=False,failure=repr(e));raise
    finally:save(out/'EVIDENCE.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ['runs']},indent=2),flush=True)


if __name__=='__main__':main()
