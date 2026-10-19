"""Trusted context-provider tests. Never execute pasted strategy Python here."""
import ast
from dataclasses import replace
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import _kernel_for_tests
from backtester.browser_context import requirements,aggregate,CompletedContext
from backtester.models import Candle
from backtester.errors import ValidationError

M=60000;H=60*M;BASE=1761955200000

def bars(n=3000,symbol='BTCUSDT'):
    return tuple(Candle(symbol,BASE+i*M,M,D(100+i),D(102+i),D(99+i),D(101+i),D(i+1)) for i in range(n))

def dataset(rows):return NS(interval='1m',candles=rows)

class CompletedContextTests(unittest.TestCase):
    def test_declared_pre_window_counts(self):
        spec={'code':(ROOT/'examples/hks_legacy_smc_reverse.py').read_text()}
        self.assertEqual(requirements(spec,2),({'15m':50,'1h':21},1320))

    def test_legacy_no_declaration_unchanged(self):
        self.assertEqual(requirements({'code':'def on_bar(ctx): pass'},51),({},51))

    def test_invalid_metadata_refused_without_execution(self):
        for code in ['CONTEXT_TIMEFRAMES={"4h":2}','CONTEXT_TIMEFRAMES={"1h":65}',
                     'CONTEXT_TIMEFRAMES={"1h":True}','CONTEXT_TIMEFRAMES=dict(a=2)',
                     'CONTEXT_TIMEFRAMES={"1h":21,"1h":22}',
                     'CONTEXT_TIMEFRAMES={"1h":21}\nCONTEXT_TIMEFRAMES={"1h":22}',
                     'CONTEXT_TIMEFRAMES={"1h":1}', 'CONTEXT_TIMEFRAMES={**{}}']:
            with self.subTest(code=code),self.assertRaises(ValidationError):requirements({'code':code},2)

    def test_utc_aggregation_ohlcv(self):
        rows=bars(60);hour=aggregate(rows,'1h')[0]
        self.assertEqual((hour.open_ms,hour.interval_ms,hour.open,hour.high,hour.low,hour.close,hour.volume),
                         (BASE,H,D(100),D(161),D(99),D(160),D(1830)))

    def test_partial_utc_hour_not_supplied(self):
        self.assertEqual(aggregate(bars(120)[1:],'1h'),aggregate(bars(120),'1h')[1:])
        self.assertEqual(aggregate(bars(59),'1h'),())

    def test_gap_and_duplicate_not_aggregated(self):
        rows=bars(60)
        for bad in (rows[:30]+rows[31:],rows[:30]+(rows[29],)+rows[30:]):
            self.assertEqual(aggregate(bad,'1h'),())

    def test_completed_hour_boundary_and_no_lookahead(self):
        rows=bars();start=BASE+1320*M
        c=CompletedContext(dataset({'BTCUSDT':rows}),{'15m':50,'1h':21},1320,start)
        for delta in (0,M,5*M,59*M,60*M):
            frame=c.at('BTCUSDT',start+delta)
            latest=frame['1h'][-1]
            self.assertEqual(latest['open_ms']+H,(start+delta)//H*H)
            self.assertEqual(len(frame['15m']),50)
        changed=tuple(replace(b,high=D(999999),close=D(999999)) if b.open_ms>=start else b for b in rows)
        other=CompletedContext(dataset({'BTCUSDT':changed}),{'15m':50,'1h':21},1320,start)
        self.assertEqual(c.at('BTCUSDT',start),other.at('BTCUSDT',start))

    def test_no_silently_delayed_warmup(self):
        rows=bars();start=BASE+1320*M
        with self.assertRaisesRegex(ValidationError,'pre-window'):
            CompletedContext(dataset({'BTCUSDT':rows[1:]}),{'15m':50,'1h':21},1320,start)

    def test_mid_hour_start_requires_all_context(self):
        start=BASE+(1320+17)*M
        c=CompletedContext(dataset({'BTCUSDT':bars()}),{'15m':50,'1h':21},1320,start)
        self.assertEqual(c.at('BTCUSDT',start)['1h'][-1]['open_ms']+H,start//H*H)

    def test_symbol_isolation(self):
        a=bars();b=tuple(replace(x,symbol='ETHUSDT',open=x.open*10,high=x.high*10,low=x.low*10,close=x.close*10) for x in a)
        c=CompletedContext(dataset({'BTCUSDT':a,'ETHUSDT':b}),{'1h':21},1320,BASE+1320*M)
        self.assertEqual(D(c.at('ETHUSDT',BASE+1320*M)['1h'][-1]['close']),D(c.at('BTCUSDT',BASE+1320*M)['1h'][-1]['close'])*10)

    def test_missing_completed_context_at_decision_rejected(self):
        rows=bars();start=BASE+1320*M
        rows=rows[:1330]+rows[1331:]
        c=CompletedContext(dataset({'BTCUSDT':rows}),{'15m':50},1320,start)
        with self.assertRaisesRegex(ValidationError,'insufficient continuous'):
            c.at('BTCUSDT',start+15*M)

    def test_non_minute_dataset_rejected(self):
        with self.assertRaisesRegex(ValidationError,'verified 1m'):
            CompletedContext(NS(interval='15m',candles={}),{'1h':21},1320,BASE+1320*M)

    def test_strategy_and_worker_syntax_without_execution(self):
        ast.parse((ROOT/'examples/hks_legacy_smc_reverse.py').read_text())
        source=(ROOT/'web/strategy-worker.js').read_text().split('const boot = `',1)[1].split('`;',1)[0]
        ast.parse(source)

    def test_all_pinned_kernel_source_hashes_unchanged(self):
        pins=json.loads((ROOT/'evidence/KERNEL_SOURCE_PINS.json').read_text())
        sources=json.loads((ROOT/'web/kernel.json').read_text())
        # Existing authoritative regression also checks the complete pin set.
        mapping=pins['source_sha256']
        for name,expected in mapping.items():
            if name in sources:self.assertEqual(hashlib.sha256(sources[name].encode()).hexdigest(),expected,name)

if __name__=='__main__':unittest.main()
