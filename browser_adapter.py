"""Browser-only IO seam. V4 Decimal, validation and accounting remain untouched.

The JavaScript function is supplied by the trusted financial Web Worker. User
Python is in another interpreter in an opaque-origin worker and has no reference
to this interpreter, its memory, source, storage, or result objects.
"""
import json, sys, types, time
from pathlib import Path

shim=types.ModuleType('backtester.python_sandbox')
class UnusedRPC:
    def __init__(self,*args):raise RuntimeError('No host/subprocess sandbox in browser')
shim.RPC=UnusedRPC
sys.modules['backtester.python_sandbox']=shim
from backtester.python_runtime import PythonRuntime
from backtester.python_definition import build
from backtester.data import load_dataset
from backtester.config import RunConfig
from backtester.simulation import simulate
from backtester.common import canonical, timestamp
from browser_stream import chunks
from backtester.browser_context import CompletedContext, requirements, CONTRACT

class BrowserRPC:
    def __init__(self, context=None):
        self.context=context;self.last_exit=None
        self.profile={k:0 for k in ('contextMs','frameEncodingMs','rpcWaitMs','decisionDecodeMs','calls')}
    def call(self,frame):
        import js
        started=time.perf_counter()
        if self.context is not None:
            last=frame['bars'][-1]
            frame={**frame,'contexts':self.context.at(frame['symbol'],last['open_ms']+last['interval_ms']),
                   'last_exit':self.last_exit}
        encoded_at=time.perf_counter();self.profile['contextMs']+=(encoded_at-started)*1000
        raw=canonical(frame)
        if len(raw.encode())>512*1024:raise ValueError('512KiB completed-context frame bound exceeded')
        sent_at=time.perf_counter();self.profile['frameEncodingMs']+=(sent_at-encoded_at)*1000
        reply=str(js.strategy_call(raw));received_at=time.perf_counter()
        self.profile['rpcWaitMs']+=(received_at-sent_at)*1000
        answer=json.loads(reply)
        self.profile['decisionDecodeMs']+=(time.perf_counter()-received_at)*1000;self.profile['calls']+=1
        if 'error' in answer:raise ValueError(answer['error'])
        return answer['decision']

class BrowserRuntime(PythonRuntime):
    def __init__(self,definition,dataset=None,start_ms=None):
        spec=build(definition)
        self.definition=spec.definition;self.content_hash=spec.content_hash
        self.version_id=spec.version_id;self.warmup_bars=spec.warmup_bars
        requested,needed=requirements(spec.definition,spec.warmup_bars)
        if requested and (dataset is None or start_ms is None):raise ValueError('Declared multi-timeframe context needs its verified dataset and UTC start')
        context=CompletedContext(dataset,requested,needed,start_ms) if requested else None
        self.rpc=BrowserRPC(context);self.previous={};self.signals={}
        self._closed_offsets={};self._last_exits={}

    def after_close(self,account,bar,history):
        # Read-only execution evidence, including positions stopped within their
        # first minute. Rebuild from the restored ledger on a fresh runtime;
        # never infer exits from an absence of positions or mutate the ledger.
        if getattr(self.rpc,'context',None) is not None:
            key=id(account);offset=self._closed_offsets.get(key,0)
            for row in account.closed[offset:]:
                self._last_exits[key,row['symbol']]={k:row[k] for k in
                    ('exit_ms','fill_window_start_ms','fill_window_end_ms','exit_reason')}
            self._closed_offsets[key]=len(account.closed)
            self.rpc.last_exit=self._last_exits.get((key,bar.symbol))
        return super().after_close(account,bar,history)

def run_browser(raw):
    try:
        bundle=json.loads(raw);root=Path('/input');root.mkdir(exist_ok=True)
        manifest=bundle['manifest'];files=bundle['files']
        if not isinstance(files,dict) or len(files)>20:raise ValueError('1–20 input files required')
        if sum(len(x.encode()) for x in files.values())>32*1024**2:raise ValueError('32MiB proof input bound')
        for name,value in files.items():
            if Path(name).name!=name or not name.endswith('.csv'):raise ValueError('unsafe candle filename')
            (root/name).write_text(value)
        (root/'manifest.json').write_text(canonical(manifest))
        ds=load_dataset(root,as_of_ms=timestamp('2026-10-17T00:00:00Z'))
        config=RunConfig.from_dict(bundle['config'])
        result=simulate(ds,BrowserRuntime(bundle['definition'],ds,config.start_ms),config)
        return canonical({'ok':True,'result':result})
    except Exception as e:
        return canonical({'ok':False,'error':str(e)[:700]})

