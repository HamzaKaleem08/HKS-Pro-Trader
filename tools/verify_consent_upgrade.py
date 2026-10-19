"""Local old-to-candidate service-worker upgrade; no user data or deployment."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    out = ap.parse_args().output
    out.mkdir(exist_ok=False)
    baseline = Path(json.loads((ROOT / 'review/BASELINE_SOURCE_INVENTORY.json').read_text())['source'])
    spec = importlib.util.spec_from_file_location('candidate_headers', ROOT / 'serve.py')
    mirror = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mirror)
    current = {'web': baseline / 'web'}
    record = {'checks': [], 'published_changes': False, 'page_errors': []}
    record['server_requests'] = []

    class Handler(mirror.Handler):
        def __init__(self, *a, **kw):
            SimpleHTTPRequestHandler.__init__(self, *a, directory=str(current['web']), **kw)

        def do_GET(self):
            if self.path in ('/app.js', '/sw.js', '/replay-consent.js'):
                record['server_requests'].append({'path': self.path, 'root': str(self.directory),
                    'if_modified_since': self.headers.get('If-Modified-Since'),
                    'cache_control': self.headers.get('Cache-Control')})
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with tempfile.TemporaryDirectory(prefix='hks-sw-consent-', dir='/tmp') as temp, sync_playwright() as p:
            env = {k: v for k, v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE', k, re.I)}
            env.update(XDG_CONFIG_HOME=temp, XDG_CACHE_HOME=temp)
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                        chromium_sandbox=True, env=env)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.on('pageerror', lambda e: record['page_errors'].append(str(e)))
            # A retained prior cache is realistic browser state, not a network or
            # Python stub. Its authentic original app must NEVER override the
            # atomically installed current build after the upgrade.
            page.goto(origin+'/style.css', wait_until='networkidle')
            page.evaluate('''async source=>{const c=await caches.open('hks-browser-proof-retained-legacy');await c.put(new URL('/app.js',location.origin),new Response(source,{headers:{'Content-Type':'text/javascript'}}));}''',(baseline/'web/app.js').read_text())
            page.goto(origin, wait_until='networkidle')
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            page.select_option('#dataset', 'synthetic_hand_partial')
            page.check('#trusted')
            page.click('#runButton')
            expect(page.locator('#jobStage')).to_contain_text('COMPLETE', timeout=30000)
            old = page.evaluate('''async()=>{await navigator.serviceWorker.ready;
                await HKSStudio.store.put('settings',{id:'upgrade-marker',value:'preserve'});
                return {hash:HKSStudio.result.result.result_hash,sourceHash:HKSStudio.sourceHash,
                datasets:await HKSStudio.store.all('datasets'),jobs:await HKSStudio.store.all('jobs'),
                settings:await HKSStudio.store.all('settings'),versions:await HKSStudio.store.all('versions')};}''')
            page.wait_for_function('()=>!!navigator.serviceWorker.controller')
            current['web'] = ROOT / 'web'
            # Exercise the actual service worker update, not a cache purge or
            # an injected replacement app. Only this loopback server changes.
            page.evaluate('''async()=>{window._updatedController=false;
                navigator.serviceWorker.addEventListener('controllerchange',()=>{window._updatedController=true;},{once:true});
                const r=await navigator.serviceWorker.getRegistration();await r.update();}''')
            build = json.loads((ROOT / 'evidence/STATIC_BUILD.json').read_text())['build_id']
            # Poll awaited evaluate results. An async predicate returning a
            # Promise is truthy to wait_for_function before it has resolved.
            deadline = time.monotonic() + 45
            while not page.evaluate('''async expected=>{
                const r=await navigator.serviceWorker.getRegistration(),keys=await caches.keys();
                return r.active?.state==='activated'&&window._updatedController&&
                keys.filter(k=>k.startsWith('hks-premium-static-')).every(k=>k==='hks-premium-static-'+expected)&&
                keys.includes('hks-premium-static-'+expected);
            }''', build):
                if time.monotonic() > deadline:
                    raise TimeoutError('New service worker did not fully activate')
                page.wait_for_timeout(100)
            page.reload(wait_until='networkidle')
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            after = page.evaluate('''async()=>({hash:HKSStudio.result.result.result_hash,sourceHash:HKSStudio.sourceHash,
                datasets:await HKSStudio.store.all('datasets'),jobs:await HKSStudio.store.all('jobs'),
                settings:await HKSStudio.store.all('settings'),versions:await HKSStudio.store.all('versions')})''')
            assert old == after
            assert page.evaluate("async()=>!!await caches.match('/replay-consent.js')")
            record['checks'].append('Actual original-to-candidate service-worker upgrade caches consent module without changing IDB/OPFS reports, jobs, versions, settings or source identity')
            record['asset_debug'] = page.evaluate('''async()=>({keys:await caches.keys(),
                perCache:await Promise.all((await caches.keys()).map(async key=>{const hit=await (await caches.open(key)).match('/app.js');return {key,hasFix:!!hit&&(await hit.text()).includes('assertReplayConsent')};})),
                registration:await (async()=>{const r=await navigator.serviceWorker.getRegistration();return {active:r.active?.state,waiting:r.waiting?.state,installing:r.installing?.state};})(),
                cachedHasFix:(await (await caches.match('/app.js')).text()).includes('assertReplayConsent'),
                fetchedHasFix:(await (await fetch('app.js')).text()).includes('assertReplayConsent')})''')
            assert record['asset_debug']['fetchedHasFix'], record['asset_debug']
            assert 'hks-browser-proof-retained-legacy' in record['asset_debug']['keys']
            record['checks'].append('Retained authentic legacy cache is preserved but cannot override current app code')
            record['checks'].append('Updated page actually loads new consent preflight code')
            context.set_offline(True)
            page.reload(wait_until='networkidle')
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            assert page.evaluate('HKSStudio.result.result.result_hash') == old['hash']
            record['checks'].append('Offline reload loads the new module and preserves last completed report')
            context.set_offline(False)
            page.check('#diagnostic')
            page.wait_for_function("async()=> (await HKSStudio.store.get('settings','diagnostic-futures-consent-v1'))?.accepted===true")
            page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=45000)
            assert page.is_checked('#diagnostic')
            page.uncheck('#diagnostic')
            page.wait_for_function("async()=> (await HKSStudio.store.get('settings','diagnostic-futures-consent-v1'))?.accepted===false")
            page.reload(wait_until='networkidle');page.wait_for_function('()=>!!window.HKSStudio',timeout=45000)
            assert not page.is_checked('#diagnostic')
            record['checks'].append('Explicit true and false consent persist before any Futures result and survive reload')
            page.select_option('#dataset', 'genuine_2coin_1day')
            page.wait_for_function("()=>document.getElementById('datasetInfo').textContent.includes('fixture')")
            assert not page.is_checked('#diagnostic')
            record['checks'].append('Futures source metadata never auto-acknowledges consent')
            page.select_option('#dataset', 'binance-november-2025')
            page.uncheck('#diagnostic')
            page.check('#trusted')
            page.click('#runButton')
            expect(page.locator('#message')).to_contain_text('Check diagnostic Futures consent')
            record['checks'].append('Upgraded app rejects missing Futures consent before Python starts')
            record['sourceHash'] = old['sourceHash']
            record['build_id'] = build
            record['status'] = 'PASS'
            record['passed_checks'] = len(record['checks'])
            page.screenshot(path=str(out / 'upgraded-consent.png'), full_page=True)
            print('PASS', record['passed_checks'], 'service-worker upgrade checks', flush=True)
            context.close()
            browser.close()
    except BaseException as e:
        record.update(status='FAIL', error=type(e).__name__ + ': ' + str(e))
        raise
    finally:
        server.shutdown()
        server.server_close()
        (out / 'UPGRADE_RESULTS.json').write_text(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
