"""Synthetic financial scheduling tests; no host execution of strategy source."""
import ast,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
TMP=tempfile.TemporaryDirectory(prefix='hks-static-unit-',dir='/tmp')
kernel=json.loads((ROOT/'web/kernel.json').read_text())
for name,code in kernel.items():
 p=Path(TMP.name)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(code)
sys.path.insert(0,TMP.name)
from browser_stream import chunks,encode,decode,capture,restore
from browser_adapter import BrowserRuntime
from backtester.config import RunConfig
from backtester.common import canonical
from backtester.models import Candle,Dataset
from backtester.simulation import simulate
BASE=1761955200000
DEFINITION={'schema_version':1,'kind':'PYTHON_STRATEGY','name':'Synthetic callback test','code':'WARMUP_BARS=2\ndef on_bar(ctx):\n return None\n'}
class Callback:
 def call(self,frame):
  b=frame['bars'][-1];p=frame['position'];i=(b['open_ms']-BASE)//60000
  if p is None:
   if i in (1,8):return {'enter':{'side':'LONG','stop':{'mode':'fraction','value':'.1'},'target':None}}
   return None
  if i==2:return {'reduce_fraction':'.25','stop':p['stop']}
  if i==3:return {'stop':max(D(p['stop']),D(p['entry_price']))}
  if i==5:return {'close':True}
  return None

def runtime():
 r=BrowserRuntime(DEFINITION);r.rpc=Callback();return r

def dataset():
 out={}
 for s in ('BTCUSDT','ETHUSDT'):
  prices=(100,100,110,120,112,116,117,100,100,110,108,110)
  out[s]=tuple(Candle(s,BASE+i*60000,60000,D(o),D(o+1),D(o-1),D(o),D(10)) for i,o in enumerate(prices))
 return Dataset('synthetic_checkpoint','SYNTHETIC','SPOT','1m',True,'Synthetic test',None,out,{},'test')

def config(mode='shared',end_policy='KEEP_OPEN'):
 return RunConfig(BASE+2*60000,BASE+12*60000,mode=mode,fee_bps=D(10),slippage_bps=D(2),end_policy=end_policy)

class CheckpointTests(unittest.TestCase):
 def test_all_checkpoint_boundaries_exact_shared(self):
  ds=dataset();cfg=config();expected=simulate(ds,runtime(),cfg)
  original=list(chunks(ds,runtime(),cfg,checkpoint_every=1))
  self.assertTrue(any(x['kind']=='CHECKPOINT' for x in original))
  self.assertEqual(original[-1]['result'],expected)
  for item in original[:-1]:
   fresh=list(chunks(ds,runtime(),cfg,resume=json.loads(json.dumps(item['snapshot'])),checkpoint_every=1))
   self.assertEqual(fresh[-1]['result'],expected)
 def test_individual_and_explicit_end_resume(self):
  for mode in ('individual','shared'):
   for policy in ('KEEP_OPEN','CLOSE_AT_LAST_CLOSE'):
    ds=dataset();cfg=config(mode,policy);expected=simulate(ds,runtime(),cfg)
    values=list(chunks(ds,runtime(),cfg,checkpoint_every=2))
    resumed=list(chunks(ds,runtime(),cfg,resume=values[1]['snapshot'],checkpoint_every=3))
    self.assertEqual(resumed[-1]['result'],expected)
 def test_open_partial_and_scheduled_stop_exist_at_boundary(self):
  snapshots=list(chunks(dataset(),runtime(),config(),checkpoint_every=1))[:-1]
  states=[decode(s['snapshot']['state']) for s in snapshots]
  self.assertTrue(any(p.scheduled for st in states for a in st['accounts'].values() for p in a.positions.values()))
  self.assertTrue(any(p.quantity<p.original_quantity for st in states for a in st['accounts'].values() for p in a.positions.values()))
 def test_decimal_and_tuple_set_type_roundtrip(self):
  x={'d':D('1.00000000000000000000000003'),'sets':{('PYTHON',123)},'tuple':(D('2'),None)}
  self.assertEqual(decode(json.loads(json.dumps(encode(x)))),x)
 def test_reject_executable_checkpoint_types(self):
  with self.assertRaises(ValueError):decode({'@':'eval','v':'print(1)'})
  with self.assertRaises(ValueError):decode({'@':'decimal','v':'NaN'})
  with self.assertRaises(ValueError):encode(object())
 def test_reject_incomplete_snapshot(self):
  with self.assertRaises(ValueError):restore({'schema':1,'next_ms':BASE,'state':encode({}),'runtime':encode({})},runtime())
 def test_invalid_checkpoint_interval(self):
  for n in (0,1441,True):
   with self.assertRaises(ValueError):list(chunks(dataset(),runtime(),config(),checkpoint_every=n))
 def test_all_pinned_sources_unchanged(self):
  pins=json.loads((ROOT/'evidence/KERNEL_SOURCE_PINS.json').read_text())
  for n,sha in pins['source_sha256'].items():self.assertEqual(hashlib.sha256(kernel[n].encode()).hexdigest(),sha)
 def test_every_financial_body_statement_preserved(self):
  # The scheduling adapter reads inspect.getsource, never substitutes finance.
  s=(ROOT/'browser_stream.py').read_text()
  self.assertIn('inspect.getsource(simulation._simulate)',s)
  for forbidden in ('stop_fraction =','quantity =','price =','gross =','fee_bps ='):
   self.assertNotIn(forbidden,s)
 def test_free_pages_headers_include_extensionless_paths(self):
  text=(ROOT/'web/_headers').read_text()
  for route in ('/sandbox\n','/vendor/pyodide/console\n','/financial-worker.js\n'):
   self.assertIn(route,text)
 def test_no_activation_or_network_execution_endpoints(self):
  text=(ROOT/'web/app.js').read_text()
  self.assertNotIn('/api/',text)
  self.assertNotIn('Authorization:',text)
  self.assertIn('trusted',text)
 def test_four_year_rejected_not_shortened(self):
  text=(ROOT/'web/app.js').read_text()
  self.assertIn('200000',text)
  self.assertIn('Four-year replay is not validated',text)
  self.assertNotIn('slice(0,200000)',text)

if __name__=='__main__':unittest.main()