_stream = None
_runtime = None
_stream_profile = {}
def start_stream(raw, checkpoint='null'):
    global _stream,_runtime,_stream_profile
    started=time.perf_counter()
    bundle=json.loads(raw);root=Path('/input');root.mkdir(exist_ok=True)
    manifest=bundle['manifest'];files=bundle['files']
    if not isinstance(files,dict) or not 1<=len(files)<=20:raise ValueError('1–20 input files required')
    if sum(len(x.encode()) for x in files.values())>32*1024**2:raise ValueError('32MiB input bound; requested range is not silently shortened')
    for name,value in files.items():
        if Path(name).name!=name or not name.endswith('.csv'):raise ValueError('unsafe candle filename')
        (root/name).write_text(value)
    (root/'manifest.json').write_text(canonical(manifest))
    dataset=load_dataset(root,as_of_ms=timestamp('2026-10-17T00:00:00Z'))
    config=RunConfig.from_dict(bundle['config'])
    parsed_at=time.perf_counter()
    _runtime=BrowserRuntime(bundle['definition'],dataset,config.start_ms)
    restored=json.loads(checkpoint)
    _stream=chunks(dataset,_runtime,config,restored,bundle.get('checkpoint_every',120))
    restored_calls=0
    if restored:
        from browser_stream import decode
        restored_calls=sum(x['evaluations'] for x in decode(restored['state'])['counts'].values())
    _stream_profile={}
    return canonical({'loaded_candles':sum(len(x) for x in dataset.candles.values()),
                      'dataset_hash':dataset.content_hash,'next_ms':restored['next_ms'] if restored else config.start_ms,
                      'restored_calls':restored_calls,'inputValidationMs':(parsed_at-started)*1000,
                      'contextInitializationMs':(time.perf_counter()-parsed_at)*1000})

def next_stream():
    global _stream_profile
    started=time.perf_counter()
    value=next(_stream)
    advanced_at=time.perf_counter();view_ms=0
    if value['kind']=='DONE':
        from backtester.reports import build_reports
        from backtester.studio_metrics import position_performance
        from decimal import Decimal, localcontext
        result=value['result']
        with localcontext() as ctx:
            ctx.prec=34
            current={name:Decimal(row['initial_capital']) for name,row in result['accounts'].items()}
            points={}
            for row in result['equity_curve']:
                current[row['account']]=Decimal(row['equity'])
                points[row['timestamp_ms']]=sum(current.values(),Decimal(0))
            rows=list(points.items());step=max(1,(len(rows)+598)//599)
            selected=rows[::step]
            if rows and (not selected or selected[-1]!=rows[-1]):selected.append(rows[-1])
            value['view']={'reports':build_reports(result),
                           'position_performance':position_performance(result),
                           'warnings':[('Browser trusted-code worker execution, NOT an OS container. Legacy raw financial result/hash retained for parity; no exchange fills certified.' if w.startswith('Python runs in a separate secret-free OS container.') else w) for w in result['warnings']],
                           'chart_sample':[{'timestamp_ms':ts,'equity':str(eq)} for ts,eq in selected]}
        view_ms=(time.perf_counter()-advanced_at)*1000
    serializing_at=time.perf_counter();raw=serialize_event(value)
    _stream_profile={'advanceMs':(advanced_at-started)*1000,'viewMs':view_ms,
                     'serializationMs':(time.perf_counter()-serializing_at)*1000,
                     'financialCaptureMs':value.get('capture_ms',0),'callbacks':dict(_runtime.rpc.profile)}
    return raw

def serialize_event(value):
    # Checkpoints are already typed JSON; DONE results/reports have already
    # passed their pinned primitives() conversion. Walking this entire growing
    # equity history again adds no validation or financial meaning. Keep the
    # identical canonical JSON options, reject unsupported/non-finite values,
    # and prove byte equality against canonical() in regression tests.
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)

def stream_profile():
    return canonical(_stream_profile)

def validate_browser(raw):
    spec=build(json.loads(raw))
    requested,needed=requirements(spec.definition,spec.warmup_bars)
    result={'definition':spec.definition,'version_id':spec.version_id,
            'content_hash':spec.content_hash,'warmup_bars':spec.warmup_bars}
    if requested:result.update(context_timeframes=requested,input_warmup_bars=needed,context_contract=CONTRACT)
    return canonical(result)
