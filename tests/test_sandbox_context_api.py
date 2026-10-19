"""Trusted API unit tests only. Pasted on_bar code never runs on the host."""
import copy,importlib,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import _kernel_for_tests
sys.modules['sandbox_api']=importlib.import_module('backtester.python_sandbox_runner')
from backtester.browser_sandbox_context import Context,CONTRACT
from backtester.python_sandbox_runner import Candle
from decimal import Decimal as D

M=60000;H=60*M;T=1761955200000+24*H
def bar(t,p):return dict(open_ms=t,interval_ms=p,open='100',high='102',low='99',close='101',volume='10')
def row():return dict(symbol='BTCUSDT',position=None,account={'equity':'1000'},
 contexts={tf:[bar(T-2*p,p),bar(T-p,p)] for tf,p in [('15m',15*M),('1h',H)]})
def ctx(r):return Context(r,[Candle('BTCUSDT',T-M,M,D(100),D(102),D(99),D(101),D(10))],{})

class ActualContextAPITests(unittest.TestCase):
 def test_method_is_defined_on_actual_context_class_not_runtime_monkeypatch(self):
  self.assertIn('candles',Context.__dict__);self.assertEqual(Context.context_contract,CONTRACT)
  self.assertEqual(Context.context_timeframes,('15m','1h'))
 def test_verified_completed_observations_are_immutable_and_not_current_candles(self):
  c=ctx(row())
  for tf,p in [('15m',15*M),('1h',H)]:
   values=c.candles(tf);self.assertIsInstance(values,tuple);self.assertEqual(values[-1].open_ms+p,T)
   with self.assertRaises(AttributeError):values[-1].close=D(0)
 def test_modifying_raw_input_later_cannot_modify_context_observation(self):
  r=row();c=ctx(r);r['contexts']['1h'][-1]['close']='999';self.assertEqual(c.candles('1h')[-1].close,D(101))
 def test_future_partial_stale_gap_duplicate_and_invalid_ohlc_are_rejected(self):
  for kind in ['future','partial','stale','gap','duplicate','ohlc']:
   with self.subTest(kind=kind):
    r=row();b=r['contexts']['1h']
    if kind=='future':b[-1]['open_ms']+=H
    if kind=='partial':b[-1]['open_ms']+=M
    if kind=='stale':b.pop();b.insert(0,bar(T-3*H,H))
    if kind=='gap':b[0]['open_ms']-=H
    if kind=='duplicate':b[0]=copy.deepcopy(b[-1])
    if kind=='ohlc':b[-1]['high']='NaN'
    with self.assertRaises(ValueError):ctx(r)
 def test_undeclared_context_is_explicit_error_instead_of_attribute_error(self):
  r=row();r['contexts']={};c=ctx(r)
  with self.assertRaisesRegex(ValueError,'Declare CONTEXT_TIMEFRAMES'):c.candles('1h')
 def test_last_exit_is_causal_and_state_lifecycle_remains_base_contract(self):
  r=row();r['last_exit']={'exit_ms':T+1,'fill_window_start_ms':T-M,'fill_window_end_ms':T,'exit_reason':'STOP'}
  with self.assertRaisesRegex(ValueError,'Future last-exit'):ctx(r)

if __name__=='__main__':unittest.main()
