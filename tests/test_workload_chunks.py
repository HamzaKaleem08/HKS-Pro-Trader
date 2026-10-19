"""Scheduling-only regression: unchanged financial results and no replayed bars."""
import json,unittest
import sys,types
from unittest.mock import patch
from test_checkpoint import chunks,dataset,runtime,config,simulate,Callback


class Trace(Callback):
    def __init__(self):self.seen=[]
    def call(self,frame):
        self.seen.append((frame['symbol'],frame['bars'][-1]['open_ms']))
        return super().call(frame)


def traced_runtime():
    r=runtime();r.rpc=Trace();return r


class WorkloadChunkTests(unittest.TestCase):
    def test_callback_frame_is_encoded_once_with_identical_wire_bytes(self):
        import browser_adapter
        from backtester.common import canonical
        sent=[]
        bridge=types.SimpleNamespace(strategy_call=lambda raw:(sent.append(raw) or '{"decision":null}'))
        frame={'symbol':'BTCUSDT','bars':[],'position':None}
        rpc=browser_adapter.BrowserRPC()
        with patch.dict(sys.modules,{'js':bridge}),patch.object(browser_adapter,'canonical',wraps=canonical) as encoder:
            self.assertIsNone(rpc.call(frame))
        self.assertEqual(encoder.call_count,1)
        self.assertEqual(sent,[canonical(frame)])
    def test_serialization_fast_path_is_identical_not_lossy(self):
        from browser_adapter import serialize_event
        from backtester.common import canonical
        values=list(chunks(dataset(),runtime(),config(),checkpoint_every=2,work_steps=2))
        for value in values:self.assertEqual(serialize_event(value),canonical(value))
        with self.assertRaises(ValueError):serialize_event({'bad':float('nan')})
        with self.assertRaises(TypeError):serialize_event({'bad':object()})
    def test_work_yields_do_not_change_any_financial_result(self):
        for mode in ('individual','shared'):
            r=traced_runtime();expected=simulate(dataset(),r,config(mode))
            other=traced_runtime()
            events=list(chunks(dataset(),other,config(mode),checkpoint_every=5,work_steps=2))
            self.assertIn('PROGRESS',[x['kind'] for x in events])
            self.assertEqual(events[-1]['result'],expected)
            self.assertEqual(other.rpc.seen,r.rpc.seen)
            self.assertEqual(len(other.rpc.seen),len(set(other.rpc.seen)))

    def test_first_work_boundary_is_durable_before_full_checkpoint_interval(self):
        events=list(chunks(dataset(),runtime(),config(),checkpoint_every=120,work_steps=2))
        self.assertEqual(events[0]['kind'],'CHECKPOINT')
        self.assertLess(events[0]['snapshot']['next_ms'],config().end_ms)
        self.assertTrue(all('snapshot' not in x for x in events if x['kind']=='PROGRESS'))

    def test_every_durable_resume_preserves_cursor_and_ledger(self):
        original=list(chunks(dataset(),runtime(),config(),checkpoint_every=3,work_steps=2))
        for event in original:
            if event['kind']!='CHECKPOINT':continue
            snapshot=json.loads(json.dumps(event['snapshot']))
            r=traced_runtime()
            resumed=list(chunks(dataset(),r,config(),resume=snapshot,checkpoint_every=2,work_steps=4))
            self.assertEqual(resumed[-1]['result'],original[-1]['result'])
            self.assertTrue(all(ts>=snapshot['next_ms'] for _,ts in r.rpc.seen))
            self.assertEqual(len(r.rpc.seen),len(set(r.rpc.seen)))

    def test_elapsed_budget_yields_without_changing_results(self):
        expected=list(chunks(dataset(),runtime(),config(),checkpoint_every=120))[-1]['result']
        from itertools import count
        ticks=count(0,.02)
        with patch('time.monotonic',side_effect=lambda:next(ticks)):
            values=list(chunks(dataset(),runtime(),config(),checkpoint_every=120,
                               work_steps=10000,yield_seconds=.01))
        self.assertIn('PROGRESS',[x['kind'] for x in values])
        self.assertEqual(values[-1]['result'],expected)

    def test_invalid_work_limits_reject_instead_of_weakening_safeguards(self):
        for n in (0,True,10001,1.5):
            with self.assertRaises(ValueError):
                list(chunks(dataset(),runtime(),config(),work_steps=n))
        for n in (0,True,float('inf'),float('nan'),6):
            with self.assertRaises(ValueError):
                list(chunks(dataset(),runtime(),config(),yield_seconds=n))


if __name__=='__main__':unittest.main()
