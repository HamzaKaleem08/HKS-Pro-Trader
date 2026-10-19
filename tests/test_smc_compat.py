"""Broker restart/exit evidence and unchanged per-wallet risk/position limits.

Callbacks here are trusted fixture decisions, never pasted strategy execution.
"""
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS
import copy,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import _kernel_for_tests
from browser_adapter import BrowserRuntime
from backtester.models import Candle,Dataset
from backtester.config import RunConfig
from backtester.simulation import simulate
BASE=1761955200000;M=60000
DEFINITION={'schema_version':1,'kind':'PYTHON_STRATEGY','name':'Trusted fixture callback',
            'code':'WARMUP_BARS=2\ndef on_bar(ctx):\n return None\n'}

class Recorder:
    context=object()
    def call(self,frame):self.frame=frame;return None

def closed(sym,when):
    return {'symbol':sym,'exit_ms':when+M,'fill_window_start_ms':when,'fill_window_end_ms':when+M,'exit_reason':'INITIAL_STOP'}

def account(ledger):
    return NS(closed=ledger,positions={},cash=D(1000),equity=lambda:D(1000),reserved=lambda:D(0),reserved_risk=lambda:D(0))

def history():return tuple(Candle('BTCUSDT',BASE+i*M,M,D(100),D(101),D(99),D(100),D(10)) for i in range(2))

class CompatTests(unittest.TestCase):
    def runtime(self):
        r=BrowserRuntime(DEFINITION);r.rpc=Recorder();return r

    def test_first_minute_stop_is_explicit_exit_evidence(self):
        r=self.runtime();a=account([closed('BTCUSDT',BASE+M)]);h=history()
        r.after_close(a,h[-1],h)
        self.assertEqual(r.rpc.last_exit,{k:v for k,v in a.closed[-1].items() if k!='symbol'})

    def test_exit_evidence_is_symbol_and_account_scoped(self):
        r=self.runtime();h=history()
        a=account([closed('ETHUSDT',BASE+M)]);r.after_close(a,h[-1],h)
        self.assertIsNone(r.rpc.last_exit)
        # Fresh runtime avoids unrelated observation chronology checks.
        r=self.runtime();a=account([closed('BTCUSDT',BASE+M)]);other=account([])
        r.after_close(a,h[-1],h);r.previous={};r.after_close(other,h[-1],h)
        self.assertIsNone(r.rpc.last_exit)

    def test_fresh_runtime_rebuilds_evidence_from_restored_ledger(self):
        a=account([closed('BTCUSDT',BASE),closed('BTCUSDT',BASE+M)]);h=history()
        first=self.runtime();first.after_close(a,h[-1],h)
        fresh=self.runtime();fresh.after_close(a,h[-1],h)
        self.assertEqual(first.rpc.last_exit,fresh.rpc.last_exit)

    def test_observation_never_mutates_actual_ledger(self):
        r=self.runtime();a=account([closed('BTCUSDT',BASE+M)]);before=copy.deepcopy(a.closed);h=history()
        r.after_close(a,h[-1],h);r.rpc.last_exit['exit_reason']='MUTATED_ONLY_COPY'
        self.assertEqual(a.closed,before)

    def limits_fixture(self,mode):
        symbols=('AAAUSDT','BBBUSDT','CCCUSDT','DDDUSDT')
        rows={s:tuple(Candle(s,BASE+i*M,M,D(100),D('100.1'),D('99.9'),D(100),D(10)) for i in range(5)) for s in symbols}
        ds=Dataset('synthetic_limits','SYNTHETIC','USDT_LINEAR_PERPETUAL','1m',True,'Synthetic limits fixture',None,rows,{},'fixture')
        r=BrowserRuntime(DEFINITION)
        class Callback:
            def call(self,frame):
                if frame['bars'][-1]['open_ms']==BASE+M:
                    return {'enter':{'side':'SHORT','stop':{'mode':'fraction','value':'.01'},'target':None}}
                return None
        r.rpc=Callback()
        return simulate(ds,r,RunConfig(BASE+2*M,BASE+5*M,mode=mode,risk_fraction=D('.01'),max_positions=3,allow_uncertified_futures=True))

    def test_shared_max_three_positions_and_one_percent_budget(self):
        result=self.limits_fixture('shared')
        self.assertEqual(len(result['open_positions']),3)
        rejected=[r for r in result['decisions'] if r['outcome']=='REJECTED']
        self.assertEqual(len(rejected),1)
        self.assertEqual(rejected[0]['reason'],'MAX_CONCURRENT_POSITIONS')
        for p in result['open_positions']:
            entry=next(e for e in result['decisions'] if e.get('trade_id')==p['trade_id'])
            # Earlier simultaneous fills have already paid fees/adverse entry
            # slippage. Current equity, not the initial $1000, is the basis.
            self.assertEqual(D(p['risk_budget']),D(entry['equity_before'])*D('.01'))
            self.assertLessEqual(D(p['planned_risk']),D(p['risk_budget']))
        self.assertEqual(set(result['accounts']),{'SHARED'})

    def test_individual_maximum_is_per_independent_wallet(self):
        result=self.limits_fixture('individual')
        self.assertEqual(len(result['open_positions']),4)
        self.assertEqual(len(result['accounts']),4)
        self.assertEqual(sum(D(a['initial_capital']) for a in result['accounts'].values()),D(4000))

if __name__=='__main__':unittest.main()
