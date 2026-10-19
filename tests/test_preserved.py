import gzip,hashlib,json,sys,unittest,os,csv,io
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]

class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=json.loads((ROOT/'evidence/NATIVE_CONTAINER_BASELINES.json').read_text())
        cls.catalog=json.loads((ROOT/'web/catalog.json').read_text())
    def test_all_copied_financial_sources_match_frozen_v4(self):
        pins=json.loads((ROOT/'evidence/KERNEL_SOURCE_PINS.json').read_text());kernel=json.loads((ROOT/'web/kernel.json').read_text())
        for name,sha in pins['source_sha256'].items():self.assertEqual(hashlib.sha256(kernel[name].encode()).hexdigest(),sha)
    def test_original_128_source_hashes_still_match(self):
        root=Path(os.environ.get('HKS_V4_SOURCE_ROOT','/workspace/HKS-Pro-Trader-backtester-v4-python-20261017'))
        if not (root/'V4_PYTHON_SOURCE_SHA256.json').exists():self.skipTest('Original V4 archive required for independent full-source verification; copied kernel pin test remains available')
        pins=json.loads((root/'V4_PYTHON_SOURCE_SHA256.json').read_text())
        self.assertEqual(len(pins['files']),128)
        for name,sha in pins['files'].items():self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),sha)
    def test_fixture_compressed_checksums_and_csv_checksums(self):
        for c in self.catalog:
            raw=(ROOT/'web'/c['url']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),c['sha256']);self.assertEqual(len(raw),c['bytes'])
            b=json.loads(gzip.decompress(raw))
            for f in b['manifest']['files']:self.assertEqual(hashlib.sha256(b['files'][f['file']].encode()).hexdigest(),f['sha256'])
    def test_all_monthly_cache_candles_independently_validate(self):
        entries=json.loads((ROOT/'web/candle-catalog.json').read_text());self.assertEqual(len(entries),20);total=0
        for e in entries:
            raw=(ROOT/'web'/e['url']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),e['sha256'])
            plain=gzip.decompress(raw);self.assertEqual(hashlib.sha256(plain).hexdigest(),e['uncompressed_sha256'])
            rows=csv.DictReader(io.StringIO(plain.decode()));count=0
            for i,r in enumerate(rows):
                self.assertEqual(int(r['open_time']),e['start_ms']+i*60000)
                o,h,lo,c,v=[D(r[k]) for k in ['open','high','low','close','volume']]
                self.assertTrue(all(x.is_finite() for x in (o,h,lo,c,v)));self.assertGreater(min(o,h,lo,c),0)
                self.assertGreaterEqual(v,0);self.assertGreaterEqual(h,max(o,c));self.assertLessEqual(lo,min(o,c));self.assertGreaterEqual(h,lo);count+=1
            self.assertEqual(count,e['candles']);self.assertEqual(e['start_ms']+count*60000,e['end_ms']);total+=count
        self.assertEqual(total,864000)
    def test_native_long_and_short_trailing_hand_value(self):
        for name in ['synthetic_long_trailing','synthetic_short_trailing']:
            r=self.native[name]['result'];self.assertEqual(D(next(iter(r['accounts'].values()))['ending_equity']),D('1020'));self.assertEqual(r['trades'][0]['exit_reason'],'TRAILING_STOP')
    def test_independent_partial_hand_calculation(self):
        r=self.native['synthetic_hand_partial']['result'];self.assertEqual(len(r['trades']),2)
        # 1 unit entered at100. 0.25 exits110;0.75 exits120 =>17.5.
        self.assertEqual(sum((D(t['net_pnl']) for t in r['trades']),D(0)),D('.25')*10+D('.75')*20)
        self.assertEqual(D(r['accounts']['SHARED']['ending_equity']),D('1017.5'))
    def test_atr_stop_at_actual_gap_entry(self):
        t=self.native['synthetic_atr_gap']['result']['trades'][0]
        self.assertEqual((D(t['entry_price']),D(t['initial_stop']),D(t['target'])),(D(110),D(106),D(118)))
    def test_independent_all_trade_pnl_fee_slippage_reconciliation(self):
        for case in self.native.values():
            if not case['ok']:continue
            r=case['result'];fees=D(r['config']['fee_bps'])/10000
            for t in r['trades']:
                q=D(t['quantity']);sign=1 if t['side']=='LONG' else -1
                gross=sign*(D(t['exit_price'])-D(t['entry_price']))*q
                self.assertLess(abs(gross-D(t['gross_pnl'])),D('1e-20'))
                self.assertLess(abs((D(t['entry_price'])+D(t['exit_price']))*q*fees-D(t['fees'])),D('1e-20'))
                self.assertLess(abs(gross-D(t['fees'])-D(t['net_pnl'])),D('1e-20'))
                self.assertLess(abs(D(t['gross_before_slippage'])-D(t['slippage_cost'])-D(t['gross_pnl'])),D('1e-20'))
            for k,a in r['accounts'].items():
                pnl=sum((D(t['net_pnl']) for t in r['trades'] if t['account']==k),D(0))
                self.assertLess(abs(D(a['ending_equity'])-D(a['initial_capital'])-pnl),D('1e-20'))
    def test_native_invalid_inputs_fail_without_report(self):
        for name in ['synthetic_invalid_stop','synthetic_invalid_decimal']:
            self.assertFalse(self.native[name]['ok']);self.assertNotIn('result',self.native[name])
    def test_actual_genuine_data_cases_not_fabricated(self):
        for c in self.catalog:
            if not c['synthetic']:
                r=self.native[c['id']]['result'];self.assertFalse(r['synthetic']);self.assertEqual(r['exchange'],'BINANCE');self.assertEqual(r['market'],'USDT_LINEAR_PERPETUAL')
                self.assertTrue(r['config']['allow_uncertified_futures']);self.assertTrue(r['trades'])
    def test_completed_native_wallets_are_isolated(self):
        a=self.native['synthetic_multicoin_costs_individual']['result']['accounts'];b=self.native['synthetic_multicoin_costs_shared']['result']['accounts']
        self.assertEqual(set(a),{'BTCUSDT','ETHUSDT'});self.assertEqual(set(b),{'SHARED'})
        self.assertEqual(sum(D(x['initial_capital']) for x in a.values()),D(2000));self.assertEqual(D(b['SHARED']['initial_capital']),D(1000))
    def test_cloudflare_asset_bounds(self):
        files=[p for p in (ROOT/'web').rglob('*') if p.is_file()];self.assertLess(len(files),20000)
        for p in files:self.assertLessEqual(p.stat().st_size,25*1024**2,p.name)
    def test_sandbox_configuration_has_no_same_origin_permission(self):
        client=(ROOT/'web/client.js').read_text();self.assertIn("this.frame.sandbox='allow-scripts'",client);self.assertNotIn('allow-same-origin',client)
        sys.path.insert(0,str(ROOT));from serve import policies
        self.assertIn("connect-src 'none'",policies()['sandbox']);self.assertIn("default-src 'none'",policies()['sandbox'])
        self.assertEqual(policies()['inert'],"default-src 'none'; sandbox; frame-ancestors 'none'",'The bundled upstream console must not execute on the application origin')

if __name__=='__main__':unittest.main()
