"""Real browser consent, 3-day replay, storage and legacy-checkpoint regression.

Uses only disposable profiles; never publishes or touches an owner's device data.
--capture-original retrieves a checkpoint from the existing HTTPS staging build.
Otherwise serves the candidate only on loopback. No simulated worker responses.
"""
import argparse
import csv
from decimal import Decimal as D, localcontext
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def save_gzip(path, value):
    raw = json.dumps(value, separators=(',', ':')).encode()
    path.write_bytes(gzip.compress(raw, mtime=0))
    return {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def reconcile(result):
    """Independent trade-level cost/PnL and account-equity checks with Decimal."""
    with localcontext() as ctx:
        ctx.prec = 50
        fee = D(result['config']['fee_bps']) / 10000
        tolerance = D('1e-20')
        for trade in result['trades']:
            q, entry, exit = (D(trade[k]) for k in ('quantity', 'entry_price', 'exit_price'))
            gross = (exit - entry) * q * (1 if trade['side'] == 'LONG' else -1)
            assert abs(gross - D(trade['gross_pnl'])) < tolerance
            assert abs((entry + exit) * q * fee - D(trade['fees'])) < tolerance
            assert abs(gross - D(trade['fees']) - D(trade['net_pnl'])) < tolerance
            assert abs(D(trade['gross_before_slippage']) - D(trade['slippage_cost']) - gross) < tolerance
        for name, account in result['accounts'].items():
            realized = sum((D(t['net_pnl']) for t in result['trades'] if t['account'] == name), D(0))
            positions = [p for p in result['open_positions'] if p['account'] == name]
            margin = sum((D(p['margin']) for p in positions), D(0))
            open_fees = sum((D(p['entry_fee']) for p in positions), D(0))
            unrealized = D(0)
            for position in positions:
                sign = 1 if position['side'] == 'LONG' else -1
                pnl = (D(position['mark_price']) - D(position['entry_price'])) * D(position['quantity']) * sign
                assert abs(pnl - D(position['unrealized_pnl'])) < tolerance
                unrealized += pnl
            expected_cash = D(account['initial_capital']) + realized - margin - open_fees
            expected_equity = D(account['initial_capital']) + realized + unrealized - open_fees
            assert abs(expected_cash - D(account['available_cash'])) < tolerance
            assert abs(expected_equity - D(account['ending_equity'])) < tolerance
            assert all(abs(D(result['reconciliation'][name][k])) < tolerance
                       for k in ('cash_residual', 'equity_residual'))
    return {'exit_segments_checked': len(result['trades']), 'accounts_checked': list(result['accounts']),
            'maximum_allowed_decimal_residual': str(tolerance)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--origin')
    ap.add_argument('--capture-original', action='store_true')
    ap.add_argument('--checkpoint', type=Path)
    ap.add_argument('--modes', nargs='+', choices=['shared', 'individual'], default=['shared', 'individual'])
    args = ap.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    record = {'checks': [], 'runs': {}, 'page_errors': [], 'published_changes': False,
              'physical_android_tested': False}
    server = None
    log = (out / 'SERVER.log').open('w')
    if args.origin:
        origin = args.origin
    else:
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        server = subprocess.Popen([sys.executable, str(ROOT / 'serve.py'), '--port', str(port)],
                                  stdout=log, stderr=log)
    record['origin'] = origin
    try:
        with tempfile.TemporaryDirectory(prefix='hks-consent-browser-', dir='/tmp') as temp, sync_playwright() as p:
            env = {k: v for k, v in os.environ.items() if not re.search('TOKEN|SECRET|PASSWORD|DATABASE|API_KEY|BACKUP|CLOUDFLARE', k, re.I)}
            env.update(XDG_CONFIG_HOME=temp, XDG_CACHE_HOME=temp)
            options = dict(executable_path='/usr/bin/chromium', headless=True,
                           chromium_sandbox=True, env=env)
            if args.origin:
                options['proxy'] = {'server': os.environ.get('HTTPS_PROXY') or os.environ['HTTP_PROXY']}
            context = p.chromium.launch_persistent_context(str(Path(temp) / 'profile'),
                viewport={'width': 1440, 'height': 1000}, accept_downloads=True, **options)
            page = context.pages[0]
            page.set_default_timeout(30000)
            urls = []
            page.on('request', lambda r: urls.append(r.url))
            page.on('pageerror', lambda e: record['page_errors'].append(str(e)))
            response = page.goto(origin, wait_until='networkidle', timeout=60000)
            assert response.status == 200
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            assert page.evaluate('crossOriginIsolated')
            record['sourceHash'] = page.evaluate('HKSStudio.sourceHash')
            record['checks'].append('Real sandboxed Chromium boot, COOP/COEP and Python runtime available')
            page.fill('#start', '2025-11-02T00:00')
            page.fill('#end', '2025-11-05T00:00')
            page.select_option('#mode', 'individual')
            page.check('#trusted')
            if args.capture_original:
                page.check('#diagnostic')
                page.evaluate("""()=>addEventListener('hks-checkpoint',()=>document.getElementById('cancel').click(),{once:true})""")
                page.click('#runButton')
                expect(page.locator('#jobStage')).to_contain_text('CANCELLED', timeout=60000)
                checkpoint = page.evaluate('''async()=>({job:HKSStudio.job,
                    snapshot:await HKSStudio.store.checkpoint(HKSStudio.job)})''')
                assert checkpoint['job']['request']['config']['allow_uncertified_futures'] is True
                record['checkpoint'] = save_gzip(out / 'original-checkpoint.json.gz', checkpoint)
                record['checks'].append('Actual original-deployment three-day job cancelled at verified durable checkpoint')
                record['status'] = 'PASS'
                print(json.dumps(record, indent=2), flush=True)
                context.close()
                return

            # Regression: no workers, versions, jobs or settings may be created
            # for a missing consent. Rechecking afterward starts a NEW request.
            workers = []
            page.on('worker', lambda w: workers.append(w.url))
            before = page.evaluate('async()=>({jobs:await HKSStudio.store.all("jobs"),versions:await HKSStudio.store.all("versions")})')
            page.uncheck('#diagnostic')
            page.click('#runButton')
            expect(page.locator('#message')).to_contain_text('Check diagnostic Futures consent before starting or resuming')
            after = page.evaluate('async()=>({jobs:await HKSStudio.store.all("jobs"),versions:await HKSStudio.store.all("versions")})')
            assert after == before and not workers
            record['checks'].append('Unchecked consent rejected before worker boot or job/version writes; late-edit failure path removed')
            page.screenshot(path=str(out / 'early-consent-validation.png'), full_page=True)

            expected_hashes = {
                'shared': json.loads((ROOT / 'review/live-before/REPRODUCTION.json').read_text())['result_hash'],
                'individual': json.loads((ROOT / 'review/live-race/LIVE_RACE_AND_INDIVIDUAL.json').read_text())['individual_3day']['hash']}
            for mode in args.modes:
                page.select_option('#mode', mode)
                page.check('#diagnostic')
                started = time.monotonic()
                page.click('#runButton')
                expect(page.locator('#diagnostic')).to_be_disabled()
                expect(page.locator('#diagnostic')).to_be_checked()
                # A prior completed report can still say COMPLETE during async
                # request validation. Wait for THIS run, not the old label.
                page.wait_for_function('mode=>!HKSStudio.running&&HKSStudio.job?.status==="COMPLETE"&&HKSStudio.result?.result?.config.mode===mode', arg=mode, timeout=180000)
                expect(page.locator('#jobStage')).to_contain_text('COMPLETE', timeout=180000)
                answer = page.evaluate('HKSStudio.result')
                result = answer['result']
                assert result['result_hash'] == expected_hashes[mode]
                assert result['config']['allow_uncertified_futures'] is True
                assert result['config']['end_ms'] - result['config']['start_ms'] == 3 * 86400000
                assert set(result['accounts']) == ({'SHARED'} if mode == 'shared' else {'BTCUSDT', 'ETHUSDT'})
                assert result['trades']
                record['runs'][mode] = {'seconds': time.monotonic() - started, 'result_hash': result['result_hash'],
                    'trades': len(result['trades']), 'accounts': result['accounts'], 'metrics': answer['metrics'],
                    'independent_checks': reconcile(result), 'report': save_gzip(out / f'{mode}-3day-answer.json.gz', answer)}
                with page.expect_download() as d:
                    page.click('#exportTrades')
                d.value.save_as(out / f'{mode}-trades.csv')
                assert len(list(csv.DictReader(io.StringIO((out / f'{mode}-trades.csv').read_text())))) == len(result['trades'])
                page.locator('#trades tbody button').first.click()
                expect(page.locator('#tradeDialog')).to_be_visible()
                assert 'net_pnl' in page.locator('#tradeDetail').inner_text()
                page.click('#closeDetail')
                page.click('#next')
                expect(page.locator('#pageInfo')).to_contain_text('Page 2')
                page.fill('#search', 'BTCUSDT')
                expect(page.locator('#pageInfo')).to_contain_text('Page 1')
                assert all('BTCUSDT' in row for row in page.locator('#trades tbody tr').all_text_contents())
                page.fill('#search', '')
                page.reload(wait_until='networkidle')
                page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
                assert page.evaluate('HKSStudio.result.result.result_hash') == result['result_hash']
                assert page.is_checked('#diagnostic')
                record['checks'].append(f'{mode}: actual 3-day Python run, exact published financial hash, costs, journal/details/CSV and reload persistence')
                page.check('#trusted')
                print('THREE_DAY_PASS', mode, result['result_hash'], len(result['trades']), flush=True)

            # Import a REAL original-deployment checkpoint into this disposable
            # test profile. No owner checkpoint/settings are read or changed.
            legacy = json.loads(gzip.decompress(args.checkpoint.read_bytes()))
            assert legacy['job']['sourceHash'] == record['sourceHash']
            page.evaluate('''async saved=>{await HKSStudio.store.saveCheckpoint(saved.job,saved.snapshot);
                await HKSStudio.showJob(saved.job.id);}''', legacy)
            checkpoint_hash = page.evaluate('HKSStudio.job.checkpoint.hash')
            page.uncheck('#diagnostic')
            workers_before = len(workers)
            page.click('#retry')
            expect(page.locator('#message')).to_contain_text('Check diagnostic Futures consent')
            assert page.evaluate('HKSStudio.job.checkpoint.hash') == checkpoint_hash
            assert len(workers) == workers_before
            record['checks'].append('Resume requires current consent and leaves original saved checkpoint unmodified on refusal')

            # Deliberately malformed disposable job: current checkbox true must
            # never silently rewrite absent/false saved consent.
            bad = dict(legacy['job'], id='disposable-bad-consent')
            bad['request'] = json.loads(json.dumps(bad['request']))
            bad['request']['config']['allow_uncertified_futures'] = False
            page.evaluate('''async j=>{await HKSStudio.store.put('jobs',j);await HKSStudio.showJob(j.id);}''', bad)
            page.check('#diagnostic')
            page.click('#retry')
            expect(page.locator('#message')).to_contain_text('saved checkpoint settings cannot be changed')
            assert page.evaluate("async()=> (await HKSStudio.store.get('jobs','disposable-bad-consent')).request.config.allow_uncertified_futures") is False
            record['checks'].append('Checked UI cannot promote false consent in a malformed saved job')

            page.evaluate('async id=>await HKSStudio.showJob(id)', legacy['job']['id'])
            downloads_before = sum('/candles/' in url for url in urls)
            page.check('#diagnostic')
            page.check('#trusted')
            page.click('#retry')
            expect(page.locator('#diagnostic')).to_be_disabled()
            page.wait_for_function('()=>!HKSStudio.running&&HKSStudio.job?.status==="COMPLETE"&&HKSStudio.result?.metrics.resumed', timeout=180000)
            expect(page.locator('#jobStage')).to_contain_text('COMPLETE', timeout=180000)
            answer = page.evaluate('HKSStudio.result')
            assert answer['metrics']['resumed']
            assert answer['result']['result_hash'] == expected_hashes['individual']
            assert sum('/candles/' in url for url in urls) == downloads_before
            record['original_checkpoint_resume'] = {'hash': answer['result']['result_hash'],
                'metrics': answer['metrics'], 'independent_checks': reconcile(answer['result'])}
            record['checks'].append('Original deployed checkpoint resumes under candidate with exact full 3-day result and ZERO candle redownload')

            # Entire browser process exits: IndexedDB/OPFS, not surviving memory.
            context.close()
            context = p.chromium.launch_persistent_context(str(Path(temp) / 'profile'),
                viewport={'width': 1440, 'height': 1000}, accept_downloads=True, **options)
            page = context.pages[0]
            page.goto(origin, wait_until='networkidle')
            page.wait_for_function('()=>!!window.HKSStudio', timeout=45000)
            assert page.evaluate('HKSStudio.result.result.result_hash') == expected_hashes['individual']
            assert page.is_checked('#diagnostic')
            assert page.evaluate('HKSStudio.job.request.config.allow_uncertified_futures') is True
            record['checks'].append('Fresh browser process restores report, saved strategy/settings, cache and explicit consent')
            page.screenshot(path=str(out / 'completed-desktop.png'), full_page=True)
            record['status'] = 'PASS'
            record['passed_checks'] = len(record['checks'])
            print('PASS', record['passed_checks'], 'browser workflow checks', flush=True)
            context.close()
    except BaseException as e:
        record['status'] = 'FAIL'
        record['error'] = type(e).__name__ + ': ' + str(e)
        raise
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        log.close()
        (out / 'BROWSER_RESULTS.json').write_text(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
