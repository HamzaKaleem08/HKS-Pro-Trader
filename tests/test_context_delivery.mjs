import assert from 'node:assert/strict';
import test from 'node:test';
import {verifiedBytes,assertContextAPI,CONTEXT_CONTRACT} from '../web/runtime-integrity.js';

const bytes=new TextEncoder().encode('verified runtime');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
test('pre-fix worker ready is rejected before on_bar execution',()=>{
 assert.throws(()=>assertContextAPI({type:'ready',origin:'null',python:'3.12'},hash),/Outdated Sandbox Context API/);
});
test('only matching Context contract, timeframes and runtime identity are accepted',()=>{
 const info={contextContract:CONTEXT_CONTRACT,contextTimeframes:['15m','1h'],runtimeManifest:hash};
 assert.doesNotThrow(()=>assertContextAPI(info,hash));
 for(const changed of [{contextContract:'old'},{contextTimeframes:['1h']},{runtimeManifest:'old'}])
  assert.throws(()=>assertContextAPI({...info,...changed},hash),/Outdated Sandbox/);
});
test('verified runtime requests carry the exact content identity and disable HTTP cache reuse',async()=>{
 let request;
 const actual=await verifiedBytes('strategy-worker.js',hash,async(url,options)=>{
  request={url,options};return new Response(bytes);
 });
 assert.equal(request.url,'strategy-worker.js?sha256='+hash);assert.equal(request.options.cache,'no-store');
 assert.deepEqual(new Uint8Array(actual),bytes);
});
test('old cached bytes cannot execute under a new runtime checksum',async()=>{
 await assert.rejects(verifiedBytes('strategy-worker.js',hash,async()=>new Response('old worker without candles')),/checksum mismatch/);
});
test('missing runtime asset and invalid pin fail closed',async()=>{
 await assert.rejects(verifiedBytes('kernel.json',hash,async()=>new Response('missing',{status:404})),/HTTP 404/);
 await assert.rejects(verifiedBytes('kernel.json','invalid',async()=>new Response(bytes)),/Invalid pinned/);
});
test('new bootstrap and module URLs are pinned consistently by the actual build',async()=>{
 const {readFile}=await import('node:fs/promises');
 const sha=async n=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await readFile(new URL('../web/'+n,import.meta.url)))),b=>b.toString(16).padStart(2,'0')).join('');
 const read=n=>readFile(new URL('../web/'+n,import.meta.url),'utf8');
 assert.ok((await read('index.html')).includes('boot.js?sha256='+await sha('boot.js')));
 assert.ok((await read('boot.js')).includes('app.js?sha256='+await sha('app.js')));
 assert.ok((await read('app.js')).includes('client.js?sha256='+await sha('client.js')));
 assert.ok((await read('client.js')).includes(await sha('runtime-manifest.json')));
 const m=JSON.parse(await read('runtime-manifest.json'));
 for(const [name,expected]of Object.entries(m.assets))assert.equal(await sha(name),expected,name);
});
test('offline versioned entry and extensionless Pages documents use their verified cached HTML',async()=>{
 const {readFile}=await import('node:fs/promises');const vm=await import('node:vm');const handlers={};let requested;
 const cached={verified:true};const origin='https://hks-pro-trader-browser-staging.pages.dev';
 const sandbox={self:{addEventListener:(name,fn)=>handlers[name]=fn},URL,location:{origin},
  caches:{open:async()=>({match:async key=>{requested=key;return cached;}})},fetch:async()=>{throw Error('offline');}};
 vm.runInNewContext(await readFile(new URL('../web/sw.js',import.meta.url),'utf8'),sandbox);
 for(const [path,key]of [['/?sandbox=completed-context-v2','/'],['/index?version=2','/index.html'],['/sandbox?sha256=abc','/sandbox.html']]){
  let result;handlers.fetch({request:{url:origin+path,method:'GET',mode:'navigate'},respondWith:p=>result=p});
  assert.equal(await result,cached);assert.equal(requested,origin+key);
 }
});
