"""Actual local old-build -> candidate -> rollback storage/identity regression."""
import argparse,contextlib,hashlib,importlib.util,json,os,re,threading,time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline-root',type=Path,required=True)
 ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
 out=args.output;out.mkdir(parents=True,exist_ok=False);record={'local_only':True,'owner_storage_accessed':False,'external_network_requests':False}
 try:
  excluded=json.loads((ROOT/'HISTORICAL_DATA_EXCLUSIONS.json').read_text())['excluded_files']
  for row in excluded:
   data=(args.data_root/row['path']).read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256']
  allow={r['path'] for r in excluded}
  with sync_playwright() as p,contextlib.ExitStack() as cleanup:
   spec=importlib.util.spec_from_file_location('upgrade_headers',ROOT/'serve.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=args.baseline_root
   class Handler(m.Handler):
    def do_GET(self):
     # Switching to an older immutable artifact can have an earlier filesystem
     # mtime. SimpleHTTPRequestHandler otherwise returns an incorrect 304 for
     # changed rollback bytes. Serve the selected artifact, while retaining all
     # original CSP/isolation and client SHA checks. No live server is changed.
     if 'If-Modified-Since' in self.headers:del self.headers['If-Modified-Since']
     return super().do_GET()
    def translate_path(self,path):
     rel='web/'+unquote(urlsplit(path).path).lstrip('/')
     return str(args.data_root/rel) if rel in allow else super().translate_path(path)
   server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();cleanup.callback(server.server_close);cleanup.callback(server.shutdown)
   env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
   env.update(XDG_CONFIG_HOME=str(out/'config'),XDG_CACHE_HOME=str(out/'cache'))
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env,timeout=45000);cleanup.callback(browser.close)
   context=browser.new_context(viewport={'width':1440,'height':1000});cleanup.callback(context.close);page=context.new_page()
   origin=f'http://127.0.0.1:{server.server_port}';page.goto(origin,wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
   old_hash=page.evaluate('HKSStudio.sourceHash');record['baseline_source_hash']=old_hash
   page.select_option('#dataset','synthetic_hand_partial');page.wait_for_function("()=>document.getElementById('definition').value.includes('reduce_fraction')")
   page.check('#trusted');page.click('#runButton');page.wait_for_function('()=>!HKSStudio.running&&HKSStudio.job?.status==="COMPLETE"',timeout=60000)
   original_report=page.evaluate('HKSStudio.result.result');original_job=page.evaluate('HKSStudio.job.id')
   req={'source':'binance-november-2025','definition':{'schema_version':1,'kind':'PYTHON_STRATEGY','name':'Exact OLD SMC Reverse','code':(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()},
    'symbols':['BTCUSDT','ETHUSDT'],'interval':'1m','config':{'start_ms':1764288000000,'end_ms':1764547200000,'mode':'individual',
    'initial_capital':'1000','fee_bps':'10','slippage_bps':'2','risk_fraction':'0.01','max_positions':3,'end_policy':'KEEP_OPEN','allow_uncertified_futures':True}}
   page.evaluate('r=>HKSStudio.applyRequest(r)',req);page.check('#diagnostic');page.check('#trusted')
   page.evaluate("()=>addEventListener('hks-checkpoint',()=>document.getElementById('cancel').click(),{once:true})")
   page.click('#runButton');page.wait_for_function('()=>!HKSStudio.running&&HKSStudio.job?.status==="CANCELLED"',timeout=90000)
   old_job=page.evaluate('HKSStudio.job');assert old_job['sourceHash']==old_hash and old_job['checkpoint']['next_ms']>req['config']['start_ms']
   datasets=page.evaluate("async()=> (await HKSStudio.store.all('datasets')).map(x=>[x.id,x.hash,x.bytes]).sort()")
   def switch(root):
    m.ROOT=root
    page.evaluate('async()=>{const r=await navigator.serviceWorker.getRegistration();if(r)await r.update();}')
    expected=re.search(r"const CACHE='([^']+)'",(root/'web/sw.js').read_text()).group(1)
    deadline=time.monotonic()+120
    while not page.evaluate('async key=>(await caches.keys()).includes(key)',expected):
     if time.monotonic()>deadline:raise TimeoutError('Local service-worker upgrade did not install')
     page.wait_for_timeout(100)
    page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
   switch(ROOT);new_hash=page.evaluate('HKSStudio.sourceHash');assert new_hash!=old_hash
   assert page.evaluate('HKSStudio.result.result.result_hash')==original_report['result_hash']
   page.evaluate('async id=>await HKSStudio.showJob(id)',old_job['id']);assert page.is_disabled('#retry')
   assert 'older runtime identity' in page.inner_text('#message')
   page.check('#trusted');page.check('#diagnostic')
   error=page.evaluate('async id=>{try{await HKSStudio.run(id);return null;}catch(e){return e.message;}}',old_job['id'])
   record['direct_resume_rejection']=error
   assert 'old checkpoint cannot resume' in error
   unchanged=page.evaluate('async id=>await HKSStudio.store.get("jobs",id)',old_job['id']);assert unchanged==old_job
   assert page.is_disabled('#retry')
   assert page.evaluate("async()=> (await HKSStudio.store.all('datasets')).map(x=>[x.id,x.hash,x.bytes]).sort()") == datasets
   record.update(candidate_source_hash=new_hash,old_runtime_rejected_before_strategy_restore=True,old_checkpoint_unchanged=True,
                 old_report_opens_after_upgrade=True,cache_and_reports_preserved=True,disabled_resume_has_explanation=True)
   switch(args.baseline_root);assert page.evaluate('HKSStudio.sourceHash')==old_hash
   page.evaluate('async id=>await HKSStudio.showJob(id)',old_job['id']);page.check('#trusted');page.check('#diagnostic');assert not page.is_disabled('#retry')
   page.evaluate("()=>{window.__firstResumedBar=null;const old=HKSStudio.SandboxClient.prototype.step;HKSStudio.SandboxClient.prototype.step=function(f,...args){if(window.__firstResumedBar===null){const x=typeof f==='string'?JSON.parse(f):f;window.__firstResumedBar=x.bars.at(-1).open_ms;}return old.call(this,f,...args);};addEventListener('hks-checkpoint',()=>document.getElementById('cancel').click(),{once:true});}")
   page.click('#retry');page.wait_for_function('()=>!HKSStudio.running&&HKSStudio.job?.status==="CANCELLED"&&window.__firstResumedBar!==null',timeout=90000)
   assert page.evaluate('__firstResumedBar')>=old_job['checkpoint']['next_ms']
   assert page.evaluate('HKSStudio.job.checkpoint.next_ms')>old_job['checkpoint']['next_ms']
   record.update(original_build_can_resume_its_old_checkpoint=True,rollback_no_callback_before_saved_cursor=True,
                 original_completed_report=original_job,legacy_checkpoint_cursor=old_job['checkpoint']['next_ms'],passed=True)
 except BaseException as e:record.update(passed=False,failure=repr(e));raise
 finally:(out/'UPGRADE_EVIDENCE.json').write_text(json.dumps(record,indent=2))
 print(json.dumps(record,indent=2),flush=True)

if __name__=='__main__':main()
