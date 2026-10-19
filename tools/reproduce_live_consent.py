"""Read-only deployed-site reproduction in a new disposable browser profile."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://hks-pro-trader-browser-staging.pages.dev'


def main():
    out = ROOT / 'review/live-before'
    out.mkdir(exist_ok=False)
    record = {'origin': ORIGIN, 'published_changes': False, 'events': [], 'checks': []}
    with tempfile.TemporaryDirectory(prefix='hks-consent-live-', dir='/tmp') as temp, sync_playwright() as p:
        env = {k: v for k, v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE', k, re.I)}
        env.update(XDG_CONFIG_HOME=temp, XDG_CACHE_HOME=temp)
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    chromium_sandbox=True,
                                    proxy={'server': os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}, env=env)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda e: record['events'].append({'pageerror': str(e)}))
        try:
            response = page.goto(ORIGIN, wait_until='networkidle', timeout=60000)
            record['http_status'] = response.status
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            record['sourceHash'] = page.evaluate('HKSStudio.sourceHash')
            record['isolated'] = page.evaluate('crossOriginIsolated')
            record['assets'] = {}
            for name in ['app.js', 'client.js', 'financial-worker.js', 'kernel.json', 'sw.js']:
                raw = page.evaluate('async n=>await (await fetch(n)).text()', name)
                (out / name).write_text(raw)
                record['assets'][name] = {'sha256': hashlib.sha256(raw.encode()).hexdigest(), 'bytes': len(raw.encode())}
            record['initial'] = page.evaluate('''()=>({dataset:document.getElementById('dataset').value,
              start:document.getElementById('start').value,end:document.getElementById('end').value,
              diagnostic:document.getElementById('diagnostic').checked,mode:document.getElementById('mode').value})''')
            # The normal UI monthly-data path, not a prebuilt fixture or bypass.
            page.select_option('#dataset', 'binance-november-2025')
            page.fill('#start', '2025-11-02T00:00')
            page.fill('#end', '2025-11-05T00:00')
            page.select_option('#mode', 'shared')
            page.check('#diagnostic')
            page.check('#trusted')
            record['before_click'] = page.evaluate('''()=>({dataset:document.getElementById('dataset').value,
              diagnostic:document.getElementById('diagnostic').checked,mode:document.getElementById('mode').value,
              code:document.getElementById('definition').value})''')
            started = time.monotonic()
            page.click('#runButton')
            page.wait_for_function("()=>/^(COMPLETE|FAILED|REJECTED|CANCELLED)/.test(document.getElementById('jobStage').textContent)", timeout=180000)
            record['elapsed_seconds'] = time.monotonic() - started
            record['job_stage'] = page.locator('#jobStage').inner_text()
            record['message'] = page.locator('#message').inner_text()
            record['job'] = page.evaluate('HKSStudio.job')
            record['checked_after'] = page.is_checked('#diagnostic')
            record['result_hash'] = page.evaluate('HKSStudio.result?.result?.result_hash || null')
            page.screenshot(path=str(out / 'live-before.png'), full_page=True)
            print(json.dumps({k: v for k, v in record.items() if k not in ('assets', 'before_click', 'job')}, indent=2), flush=True)
            print('SAVED_CONFIG', json.dumps((record.get('job') or {}).get('request', {}).get('config')), flush=True)
        finally:
            (out / 'REPRODUCTION.json').write_text(json.dumps(record, indent=2))
            context.close()
            browser.close()


if __name__ == '__main__':
    main()
