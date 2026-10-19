"""Actual offline entry/Context smoke check; no financial or strategy changes."""
import argparse,contextlib,importlib.util,json,os,re,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from verify_context_browser import wait_activated
from verify_smc_browser import synthetic_cases,check_decision

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
args.output.mkdir(parents=True,exist_ok=False);record={}
try:
 with tempfile.TemporaryDirectory(prefix='hks-offline-context-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
    spec=importlib.util.spec_from_file_location('offline_headers',ROOT/'serve.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    cleanup.callback(server.server_close);cleanup.callback(server.shutdown)
    origin=f'http://127.0.0.1:{server.server_port}'
    env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
    env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,env=env,timeout=45000);cleanup.callback(browser.close)
    context=browser.new_context();cleanup.callback(context.close);page=context.new_page()
    page.goto(origin+'/?sandbox=completed-context-v2',wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
    wait_activated(page,re.search(r"const CACHE='([^']+)'",(ROOT/'web/sw.js').read_text()).group(1))
    context.set_offline(True);page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
    record['versioned_entry_offline_reload']=True
    source=(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()
    info=page.evaluate('''async code=>{window.probe=new HKSStudio.SandboxClient();return await probe.init(code);}''',source)
    assert info['contextContract']=='HKS_BROWSER_COMPLETED_CONTEXT/2';record['offline_context_api']=info
    case=synthetic_cases()[0];answer=page.evaluate('async row=>JSON.parse(await probe.step(row))',case['frame']);check_decision(answer['decision'],case['expected'])
    page.evaluate('probe.stop()');record['offline_actual_callback']=True
    page.goto(origin+'/index?version=context-v2',wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
    record['extensionless_index_offline']=True;record['passed']=True;print(json.dumps(record,indent=2),flush=True)
except BaseException as e:record.update(passed=False,failure=repr(e));raise
finally:(args.output/'OFFLINE_EVIDENCE.json').write_text(json.dumps(record,indent=2))
