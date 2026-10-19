/* Appended after pinned Pyodide JS. No financial kernel/DB/token is supplied. */
let py, runtime, ready=false;
const td = new TextDecoder();
const boot = `
import json, contextlib, os, sys
sys.path.insert(0,'/')
from collections import deque
import pickle,base64,types
from decimal import Decimal,localcontext
from sandbox_api import Candle,encode
from browser_context_api import Context
_histories={};_states={};_ns={'__name__':'strategy','__file__':'/strategy.py'}
with open(os.devnull,'w') as _sink, contextlib.redirect_stdout(_sink):
    exec(compile(_source,'strategy.py','exec'),_ns)
_warmup=_ns.get('WARMUP_BARS',100)
if type(_warmup) is not int or not 2<=_warmup<=501:raise ValueError('WARMUP_BARS outside 2–501')
if not callable(_ns.get('on_bar')):raise ValueError('define on_bar(ctx)')
def _browser_step(raw):
    row=json.loads(raw);sym=row['symbol'];h=_histories.setdefault(sym,deque(maxlen=_warmup))
    for b in row['bars']:
        c=Candle(sym,b['open_ms'],b['interval_ms'],*(Decimal(b[k]) for k in ['open','high','low','close','volume']))
        if h and c.open_ms!=h[-1].open_ms+h[-1].interval_ms:raise ValueError('noncontiguous completed history')
        h.append(c)
    if len(h)<_warmup:raise ValueError('insufficient completed warm-up')
    with localcontext() as ctx:
        ctx.prec=34
        c=Context(row,h,_states.setdefault(sym,{}))
        with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink):d=_ns['on_bar'](c)
    text=json.dumps({'decision':d},default=encode,separators=(',',':'),allow_nan=False)
    if len(text.encode())>65536:raise ValueError('64KiB decision reply bound')
    return text

def _checkpoint_strategy():
    globals_to_save={}
    for key,value in _ns.items():
        if key.startswith('__'):continue
        module=getattr(value,'__module__','').split('.')[0]
        if module in {'random','time','os','posix','nt','secrets','js','pyodide'}:
            raise ValueError('Checkpoint recovery requires deterministic Python state; clocks, randomness, OS and JS interop are not recoverable')
        if isinstance(value,types.ModuleType):
            if value.__name__.split('.')[0] in {'random','time','os','sys','secrets','js','pyodide'}:
                raise ValueError('Checkpoint recovery does not support clock/random/OS/JS module state')
            continue
        if isinstance(value,type):
            if value.__module__=='strategy':
                raise ValueError('User-defined class state is not resumable; keep mutable recovery state in ctx.state')
            continue
        if isinstance(value,types.FunctionType):
            if value.__closure__ or value.__dict__ or value.__kwdefaults__ or any(isinstance(x,(dict,list,set)) for x in (value.__defaults__ or ())):
                raise ValueError('Recovery requires mutable strategy state in ctx.state or serializable globals, not function closures/defaults/attributes')
            continue
        globals_to_save[key]=value
    raw=pickle.dumps((_histories,_states,globals_to_save),protocol=5)
    if len(raw)>1024*1024:raise ValueError('1MiB strategy recovery-state bound exceeded')
    return base64.b64encode(raw).decode()

def _restore_strategy(raw):
    global _histories,_states
    # These bytes are unpickled ONLY in the isolated strategy worker, never in
    # the financial interpreter, page, host Python or server.
    raw=base64.b64decode(raw,validate=True)
    if len(raw)>1024*1024:raise ValueError('strategy checkpoint size exceeded')
    _histories,_states,saved=pickle.loads(raw)
    _ns.update(saved)
`;
onmessage = async ({data}) => {
  try {
    if(data.type==='INIT'){
      runtime=data.files;
      const get = url => {
        const u=new URL(String(url),'https://offline.invalid/');
        if(u.origin!=='https://offline.invalid')throw Error('Network unavailable in strategy sandbox');
        const key=u.pathname.split('/').pop();
        if(!Object.hasOwn(runtime,key))throw Error('Not a preloaded runtime resource');
        return runtime[key];
      };
      // No browser fetch occurs here. CSP also denies connect-src if bypassed.
      self.fetch=async url=>new Response(get(url),{headers:{'Content-Type':String(url).endsWith('.wasm')?'application/wasm':'application/octet-stream'}});
      self.importScripts=(...urls)=>{for(const url of urls)(0,eval)(td.decode(get(url)));};
      py=await loadPyodide({indexURL:'https://offline.invalid/',stdout:()=>{},stderr:()=>{}});
      py.FS.writeFile('/sandbox_api.py',data.api);
      py.FS.writeFile('/browser_context_api.py',data.contextAPI);
      py.globals.set('_source',data.code);
      py.runPython(boot);
      ready=true;
      postMessage({type:'ready',contextContract:py.runPython('Context.context_contract'),contextTimeframes:JSON.parse(py.runPython('json.dumps(Context.context_timeframes)')),runtimeManifest:data.runtimeManifest,wasmBytes:py._module.HEAP8.buffer.byteLength,origin:self.origin,python:py.runPython('import sys;sys.version')});
    } else if(data.type==='SNAPSHOT' && ready){
      let result;
      try {result=JSON.stringify({checkpoint:py.runPython('_checkpoint_strategy()')});}
      catch(e){result=JSON.stringify({error:String(e).slice(-700)});}
      postMessage({type:'reply',id:data.id,result,wasmBytes:py._module.HEAP8.buffer.byteLength});
    } else if(data.type==='RESTORE' && ready){
      py.globals.set('_restore_blob',data.snapshot);
      let result;
      try{py.runPython('_restore_strategy(_restore_blob)');result='{"restored":true}';}
      catch(e){result=JSON.stringify({error:String(e).slice(-700)});}
      postMessage({type:'reply',id:data.id,result,wasmBytes:py._module.HEAP8.buffer.byteLength});
    } else if(data.type==='STEP' && ready){
      const started=performance.now();
      py.globals.set('_frame',data.frame);
      let result;
      try { result=py.runPython('_browser_step(_frame)'); }
      catch(e){result=JSON.stringify({error:String(e).slice(-700)});}
      postMessage({type:'reply',id:data.id,result,wasmBytes:py._module.HEAP8.buffer.byteLength,stepMs:performance.now()-started});
    }
  } catch(e){postMessage({type:'fatal',error:String(e).slice(-1200)});}
};
