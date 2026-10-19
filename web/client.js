import {verifiedBytes,assertContextAPI,CONTEXT_CONTRACT} from './runtime-integrity.js?sha256=1801327ff8bab8700e939283b7b3b249fc3f1903fb5e84ac2c6364d1c9f20737';
const MANIFEST_SHA256='0cbd6447536d9caf13aeb5a84710a1cb0df7f0a3df1f522a050c9fc4a5d8c747';
let runtimePromise;
const td=new TextDecoder();
const names=['pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json'];
async function manifest(){return JSON.parse(td.decode(await verifiedBytes('runtime-manifest.json',MANIFEST_SHA256)));}
export async function runtimeIdentity(){
  const m=await manifest();return {contract:CONTEXT_CONTRACT,manifest:MANIFEST_SHA256,assets:m.assets,
    client:new URL(import.meta.url).searchParams.get('sha256')};
}
async function material(){
  if(!runtimePromise)runtimePromise=(async()=>{
    const m=await manifest();
    const pairs=await Promise.all(Object.entries(m.assets).map(async([name,hash])=>[name,await verifiedBytes(name,hash)]));
    const assets=Object.fromEntries(pairs);
    return {files:Object.fromEntries(names.map(n=>[n,assets['vendor/pyodide/'+n]])),
      source:td.decode(assets['vendor/pyodide/pyodide.js'])+'\n'+td.decode(assets['strategy-worker.js']),
      kernel:JSON.parse(td.decode(assets['kernel.json'])),financialHash:m.assets['financial-worker.js'],frameHash:m.assets['sandbox.html'],manifest:MANIFEST_SHA256};
  })().catch(error=>{runtimePromise=null;throw error;});
  return runtimePromise;
}
export class SandboxClient{
  async init(code,timeout=12000){
    if(typeof code!=='string'||new TextEncoder().encode(code).length>12000)throw Error('Python source limit: 12,000 UTF-8 bytes');
    const m=await material();this.frame=document.createElement('iframe');this.frame.sandbox='allow-scripts';this.frame.hidden=true;this.pending=new Map();this.sequence=0;
    this.ready=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>this.stop(Error('Sandbox initialization deadline exceeded')),timeout);
      this.rejectInit=e=>{clearTimeout(timer);this.rejectInit=null;reject(e);};
      const frameReady=e=>{
        if(e.source!==this.frame.contentWindow||e.data?.type!=='HKS_OPAQUE_FRAME_READY')return;
        removeEventListener('message',frameReady);
        const channel=new MessageChannel();this.port=channel.port1;
        this.port.onmessage=({data})=>{
          if(data.type==='attached')this.port.postMessage({type:'INIT',code,files:m.files,api:m.kernel['backtester/python_sandbox_runner.py'],contextAPI:m.kernel['backtester/browser_sandbox_context.py'],runtimeManifest:m.manifest});
          if(data.type==='ready'){try{assertContextAPI(data,m.manifest);}catch(error){this.stop(error);return;}clearTimeout(timer);this.rejectInit=null;this.info=data;resolve(data);}
          if(data.type==='fatal'){this.rejectInit?.(Error(data.error));for(const x of this.pending.values())x.reject(Error(data.error));this.pending.clear();}
          if(data.type==='reply'){
            const p=this.pending.get(data.id);if(!p)return;clearTimeout(p.timer);this.pending.delete(data.id);
            this.lastWasmBytes=data.wasmBytes;this.lastStepMs=data.stepMs;p.resolve(data.result);
          }
        };
        this.port.start();this.frame.contentWindow.postMessage({type:'ATTACH',source:m.source},'*',[channel.port2]);
      };
      addEventListener('message',frameReady);this.removeListener=()=>removeEventListener('message',frameReady);
    });
    this.frame.src='sandbox.html?sha256='+m.frameHash;document.body.append(this.frame);return this.ready;
  }
  step(frame,timeout=3000){
    const id=++this.sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('Strategy callback deadline exceeded'));},timeout);
      this.pending.set(id,{resolve,reject,timer});this.port.postMessage({type:'STEP',id,frame:typeof frame==='string'?frame:JSON.stringify(frame)});
    });
  }
  control(type,snapshot,timeout=5000){
    const id=++this.sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('Strategy checkpoint deadline exceeded'));},timeout);
      this.pending.set(id,{resolve:v=>{const x=JSON.parse(v);x.error?reject(Error(x.error)):resolve(x);},reject,timer});
      this.port.postMessage({type,id,snapshot});
    });
  }
  stop(reason=Error('Sandbox stopped')){
    this.rejectInit?.(reason);
    this.removeListener?.();this.port?.postMessage({type:'STOP'});this.port?.close();this.frame?.remove();
    for(const p of this.pending?.values()||[]){clearTimeout(p.timer);p.reject(Error('Sandbox stopped'));}this.pending?.clear();
  }
}
export function replayProgress(cursor,config){
  if(!Number.isFinite(cursor)||!Number.isFinite(config.start_ms)||!Number.isFinite(config.end_ms)||config.end_ms<=config.start_ms)return 0;
  return Math.max(0,Math.min(100,(cursor-config.start_ms)/(config.end_ms-config.start_ms)*100));
}
export class BrowserEngine{
  async validate(definition){
    const m=await material(),worker=new Worker('financial-worker.js?sha256='+m.financialHash);
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{worker.terminate();reject(Error('Validation initialization timeout'));},15000);
      worker.onmessage=({data})=>{if(['validated','fatal'].includes(data.type)){clearTimeout(timer);worker.terminate();data.type==='validated'?resolve(data.value):reject(Error(data.error));}};
      worker.onerror=e=>{clearTimeout(timer);worker.terminate();reject(Error(e.message));};
      worker.postMessage({type:'BOOT',validate:definition,kernel:m.kernel,channel:new SharedArrayBuffer(16+65536)});
    });
  }
  async run(bundle,onProgress=()=>{},options={}){
    if(!crossOriginIsolated||typeof SharedArrayBuffer==='undefined')throw Error('COOP/COEP headers required; no unsafe fallback');
    this.cancelled=false;const m=await material(),started=performance.now();
    this.sandbox=new SandboxClient();
    const scheduling={chunks:0,checkpoints:0,callbackMs:0,callbackPythonMs:0,strategySnapshotMs:0,checkpointPersistenceMs:0,worstCheckpointPersistenceMs:0};
    const initializing=performance.now();
    try{
      await this.sandbox.init(bundle.definition.code);
      if(this.cancelled)throw Error('Cancelled by user');
      if(options.resume)await this.sandbox.control('RESTORE',options.resume.strategy);
    }catch(e){this.stop();throw e;}
    scheduling.sandboxInitializationMs=performance.now()-initializing;
    this.worker=new Worker('financial-worker.js?sha256='+m.financialHash);
    const shared=new SharedArrayBuffer(16+65536),control=new Int32Array(shared,0,4),out=new Uint8Array(shared,16);
    return new Promise((resolve,reject)=>{
      let chunkTimer,wholeTimer,closed=false,restoredCalls=0;
      const fail=e=>{if(closed)return;closed=true;clearTimeout(chunkTimer);clearTimeout(wholeTimer);this.stop();reject(e instanceof Error?e:Error(String(e)));};
      const arm=()=>{clearTimeout(chunkTimer);chunkTimer=setTimeout(()=>fail(Error('30-second chunk deadline exceeded; resume last verified checkpoint')),32000);};
      const next=()=>{arm();this.worker?.postMessage({type:'NEXT'});};
      wholeTimer=setTimeout(()=>fail(Error('One-hour foreground job limit exceeded; latest checkpoint preserved')),3600000);
      this.reject=fail;arm();
      this.worker.onmessage=async({data})=>{
        if(closed)return;
        try{
          if(data.type==='call'){
            const callbackStarted=performance.now();
            let answer;try{answer=await this.sandbox.step(data.frame);}catch(e){answer=JSON.stringify({error:e.message});}
            scheduling.callbackMs+=performance.now()-callbackStarted;scheduling.callbackPythonMs+=this.sandbox.lastStepMs||0;
            if(closed||!this.worker)return;
            const encoded=new TextEncoder().encode(answer);
            if(encoded.length>65536)throw Error('Decision reply exceeds 64KiB');
            out.set(encoded);Atomics.store(control,1,encoded.length);Atomics.store(control,0,1);Atomics.notify(control,0);
            if(data.seq%100===0)onProgress({calls:data.seq+restoredCalls});
          }else if(data.type==='loaded'){
            restoredCalls=data.loaded.restored_calls||0;
            onProgress({calls:restoredCalls,next_ms:data.loaded.next_ms,resumed:!!options.resume});next();
          }else if(data.type==='progress'){
            clearTimeout(chunkTimer);scheduling.chunks++;
            onProgress({calls:data.metrics.calls,next_ms:data.next_ms,metrics:data.metrics});next();
          }
          else if(data.type==='checkpoint'){
            clearTimeout(chunkTimer);scheduling.chunks++;scheduling.checkpoints++;
            const snapshotStarted=performance.now();
            const state=await this.sandbox.control('SNAPSHOT');
            scheduling.strategySnapshotMs+=performance.now()-snapshotStarted;
            if(closed)return;
            const persistenceStarted=performance.now();
            await options.onCheckpoint?.({finance:data.snapshot,strategy:state.checkpoint});
            const persistenceMs=performance.now()-persistenceStarted;scheduling.checkpointPersistenceMs+=persistenceMs;
            scheduling.worstCheckpointPersistenceMs=Math.max(scheduling.worstCheckpointPersistenceMs,persistenceMs);
            if(closed)return;
            onProgress({calls:data.metrics.calls,next_ms:data.snapshot.next_ms,checkpoint:true,metrics:data.metrics});
            next();
          }else if(data.type==='fatal')fail(Error(data.error));
          else if(data.type==='done'){
            closed=true;clearTimeout(chunkTimer);clearTimeout(wholeTimer);
            const metrics={...data.metrics,scheduling,wallMs:performance.now()-started,strategyWasmBytes:this.sandbox.lastWasmBytes||this.sandbox.info.wasmBytes,resumed:!!options.resume};
            this.stop();resolve({...data.value,metrics,scope:'TRUSTED-CODE BROWSER REPLAY; NOT OS-CONTAINER ISOLATION'});
          }
        }catch(e){fail(e);}
      };
      this.worker.onerror=e=>fail(Error(e.message));
      this.worker.postMessage({type:'BOOT',bundle,kernel:m.kernel,channel:shared,resume:options.resume});
    });
  }
  stop(){this.worker?.terminate();this.worker=null;this.sandbox?.stop();}
  cancel(){this.cancelled=true;const e=Error('Cancelled by user; latest verified checkpoint retained');if(this.reject)this.reject(e);else this.sandbox?.stop(e);this.stop();}
}
