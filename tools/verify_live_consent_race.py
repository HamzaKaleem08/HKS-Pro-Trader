"""Reproduce the actual late-checkbox/saved-config mismatch on deployed assets.

Only uses a new browser profile. No published assets, owner settings or data change.
"""
import gzip
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
    out = ROOT / 'review/live-race'
    out.mkdir(exist_ok=False)
    record = {'origin': ORIGIN, 'published_changes': False, 'checks': [], 'page_errors': []}
    with tempfile.TemporaryDirectory(prefix='hks-consent-race-', dir='/tmp') as temp, sync_playwright() as p:
        env = {k: v for k, v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE', k, re.I)}
        env.update(XDG_CONFIG_HOME=temp, XDG_CACHE_HOME=temp)
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                    chromium_sandbox=True,
                                    proxy={'server': os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}, env=env)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda e: record['page_errors'].append(str(e)))
        try:
            record['http_status'] = page.goto(ORIGIN, wait_until='networkidle').status
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            record['sourceHash'] = page.evaluate('HKSStudio.sourceHash')
            page.fill('#start', '2025-11-02T00:00')
            page.fill('#end', '2025-11-05T00:00')
            page.select_option('#mode', 'individual')
            page.check('#trusted')
            page.uncheck('#diagnostic')
            # This input edit happens AFTER settings() takes the request snapshot,
            # while async metadata validation/candle preparation is still running.
            page.click('#runButton')
            page.wait_for_function("()=>document.getElementById('runButton').disabled")
            page.check('#diagnostic')
            expect(page.locator('#jobStage')).to_contain_text('allow_uncertified_futures=true required', timeout=60000)
            record['race'] = {'visible_checked': page.is_checked('#diagnostic'),
                              'job_stage': page.locator('#jobStage').inner_text(),
                              'saved_config': page.evaluate('HKSStudio.job.request.config'),
                              'source_hash': page.evaluate('HKSStudio.job.sourceHash')}
            assert record['race']['visible_checked'] is True
            assert record['race']['saved_config']['allow_uncertified_futures'] is False
            record['checks'].append('Exact deployed error reproduced: visible checkbox true, captured job config false after late edit')
            page.screenshot(path=str(out / 'checked-but-captured-false.png'), full_page=True)
            print('REPRODUCED', json.dumps(record['race']), flush=True)
            # With consent present BEFORE the request capture, the same live
            # Python worker accepts it. Keep all parameters and data unchanged.
            start = time.monotonic()
            page.click('#runButton')
            expect(page.locator('#jobStage')).to_contain_text('COMPLETE', timeout=180000)
            answer = page.evaluate('HKSStudio.result')
            (out / 'live-individual-3day-answer.json.gz').write_bytes(gzip.compress(json.dumps(answer).encode(), mtime=0))
            result = answer['result']
            assert result['config']['allow_uncertified_futures'] is True
            assert set(result['accounts']) == {'BTCUSDT', 'ETHUSDT'}
            assert result['trades']
            record['individual_3day'] = {'seconds': time.monotonic() - start,
                'hash': result['result_hash'], 'trades': len(result['trades']),
                'accounts': result['accounts'], 'reconciliation': result['reconciliation'], 'metrics': answer['metrics']}
            record['checks'].append('Live three-day Individual genuine Futures run succeeds when consent captured true')
            with page.expect_download() as d:
                page.click('#exportTrades')
            d.value.save_as(out / 'live-individual-3day-trades.csv')
            page.locator('#trades tbody button').first.click()
            expect(page.locator('#tradeDialog')).to_be_visible()
            page.click('#closeDetail')
            page.reload(wait_until='networkidle')
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            assert page.evaluate('HKSStudio.result.result.result_hash') == result['result_hash']
            assert page.is_checked('#diagnostic')
            record['checks'].append('Live journal details, CSV export and reload persistence retain the actual Individual report and consent')
            # Export one original, source-bound checkpoint from this disposable
            # profile, for candidate compatibility testing without owner data.
            page.check('#trusted')
            page.evaluate("""()=>{window._savedCheckpoint=false;addEventListener('hks-checkpoint',()=>{
                window._savedCheckpoint=true;document.getElementById('cancel').click();},{once:true});}""")
            page.click('#runButton')
            expect(page.locator('#jobStage')).to_contain_text('CANCELLED', timeout=60000)
            checkpoint = page.evaluate('''async()=>({job:HKSStudio.job,
                snapshot:await HKSStudio.store.checkpoint(HKSStudio.job)})''')
            (out / 'original-deployment-checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(checkpoint).encode(), mtime=0))
            record['original_checkpoint'] = {'job': checkpoint['job']['id'],
                'identity': checkpoint['job']['identity'], 'sourceHash': checkpoint['job']['sourceHash'],
                'next_ms': checkpoint['snapshot']['finance']['next_ms']}
            record['checks'].append('Original deployment checkpoint retained for byte-exact candidate resume compatibility test')
            record['status'] = 'PASS'
            print(json.dumps(record, indent=2), flush=True)
        finally:
            (out / 'LIVE_RACE_AND_INDIVIDUAL.json').write_text(json.dumps(record, indent=2))
            context.close()
            browser.close()


if __name__ == '__main__':
    main()
