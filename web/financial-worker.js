// Trusted pinned financial interpreter: strategy source NEVER executes here.
importScripts('vendor/pyodide/pyodide.js');
let py,words,bytes,calls=0,start,calculationStart,computeMs=0,loaded,worstChunkMs=0;
const decoder=new TextDecoder();
self.strategy_call=frame=>{
  Atomics.store(words,0,0);postMessage({type:'call',seq:++calls,frame});
  if(Atomics.wait(words,0,0,3000)==='timed-out'||Atomics.load(words,0)!==1)throw Error('Strategy response deadline exceeded');
  const length=Atomics.load(words,1);
  if(length<0||length>65536)throw Error('Strategy decision exceeds 64KiB');
  return decoder.decode(new Uint8Array(bytes.subarray(0,length)));
};
onmessage=async({data})=>{
  try{
    if(data.type==='BOOT'){
      start=performance.now();words=new Int32Array(data.channel,0,4);bytes=new Uint8Array(data.channel,16);
      py=await loadPyodide({indexURL:new URL('vendor/pyodide/',location.href).href,stdout:()=>{},stderr:()=>{}});
      py.FS.mkdirTree('/app/backtester');
      for(const [name,source]of Object.entries(data.kernel)){
        if(!/^backtester\/[a-z_]+\.py$/.test(name)&&!['browser_adapter.py','browser_stream.py'].includes(name))throw Error('Unexpected kernel path');
        py.FS.writeFile('/app/'+name,source);
      }
      py.runPython("import sys;sys.path.insert(0,'/app');from browser_adapter import start_stream,next_stream,validate_browser,stream_profile");
      if(data.validate){
        py.globals.set('_definition',JSON.stringify(data.validate));
        postMessage({type:'validated',value:JSON.parse(py.runPython('validate_browser(_definition)'))});return;
      }
      py.globals.set('_input',JSON.stringify(data.bundle));
      py.globals.set('_resume',JSON.stringify(data.resume?.finance||null));
      loaded=JSON.parse(py.runPython('start_stream(_input,_resume)'));
      calculationStart=performance.now();postMessage({type:'loaded',loaded});
    }
    if(data.type==='NEXT'){
      const chunkStart=performance.now(),raw=py.runPython('next_stream()'),parsedAt=performance.now(),value=JSON.parse(raw),ended=performance.now();
      const chunkMs=ended-chunkStart;computeMs+=chunkMs;worstChunkMs=Math.max(worstChunkMs,chunkMs);
      const metrics={calls:calls+(loaded.restored_calls||0),sessionCalls:calls,initializationMs:calculationStart-start,calculationMs:computeMs,
        chunkMs,worstChunkMs,jsonParseMs:ended-parsedAt,profile:JSON.parse(py.runPython('stream_profile()')),
        financialWasmBytes:py._module.HEAP8.buffer.byteLength,loaded};
      if(value.kind==='DONE')postMessage({type:'done',value:{ok:true,result:value.result,view:value.view},metrics});
      else if(value.kind==='PROGRESS')postMessage({type:'progress',next_ms:value.next_ms,metrics});
      else postMessage({type:'checkpoint',snapshot:value.snapshot,metrics});
    }
  }catch(e){postMessage({type:'fatal',error:String(e).slice(-1800)});}
};
