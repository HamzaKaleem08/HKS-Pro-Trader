"""Read-only published runtime inventory. No strategy execution on the host."""
import argparse,contextlib,hashlib,json,os,re,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'deployment/smc-context-v2-20261019/live-before')
OUT=ap.parse_args().output
OUT.mkdir(exist_ok=False)
record={'page_errors':[]}
try:
    with tempfile.TemporaryDirectory(prefix='hks-context-inspection-') as temp,sync_playwright() as p,contextlib.ExitStack() as cleanup:
        env={k:v for k,v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE',k,re.I)}
        env.update(XDG_CONFIG_HOME=temp,XDG_CACHE_HOME=temp)
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,chromium_sandbox=True,
            env=env,proxy={'server':os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']},timeout=45000)
        cleanup.callback(browser.close)
        context=browser.new_context(viewport={'width':1440,'height':1000});cleanup.callback(context.close)
        page=context.new_page();page.on('pageerror',lambda e:record['page_errors'].append(str(e)))
        response=page.goto('https://hks-pro-trader-browser-staging.pages.dev/',wait_until='networkidle',timeout=60000)
        page.wait_for_function('()=>!!window.HKSStudio',timeout=60000)
        record['http_status']=response.status;record['sourceHash']=page.evaluate('HKSStudio.sourceHash')
        record['sw']=page.evaluate('''async()=>({controller:navigator.serviceWorker.controller?.scriptURL,
            caches:await caches.keys(),registrations:(await navigator.serviceWorker.getRegistrations()).map(r=>({active:r.active?.scriptURL,waiting:r.waiting?.scriptURL,installing:r.installing?.scriptURL}))})''')
        record['assets']={}
        for name in ['app.js','client.js','strategy-worker.js','kernel.json','sw.js','boot.js']:
            value=page.evaluate('''async name=>{const r=await fetch(name,{cache:'no-store'});return {status:r.status,text:await r.text(),headers:Object.fromEntries(r.headers)};}''',name)
            (OUT/name).write_text(value.pop('text'));value['sha256']=hashlib.sha256((OUT/name).read_bytes()).hexdigest();record['assets'][name]=value
        record['runtime']=page.evaluate('''async code=>{window.contextProbe=new HKSStudio.SandboxClient();const info=await contextProbe.init(code);contextProbe.stop();return info;}''',(ROOT/'examples/hks_legacy_smc_reverse.py').read_text())
        record['passed']=True;print(json.dumps(record,indent=2),flush=True)
finally:
    (OUT/'INSPECTION.json').write_text(json.dumps(record,indent=2))
