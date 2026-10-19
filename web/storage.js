const DB='hks-pro-trader-static-v1';
const encoder=new TextEncoder();
export async function sha256(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');}
function request(q){return new Promise((resolve,reject)=>{q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});}
export class CandleStore{
  async init(forceIDB=false){
    const q=indexedDB.open(DB,1);
    q.onupgradeneeded=()=>{for(const n of ['datasets','blobs','jobs','settings','versions'])q.result.createObjectStore(n,{keyPath:'id'});};
    this.db=await request(q);this.opfs=null;
    if(!forceIDB && navigator.storage?.getDirectory)try{this.opfs=await navigator.storage.getDirectory();}catch{}
    this.backend=this.opfs?'OPFS + IndexedDB metadata':'IndexedDB';return this;
  }
  async get(table,id){return request(this.db.transaction(table).objectStore(table).get(id));}
  async all(table){return request(this.db.transaction(table).objectStore(table).getAll());}
  async put(table,value){
    const tx=this.db.transaction(table,'readwrite');tx.objectStore(table).put(value);
    return new Promise((resolve,reject)=>{tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Storage transaction aborted'));});
  }
  async saveDataset(id,raw,expected,metadata={}){
    const hash=await sha256(raw);if(hash!==expected)throw Error('Dataset SHA-256 mismatch; import rejected');
    if(await this.get('datasets',id)){
      const old=await this.readDataset(id);if(old.hash!==hash)throw Error('Dataset ID already names different bytes');
      return {reused:true,hash};
    }
    if(this.opfs){
      const file=await this.opfs.getFileHandle(hash+'.gz',{create:true});const stream=await file.createWritable();
      try{await stream.write(raw);await stream.close();}catch(e){await stream.abort().catch(()=>{});throw e;}
      const verified=await (await file.getFile()).arrayBuffer();if(await sha256(verified)!==hash)throw Error('OPFS read-back hash mismatch');
    }else await this.put('blobs',{id:hash,bytes:raw});
    await this.put('datasets',{...metadata,id,hash,bytes:raw.byteLength,backend:this.opfs?'OPFS':'IDB'});
    return {reused:false,hash};
  }
  async readDataset(id){
    const meta=await this.get('datasets',id);if(!meta)throw Error('Dataset not cached on this device');
    let bytes;
    try{
      bytes=meta.backend==='OPFS'?await (await (await this.opfs.getFileHandle(meta.hash+'.gz')).getFile()).arrayBuffer():(await this.get('blobs',meta.hash)).bytes;
    }catch{throw Error('Cached file missing or evicted; restore original verified dataset');}
    if(await sha256(bytes)!==meta.hash)throw Error('Local cache corrupted; no backtest accepted');
    return {...meta,bytes};
  }
  async bundle(id){const {bytes}=await this.readDataset(id);return JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());}
  async saveCheckpoint(job,snapshot){
    const text=JSON.stringify({schema:1,job:job.id,identity:job.identity,snapshot});
    if(new TextEncoder().encode(text).length>64*1024**2)throw Error('64MiB checkpoint expansion limit exceeded');
    const bytes=await new Response(new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer();
    if(bytes.byteLength>16*1024**2)throw Error('16MiB compressed checkpoint limit exceeded');
    const hash=await sha256(bytes),name='checkpoint-'+hash+'.gz';
    if(this.opfs){const h=await this.opfs.getFileHandle(name,{create:true});const w=await h.createWritable();try{await w.write(bytes);await w.close();}catch(e){await w.abort().catch(()=>{});throw e;}if(await sha256(await (await h.getFile()).arrayBuffer())!==hash)throw Error('Checkpoint read-back hash mismatch');}
    else await this.put('blobs',{id:name,bytes});
    const latest={...job,checkpoint:{hash,bytes:bytes.byteLength,name,backend:this.opfs?'OPFS':'IDB',next_ms:snapshot.finance.next_ms},previousCheckpoint:job.checkpoint};
    await this.put('jobs',latest); // pointer commits only after complete read-back
    if(job.previousCheckpoint){const old=job.previousCheckpoint.name;try{if(this.opfs)await this.opfs.removeEntry(old);else{const t=this.db.transaction('blobs','readwrite');t.objectStore('blobs').delete(old);}}catch{}}
    return latest;
  }
  async checkpoint(job){
    const p=job.checkpoint;if(!p)throw Error('No completed checkpoint; start a new test explicitly');
    const bytes=p.backend==='OPFS'?await (await (await this.opfs.getFileHandle(p.name)).getFile()).arrayBuffer():(await this.get('blobs',p.name)).bytes;
    if(await sha256(bytes)!==p.hash)throw Error('Checkpoint SHA-256 mismatch; resume rejected');
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    const reader=stream.getReader(),chunks=[];let size=0;
    while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>64*1024**2){await reader.cancel();throw Error('Checkpoint expansion bound exceeded');}chunks.push(value);}
    const raw=JSON.parse(await new Blob(chunks).text());
    if(raw.schema!==1||raw.job!==job.id||raw.identity!==job.identity)throw Error('Checkpoint identity mismatch');
    return raw.snapshot;
  }
  async recover(){
    if(!navigator.locks)throw Error('Web Locks required for safe single-device replay');
    await navigator.locks.request('hks-pro-trader-runner',{ifAvailable:true},async lock=>{
      if(!lock)return;
      for(const j of await this.all('jobs'))if(j.status==='RUNNING')await this.put('jobs',{...j,status:'INTERRUPTED',error:j.checkpoint?'Interrupted; verified checkpoint available. Resume explicitly.':'Interrupted before first checkpoint; no completed result.'});
    });
  }
}
