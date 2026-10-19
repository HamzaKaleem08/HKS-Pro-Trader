import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {BrowserEngine,SandboxClient,replayProgress} from '../web/client.js';

test('resume progress uses the verified cursor, including zero and warm-up boundaries',()=>{
 const config={start_ms:60000,end_ms:660000};
 assert.equal(replayProgress(360000,config),50);
 assert.equal(replayProgress(0,config),0);
 assert.equal(replayProgress(720000,config),100);
 assert.equal(replayProgress(undefined,config),0);
 assert.equal(replayProgress(NaN,config),0);
 assert.equal(replayProgress(100,{start_ms:100,end_ms:100}),0);
});

test('work-only yields advance before another NEXT without persisting a fake checkpoint',async()=>{
 const old={Worker:globalThis.Worker,fetch:globalThis.fetch,crossOriginIsolated:globalThis.crossOriginIsolated,
   init:SandboxClient.prototype.init,control:SandboxClient.prototype.control};
 const actions=[],progress=[];let nexts=0;
 globalThis.crossOriginIsolated=true;
 globalThis.fetch=async name=>new Response(await readFile(new URL('../web/'+String(name).split('?')[0],import.meta.url)));
 SandboxClient.prototype.init=async function(){this.info={wasmBytes:1};return this.info;};
 SandboxClient.prototype.control=async function(type){actions.push(type);return {checkpoint:'synthetic-state'};};
 globalThis.Worker=class{
  terminate(){actions.push('terminate');}
  postMessage(data){
   if(data.type==='BOOT'){actions.push('BOOT');queueMicrotask(()=>this.onmessage({data:{type:'loaded',loaded:{next_ms:180000,restored_calls:7}}}));}
   if(data.type==='NEXT'){
    actions.push('NEXT');nexts++;
    if(nexts===1)queueMicrotask(()=>this.onmessage({data:{type:'progress',next_ms:240000,metrics:{calls:9}}}));
    if(nexts===2)queueMicrotask(()=>this.onmessage({data:{type:'checkpoint',snapshot:{next_ms:300000},metrics:{calls:11}}}));
    if(nexts===3)queueMicrotask(()=>this.onmessage({data:{type:'done',value:{result:{synthetic:true}},metrics:{calls:13}}}));
   }
  }
 };
 try{
  const answer=await new BrowserEngine().run({definition:{code:'synthetic unit stub'}},p=>progress.push(p),{
   resume:{finance:{next_ms:180000},strategy:'state'},onCheckpoint:async x=>{
    assert.equal(x.finance.next_ms,300000);actions.push('persist-start');
    await new Promise(r=>setTimeout(r,2));actions.push('persist-done');
   }});
  assert.deepEqual(progress.map(p=>p.next_ms),[180000,240000,300000]);
  assert.equal(progress[0].calls,7);assert.equal(progress[0].resumed,true);
  assert.equal(answer.metrics.scheduling.checkpoints,1);
  assert.equal(answer.metrics.scheduling.chunks,2);
  assert.deepEqual(actions.slice(0,3),['RESTORE','BOOT','NEXT']);
  assert.ok(actions.indexOf('persist-done')<actions.lastIndexOf('NEXT'));
 }finally{
  globalThis.Worker=old.Worker;globalThis.fetch=old.fetch;globalThis.crossOriginIsolated=old.crossOriginIsolated;
  SandboxClient.prototype.init=old.init;SandboxClient.prototype.control=old.control;
 }
});
