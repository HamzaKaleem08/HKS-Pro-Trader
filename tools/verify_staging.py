"""Real sandboxed Chromium desktop/mobile-emulation integration and parity QA."""
import csv,io,json,os,re,socket,subprocess,tempfile,time,threading,sys
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]

def main():
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--origin');args=ap.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=False)
 checks=[];issues=[];console=[];errors=[];urls=[];report={'checks':checks,'issues':issues,'physical_android_tested':False,'scope':'Actual sandboxed desktop Chromium and touch-enabled Android viewport emulation; no physical device'}
 baseline=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text());report['cases']={};report['build']=json.loads((ROOT/'evidence/STATIC_BUILD.json').read_text());report['hosting_runtime']='Cloudflare Pages local workerd' if args.origin else 'Python static headers mirror'
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 origin=args.origin or f'http://127.0.0.1:{port}';log=(out/'SERVER.log').open('w');server=None if args.origin else subprocess.Popen([sys.executable,'serve.py','--port',str(port)],cwd=ROOT,stdout=log,stderr=log)
 try:
  time.sleep(.25)
  before={p.name for p in Path('/proc').iterdir() if p.name.isdigit()};stop=threading.Event();peak={}
  def measure():
   while not stop.wait(.25):
    total=0;count=0
    for proc in Path('/proc').iterdir():
     if not proc.name.isdigit() or proc.name in before:continue
     try:
      if proc.joinpath('comm').read_text().strip()!='chromium':continue
      value=next(int(line.split()[1]) for line in proc.joinpath('smaps_rollup').read_text().splitlines() if line.startswith('Pss:'))
      total+=value;count+=1
     except (OSError,ValueError,StopIteration):pass
    if total>peak.get('peak_pss_kib',0):peak.update(peak_pss_kib=total,processes=count)
  monitor=threading.Thread(target=measure,daemon=True);monitor.start()
  with tempfile.TemporaryDirectory(prefix='hks-premium-browser-',dir='/tmp') as temp,sync_playwright() as p:
   env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)};env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp);profile=Path(temp)/'profile'
   context=p.chromium.launch_persistent_context(str(profile),executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,viewport={'width':1440,'height':1000},accept_downloads=True,env=env,**({'proxy':{'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}} if args.origin else {}))
   page=context.pages[0];page.on('pageerror',lambda e:errors.append(str(e)));page.on('console',lambda m:console.append({'type':m.type,'text':m.text[:1000]}));page.on('request',lambda r:urls.append(r.url))
   page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=25000)
   assert page.evaluate('crossOriginIsolated');checks.append('Actual premium page boots with COOP/COEP and normal Chromium OS sandbox')
   # Same 14 original native cases, no changed strategy formulas, full raw result.
   for name,expected in baseline.items():
    print('PARITY',name,flush=True)
    value=page.evaluate('async id=>{const b=await HKSStudio.fixture(id);try{return await new HKSStudio.BrowserEngine().run(b);}catch(e){return {ok:false,error:e.message};}}',name)
    if expected['ok']:
     if value.get('result')!=expected['result']:(out/(name+'-mismatch.json')).write_text(json.dumps(value,indent=2));raise AssertionError('Exact native result mismatch: '+name)
     report['cases'][name]={'status':'EXACT','trades':len(value['result']['trades']),'result_hash':value['result']['result_hash'],'metrics':value['metrics']}
    else:
     assert not value['ok'] and expected['error'] in value['error'],(name,value,expected['error']);report['cases'][name]={'status':'EXPECTED REJECTION','error':expected['error']}
    checks.append('Frozen native/browser parity: '+name)
   # Every checkpoint of the hand-calculated partial case; actual separate Python workers.
   value=page.evaluate('''async()=>{const b=await HKSStudio.fixture('synthetic_hand_partial');b.checkpoint_every=1;const states=[];
    const full=await new HKSStudio.BrowserEngine().run(b,()=>{},{onCheckpoint:async s=>states.push(s)});
    const hashes=[];for(const resume of states){const x=await new HKSStudio.BrowserEngine().run(b,()=>{},{resume});hashes.push(x.result.result_hash);}
    return {count:states.length,hash:full.result.result_hash,hashes};}''')
   assert value['count']==4 and len(set(value['hashes']+[value['hash']]))==1,value
   report['all_partial_checkpoints']=value;checks.append('Fresh Python worker restore at ALL 4 partial/stop/open boundaries yields exact full result hash')
   stateful=page.evaluate("""async()=>{const b=await HKSStudio.fixture('synthetic_hand_partial');b.checkpoint_every=1;
    b.definition.code='from decimal import Decimal as D\\nWARMUP_BARS=2\\ncounter=0\\ndef on_bar(ctx):\\n global counter\\n counter+=1\\n ctx.state[\"n\"]=ctx.state.get(\"n\",0)+1\\n if ctx.position is None and ctx.state[\"n\"]==1:return ctx.enter(\"LONG\",stop_fraction=D(\".1\"))\\n if ctx.position is not None and counter==2:return ctx.manage(reduce_fraction=D(\".25\"))\\n return None\\n';
    const snapshots=[];const full=await new HKSStudio.BrowserEngine().run(b,()=>{},{onCheckpoint:async s=>snapshots.push(s)});
    const hashes=[];for(const resume of snapshots){const r=await new HKSStudio.BrowserEngine().run(b,()=>{},{resume});hashes.push(r.result.result_hash);}return {hash:full.result.result_hash,hashes};}""")
   assert all(x==stateful['hash'] for x in stateful['hashes']);checks.append('Actual worker checkpoints preserve Decimal ctx.state and mutable global counters across fresh interpreters')
   # Functional premium UI, not merely hidden API calls.
   page.select_option('#dataset','synthetic_hand_partial');expect(page.locator('#definition')).to_have_value(__import__('re').compile('reduce_fraction'))
   page.check('#trusted');page.click('#runButton');expect(page.locator('#jobStage')).to_contain_text('COMPLETE',timeout=30000)
   assert page.locator('#trades tbody tr').count()==2;expect(page.locator('#equityStat')).to_have_text('$1,017.50')
   page.locator('#trades tbody button').first.click();expect(page.locator('#tradeDialog')).to_be_visible();assert 'PYTHON_REDUCTION_NEXT_OPEN' in page.locator('#tradeDetail').inner_text();page.click('#closeDetail')
   with page.expect_download() as d:page.click('#exportTrades')
   d.value.save_as(out/'ui-trades.csv');assert len(list(csv.DictReader(io.StringIO((out/'ui-trades.csv').read_text()))))==2
   checks.append('Actual premium Python editor → Run → exact $1,017.50 hand ledger → detail dialog → full CSV')
   first=page.evaluate('(HKSStudio.result.result.result_hash)')
   page.fill('#definition','this is invalid python !!!');page.click('#validate');expect(page.locator('#message')).to_contain_text('syntax error',timeout=20000)
   page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio');expect(page.locator('#definition')).to_have_value(__import__('re').compile('reduce_fraction'));assert page.evaluate('HKSStudio.result.result.result_hash')==first
   checks.append('Invalid pasted draft does not replace last successfully tested strategy/settings/report across reload')
   report['cache_cold']=page.evaluate('async()=>await HKSStudio.cacheAll()');count=sum('/candles/' in u for u in urls)
   report['cache_warm']=page.evaluate('async()=>await HKSStudio.cacheAll()');assert report['cache_cold']=={'downloaded':20,'reused':0} and report['cache_warm']=={'downloaded':0,'reused':20};assert sum('/candles/' in u for u in urls)==count
   checks.append('All 864,000 genuine monthly candles cached in OPFS; warm reuse downloads ZERO candle chunks')
   # Genuine chronological 20-symbol replay composed from monthly cache.
   result=page.evaluate('''async()=>{const b=await HKSStudio.fixture('genuine_20coin_6hours');const request={source:'binance-november-2025',definition:b.definition,symbols:b.manifest.files.map(f=>f.symbol).sort(),config:b.config,interval:'1m'};
    const spec=await HKSStudio.saveVersion(b.definition),start=performance.now(),composed=await HKSStudio.compose(request,spec);let checkpoints=0;
    const answer=await new HKSStudio.BrowserEngine().run(composed,()=>{},{onCheckpoint:async s=>{checkpoints++;}});
    return {metrics:answer.metrics,trades:answer.result.trades.length,accounts:answer.result.accounts,reconciliation:answer.result.reconciliation,wallMs:performance.now()-start,checkpoints};}''')
   assert len(result['accounts'])==1 and result['trades']>0 and result['checkpoints']>0
   assert all(abs(float(v[k]))<1e-20 for v in result['reconciliation'].values() for k in ('cash_residual','equity_residual'))
   report['warm_cache_20coin_6h']=result;assert sum('/candles/' in u for u in urls)==count
   checks.append('20 genuine symbols compose from month cache, run globally chronological Shared wallet, reconcile, zero redownload')
   # Actual UI interrupted in mid-run after durable checkpoint, then reload and resume.
   page.select_option('#dataset','genuine_2coin_1day');page.check('#diagnostic');page.check('#trusted')
   page.evaluate('''()=>{window._checkpointSeen=false;window.addEventListener('hks-checkpoint',()=>{window._checkpointSeen=true;document.getElementById('cancel').click();},{once:true});}''')
   page.click('#runButton');page.wait_for_function('()=>window._checkpointSeen',timeout=30000);expect(page.locator('#jobStage')).to_contain_text('CANCELLED',timeout=15000)
   interrupted=page.evaluate('HKSStudio.job.id');saved=page.evaluate('HKSStudio.job.checkpoint');assert saved and saved['bytes']>0
   page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio');page.evaluate('async id=>await HKSStudio.showJob(id)',interrupted)
   page.check('#trusted');page.check('#diagnostic');page.click('#retry');expect(page.locator('#jobStage')).to_contain_text('COMPLETE',timeout=90000)
   resumed=page.evaluate('HKSStudio.result');assert resumed['result']==baseline['genuine_2coin_1day']['result'];assert resumed['metrics']['resumed']
   report['genuine_resume']={'checkpoint':saved,'metrics':resumed['metrics'],'result_hash':resumed['result']['result_hash']};checks.append('Cancel after durable genuine-data checkpoint → reload → UI Resume → exact frozen one-day result')
   # Pagination and filtering use the actual larger completed journal.
   assert page.locator('#trades tbody tr').count()==25;page.click('#next');expect(page.locator('#pageInfo')).to_contain_text('Page 2');page.fill('#search','BTCUSDT');expect(page.locator('#pageInfo')).to_contain_text('Page 1');assert all('BTCUSDT' in x for x in page.locator('#trades tbody tr').all_text_contents())
   checks.append('Actual journal pagination, symbol filtering and page reset')
   # Cross-tab exclusion: one browser-profile runner lock, no duplicate resume.
   blocked=page.evaluate('''async()=>{return await navigator.locks.request('hks-pro-trader-runner',async()=>{const p=await navigator.locks.request('hks-pro-trader-runner',{ifAvailable:true},lock=>!lock);return p;});}''');assert blocked;checks.append('Web Locks prevents a second tab from executing the same device runner concurrently')
   # Corrupted checkpoints are never restored.
   rejected=page.evaluate('''async id=>{const j=await HKSStudio.store.get('jobs',id),h=await HKSStudio.store.opfs.getFileHandle(j.checkpoint.name);const original=await (await h.getFile()).arrayBuffer();let w=await h.createWritable();await w.write(new Uint8Array([1,2,3]));await w.close();let error;try{await HKSStudio.store.checkpoint(j);}catch(e){error=e.message;}w=await h.createWritable();await w.write(original);await w.close();return error;}''',interrupted)
   assert 'SHA-256 mismatch' in rejected;checks.append('Damaged OPFS checkpoint is rejected before any restoration; original disposable checkpoint restored')
   page.screenshot(path=str(out/'desktop.png'),full_page=True)
   # Browser strategy origin/network/storage denial (not a hard resource sandbox).
   frame={'symbol':'BTCUSDT','bars':[{'symbol':'BTCUSDT','open_ms':1761955200000+i*60000,'interval_ms':60000,'open':'100','high':'101','low':'99','close':'100','volume':'10'} for i in range(2)],'position':None,'account':{'equity':'1000','cash':'1000','reserved_capital':'0','reserved_risk':'0'}}
   code='''import js,os\nWARMUP_BARS=2\ndef on_bar(ctx):\n a={'origin':str(js.origin),'secret':('DATABASE_URL' in os.environ)}\n try:js.indexedDB.open('hks-pro-trader-static-v1');a['idb']=True\n except Exception:a['idb']=False\n try:\n  x=js.XMLHttpRequest.new();x.open('GET','https://example.invalid/',False);x.send();a['network']=True\n except Exception:a['network']=False\n return a\n'''
   sec=page.evaluate('''async({code,frame})=>{const s=new HKSStudio.SandboxClient();try{await s.init(code);return JSON.parse(await s.step(frame));}finally{s.stop();}}''',{'code':code,'frame':frame})
   assert sec['decision']=={'origin':'null','secret':False,'idb':False,'network':False};report['opaque_origin_check']=sec;checks.append('Actual strategy worker stays opaque-origin, denies network and app storage, receives no server secret')
   # Entire browser process closes; no alive worker can fake restart persistence.
   last=page.evaluate('HKSStudio.result.result.result_hash');context.close()
   context=p.chromium.launch_persistent_context(str(profile),executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,viewport={'width':1440,'height':1000},env=env,**({'proxy':{'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}} if args.origin else {}))
   page=context.pages[0];page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio');assert page.evaluate('HKSStudio.result.result.result_hash')==last
   assert len(page.evaluate('async()=>await HKSStudio.store.all("datasets")'))>=20
   checks.append('Fresh browser process restores genuine report, Python, settings and verified OPFS candle inventory')
   context.close()
   mobile=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env)
   ctx=mobile.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,device_scale_factor=2,accept_downloads=True)
   page=ctx.new_page();page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio')
   page.select_option('#dataset','synthetic_hand_partial');page.check('#trusted');page.locator('#runButton').tap();expect(page.locator('#jobStage')).to_contain_text('COMPLETE',timeout=30000)
   expect(page.locator('#equityStat')).to_have_text('$1,017.50');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   page.locator('#trades tbody button').first.tap();expect(page.locator('#tradeDialog')).to_be_visible();page.locator('#closeDetail').tap()
   with page.expect_download() as d:page.locator('#exportTrades').tap()
   d.value.save_as(out/'mobile-trades.csv');page.screenshot(path=str(out/'mobile.png'),full_page=True)
   page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio');expect(page.locator('#equityStat')).to_have_text('$1,017.50')
   checks.append('Actual mobile emulation: touch Run, real Python partials, responsive width, details, CSV and reload persistence')
   report['mobile_browser']='Chromium Android viewport/touch emulation only';ctx.close();mobile.close()
   report['status']='PASS';print('PASS',len(checks),'checks',flush=True)
 except BaseException as e:
  report['status']='FAIL';report['error']=type(e).__name__+': '+str(e);raise
 finally:
  if server and server.poll() is None:server.terminate();server.wait(timeout=10)
  log.close();
  if 'stop' in locals():stop.set();monitor.join(timeout=2);report['whole_browser_memory']=peak
  report['console']=console;report['page_errors']=errors;report['network_requests']=len(urls);report['passed_checks']=len(checks)
  (out/'BROWSER_RESULTS.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
