import {CandleStore,sha256} from './storage.js';
import {BrowserEngine,SandboxClient,runtimeIdentity,replayProgress} from './client.js?sha256=7d61335b4336ab631be1d5e6bb1baccd967de442b14eded4054747e285ccf7ea';
import {assertReplayConsent,FUTURES_CONSENT_ID,consentPreference,savedConsent} from './replay-consent.js';
const $=id=>document.getElementById(id),store=await new CandleStore().init();
const text=(id,v)=>$(id).textContent=String(v??'—'),money=v=>v==null?'—':'$'+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const number=v=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:4});
const utc=v=>v==null?'—':new Date(v).toISOString().replace('T',' ').replace('.000Z',' UTC'),inputUTC=v=>new Date(v).toISOString().slice(0,16);
const message=v=>text('message',v);
const catalog=await(await fetch('catalog.json')).json(),months=await(await fetch('candle-catalog.json')).json();
let selected=new Set(['BTCUSDT','ETHUSDT']),period='custom',running=false,engine,job,currentResult,currentAnswer,page=1,abort;
const runtimePins=await runtimeIdentity();
let watchlist=[...months.map(x=>x.symbol)].sort(),sourceHash=await sha256(new TextEncoder().encode(JSON.stringify(runtimePins)));
const handle=fn=>async e=>{e?.preventDefault();try{await fn(e);}catch(err){message(err.message);}};
function consentStatus(){text('consentState',$('diagnostic').checked
 ? 'Diagnostic Futures consent ON · 1× fully reserved capital · LONG / SHORT supported. This acknowledgement is remembered on this browser only.'
 : 'Diagnostic Futures consent OFF · Check the box above before Run. Funding, historical filters and liquidation remain uncertified.');}
function table(id,labels,rows){
 const head=document.createElement('thead'),tr=document.createElement('tr'),body=document.createElement('tbody');
 for(const t of labels){const th=document.createElement('th');th.textContent=t;tr.append(th);}head.append(tr);
 for(const row of rows){const r=document.createElement('tr');for(const v of row){const td=document.createElement('td');if(v instanceof Node)td.append(v);else td.textContent=String(v??'—');r.append(td);}body.append(r);}
 $(id).replaceChildren(head,body);
}
function lines(){text('lineNumbers',$('definition').value.split('\n').map((_,i)=>i+1).join('\n'));}
function definition(){return {schema_version:1,kind:'PYTHON_STRATEGY',name:$('strategyName').value.trim()||'My Python strategy',code:$('definition').value};}
function setDefinition(d){$('strategyName').value=d.name;$('definition').value=d.code;lines();}
function settings(){return {start_ms:Date.parse($('start').value+'Z'),end_ms:Date.parse($('end').value+'Z'),mode:$('mode').value,initial_capital:$('capital').value,fee_bps:$('fees').value,slippage_bps:$('slippage').value,risk_fraction:$('risk').value,max_positions:Number($('maxPositions').value),end_policy:$('endPolicy').value,allow_uncertified_futures:$('diagnostic').checked};}
function request(){return {source:$('dataset').value,definition:definition(),symbols:[...selected].sort(),config:settings(),interval:'1m'};}
function applyRequest(r){
 $('dataset').value=r.source;setDefinition(r.definition);selected=new Set(r.symbols);
 const c=r.config;for(const [id,key]of [['capital','initial_capital'],['fees','fee_bps'],['slippage','slippage_bps'],['risk','risk_fraction'],['maxPositions','max_positions'],['endPolicy','end_policy'],['mode','mode']])$(id).value=c[key];
 $('start').value=inputUTC(c.start_ms);$('end').value=inputUTC(c.end_ms);renderCoins();coverage();consentStatus();
}
function available(){return $('dataset').value==='binance-november-2025'?months.map(x=>x.symbol):[];}
function renderCoins(){
 $('coins').replaceChildren();const allowed=new Set(available());
 for(const s of new Set([...watchlist,...selected])){const b=document.createElement('button');b.type='button';b.className='coin'+(selected.has(s)?' selected':'');b.textContent=s.replace(/USDT$/,'');b.setAttribute('aria-pressed',String(selected.has(s)));b.disabled=$('dataset').value==='binance-november-2025'&&!allowed.has(s);b.title=b.disabled?'No verified coverage':s;b.onclick=()=>{selected.has(s)?selected.delete(s):selected.add(s);$('universe').value='custom';renderCoins();coverage();};$('coins').append(b);}
}
function coverage(){
 const isMonth=$('dataset').value==='binance-november-2025';
 const rows=months.filter(m=>selected.has(m.symbol));
 text('datasetInfo',isMonth?'BINANCE · USD-M USDT perpetual Futures · genuine November 2025 1m · 20 symbols':'SYNTHETIC / genuine parity fixture: label shown in dataset name and report');
 const bars=Math.ceil((settings().end_ms-settings().start_ms)/60000)*selected.size;
 text('coverage',isMonth?selected.size+' selected · '+number(bars)+' requested candles, plus exact warm-up. Limit: 200,000 total candles / 32MiB CSV / 10,000 entries. A failed or oversized request is rejected, never shortened.':'Fixture boundaries and exact warm-up remain verified by the original Python loader.');
 for(const b of document.querySelectorAll('[data-period]')){
  const d=b.dataset.period;b.disabled=!isMonth||!['3','custom'].includes(d);b.title=b.disabled?'Unavailable: required warm-up or long-history streaming is not validated':'';
 }
 if(rows.length&&isMonth)text('cacheState','Local verified cache is reused. Cold requests fetch selected chunks once. No Spot substitution.');
}
async function storageStatus(){
 const q=await navigator.storage.estimate();text('storageInfo',JSON.stringify({backend:store.backend,usage_bytes:q.usage,quota_bytes:q.quota,persistence_granted:await navigator.storage.persisted(),scope:'THIS browser profile only; device eviction/clear-site-data can remove files. Export important reports. No cloud account synchronization.',source:'Original official monthly ZIP hashes remain in candle-catalog.json; original retrieval dates are unknown where not supplied.'},null,2));
 const cached=new Set((await store.all('datasets')).map(x=>x.id));
 table('coverageTable',['Symbol / market','First UTC','Last complete UTC','1m candles','Device cache / SHA256'],months.map(m=>[m.symbol+' · USD-M Futures',utc(m.start_ms),utc(m.end_ms),m.candles,(cached.has(m.id)?'Verified locally · ':'Not cached · ')+m.sha256.slice(0,16)]));
}
async function cache(entry){
 if(await store.get('datasets',entry.id)){await store.readDataset(entry.id);return {reused:true};}
 const r=await fetch(entry.url,{signal:abort?.signal});if(!r.ok)throw Error('Source HTTP '+r.status+': '+entry.id);
 const raw=await r.arrayBuffer();if(raw.byteLength!==entry.bytes)throw Error('Source byte count mismatch: '+entry.id);
 return store.saveDataset(entry.id,raw,entry.sha256,{...entry,kind:entry.symbol?'candles':'fixture'});
}
async function cacheAll(){
 let downloaded=0,reused=0;for(const m of months){const r=await cache(m);r.reused?reused++:downloaded++;text('cacheProgress',(downloaded+reused)+'/20 · '+reused+' reused');}
 await storageStatus();return {downloaded,reused};
}
async function fixture(id){const e=catalog.find(x=>x.id===id);if(!e)throw Error('Unknown pinned fixture');await cache(e);return store.bundle(id);}
async function selection(){
 if($('dataset').value==='binance-november-2025'){
  selected=new Set(['BTCUSDT','ETHUSDT']);$('start').value='2025-11-02T00:00';$('end').value='2025-11-03T00:00';
 }else{
  const b=await fixture($('dataset').value);setDefinition(b.definition);selected=new Set(b.manifest.files.map(x=>x.symbol));$('start').value=inputUTC(b.config.start_ms);$('end').value=inputUTC(b.config.end_ms);$('mode').value=b.config.mode;
  for(const [id,key]of [['capital','initial_capital'],['fees','fee_bps'],['slippage','slippage_bps'],['risk','risk_fraction'],['maxPositions','max_positions'],['endPolicy','end_policy']])if(b.config[key]!==undefined)$(id).value=b.config[key];
  // Dataset metadata is not user consent; keep the user's explicit choice.
 }
 renderCoins();coverage();
}
async function* csvLines(bytes){
 const reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).pipeThrough(new TextDecoderStream()).getReader();let buffer='',total=0;
 try{while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>16*1024**2)throw Error('16MiB expanded source bound');buffer+=value;let i;while((i=buffer.indexOf('\n'))>=0){yield buffer.slice(0,i).replace(/\r$/,'');buffer=buffer.slice(i+1);}}if(buffer)yield buffer;}
 finally{await reader.cancel().catch(()=>{});}
}
async function compose(req,spec){
 if(req.interval!=='1m')throw Error('Only verified 1m execution is supported in this release');
 if(!req.symbols.length||req.symbols.length>20)throw Error('Select 1–20 available symbols');
 if(!Number.isFinite(req.config.start_ms)||!Number.isFinite(req.config.end_ms)||req.config.end_ms<=req.config.start_ms)throw Error('Valid aligned UTC start/end required');
 if(req.config.start_ms%60000||req.config.end_ms%60000)throw Error('UTC boundaries must align to 1m');
 if(req.source!=='binance-november-2025'){
  const b=await fixture(req.source);if(JSON.stringify([...b.manifest.files.map(f=>f.symbol)].sort())!==JSON.stringify(req.symbols))throw Error('Fixture symbol selection must match its pinned manifest');
  return {...b,definition:req.definition,config:req.config,checkpoint_every:120};
 }
 const entries=req.symbols.map(s=>{const m=months.find(x=>x.symbol===s);if(!m)throw Error(s+': no verified cached source');return m;});
 const inputWarmup=spec.input_warmup_bars??spec.warmup_bars;
 const first=req.config.start_ms-inputWarmup*60000,last=req.config.end_ms;
 const per=(last-first)/60000;
 if(!Number.isInteger(per)||per*entries.length>200000)throw Error('200,000-candle browser limit exceeded. Four-year replay is not validated; request a smaller explicit range.');
 let total=0;const files={},records=[];
 for(const e of entries){
  if(abort?.signal.aborted)throw Error('Cancelled by user during input preparation');
  if(e.start_ms>first||e.end_ms<last)throw Error(e.symbol+': required period plus '+inputWarmup+' warm-up candles unavailable; request rejected without shortening.');
  text('jobStage','Preparing verified local candles · '+e.symbol);await cache(e);
  const d=await store.readDataset(e.id);let header=true,previous=null,count=0;const lines=[];
  for await(const line of csvLines(d.bytes)){
   if(header){if(line!=='open_time,open,high,low,close,volume')throw Error('Invalid normalized CSV header');header=false;lines.push(line);continue;}
   if(!line)continue;const row=line.split(','),ts=Number(row[0]);
   if(row.length!==6||!Number.isSafeInteger(ts)||ts%60000||previous!==null&&ts!==previous+60000)throw Error(e.symbol+': chronology/gap/CSV mismatch');previous=ts;
   if(ts>=first&&ts<last){lines.push(line);count++;}
  }
  if(count!==per)throw Error(e.symbol+': incomplete requested range');
  const content=lines.join('\n')+'\n',raw=new TextEncoder().encode(content);total+=raw.byteLength;
  if(raw.byteLength>16*1024**2||total>32*1024**2)throw Error('CSV input size bound exceeded; no partial replay');
  const name=e.symbol+'.csv';files[name]=content;records.push({symbol:e.symbol,file:name,sha256:await sha256(raw)});
 }
 return {id:'browser-request',manifest:{schema_version:1,dataset_id:'browser_verified_binance',exchange:'BINANCE',market:'USDT_LINEAR_PERPETUAL',interval:'1m',synthetic:false,source:'Official Binance USD-M November 2025 monthly archives; original ZIP hashes pinned in candle-catalog.json; normalized subset selected causally.',retrieved_at:null,files:records},files,definition:req.definition,config:req.config,checkpoint_every:120};
}
async function saveVersion(d){
 const spec=await new BrowserEngine().validate(d),old=await store.get('versions',spec.version_id);
 if(old&&JSON.stringify(old.definition)!==JSON.stringify(spec.definition))throw Error('Immutable version collision');
 if(!old)await store.put('versions',{id:spec.version_id,...spec,created:Date.now()});
 await versions(spec.version_id);return spec;
}
async function versions(pick){
 $('versions').replaceChildren(new Option('Saved immutable versions',''));
 for(const v of await store.all('versions'))$('versions').append(new Option(v.definition.name+' · '+v.content_hash.slice(0,12),v.id));
 if(pick)$('versions').value=pick;
}
async function history(){
 $('history').replaceChildren();const jobs=(await store.all('jobs')).sort((a,b)=>b.created-a.created);
 for(const j of jobs){const b=document.createElement('button');b.className='subtle-button';b.textContent=utc(j.created)+' · '+j.status+' · '+j.request.config.mode+' · '+j.request.symbols.join(', ')+(j.checkpoint?' · checkpoint '+utc(j.checkpoint.next_ms):'')+(j.error?' · '+j.error:'');b.onclick=handle(()=>showJob(j.id));$('history').append(b);}
 if(!jobs.length)text('history','No computed tests on this device.');
}
function busy(value){running=value;for(const id of ['runButton','saveStrategy','validate','cacheAll','versions','dataset','restore','diagnostic'])$(id).disabled=value;$('cancel').disabled=!value;}
function clearResult(){currentResult=null;currentAnswer=null;$('result').hidden=true;for(const id of ['pnlStat','returnStat','equityStat','capitalStat','winStat','tradeCount','ddStat'])text(id,'—');for(const id of ['exportTrades','exportCoins','downloadEquity'])$(id).disabled=true;}
async function report(j){const d=await store.readDataset(j.report);return JSON.parse(await new Response(new Blob([d.bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());}
async function showJob(id){
 if(running)throw Error('Wait for the running job or cancel before changing reports');job=await store.get('jobs',id);clearResult();
 text('jobStage',job.status+(job.error?' · '+job.error:''));$('retry').disabled=!job.checkpoint||job.status==='COMPLETE'||job.sourceHash!==sourceHash;
 $('jobProgress').value=job.status==='COMPLETE'?100:replayProgress(job.checkpoint?.next_ms,job.request.config);
 if(job.sourceHash&&job.sourceHash!==sourceHash){$('retry').disabled=true;message('This saved job uses an older runtime identity. Its report and checkpoint are preserved; resume requires the original verified build. Start a new test explicitly to use this build.');}
 if(job.status==='COMPLETE'){currentAnswer=await report(job);currentResult={...currentAnswer.result,...currentAnswer.view};renderResult(currentResult);page=1;renderTrades();}
}
async function run(resumeId=null,override=null){
 if(running)throw Error('A replay is already running');if(!$('trusted').checked&&!override)throw Error('Confirm this Python source is trusted before running');
 await navigator.locks.request('hks-pro-trader-runner',{ifAvailable:true},async lock=>{
  if(!lock)throw Error('Another tab is running this device workspace; no concurrent duplicate execution');
  busy(true);clearResult();$('retry').disabled=true;abort=new AbortController();let j,prepared=false;
  try{
   const req=resumeId?(await store.get('jobs',resumeId)).request:override?null:request();
   const consent=override?override.config.allow_uncertified_futures:$('diagnostic').checked;
   // Fail before async validation/preparation can leave a stale checkbox on
   // screen. A resume uses its original immutable request, never edited UI data.
   if(req&&(req.source==='binance-november-2025'||catalog.some(c=>c.id===req.source&&!c.synthetic)))
    assertReplayConsent(req.config,'USDT_LINEAR_PERPETUAL',consent,!!resumeId);
   if(!override)await store.put('settings',consentPreference(consent));
   message(resumeId?'Verifying saved source/data/checkpoint before resuming…':'Preparing a real local Python replay. No orders or activation.');
   const spec=await saveVersion(override?override.definition:req.definition);
   const bundle=override||await compose(req,spec);if(abort.signal.aborted)throw Error('Cancelled by user during input preparation');
   assertReplayConsent(bundle.config,bundle.manifest.market,consent,!!resumeId);
   const identity=await sha256(new TextEncoder().encode(JSON.stringify({sourceHash,bundle})));
   let checkpoint;
   if(resumeId){j=await store.get('jobs',resumeId);if(j.identity!==identity)throw Error('Source, settings or input identity changed; old checkpoint cannot resume. Saved data is preserved; use the original verified build or start a new test explicitly.');checkpoint=await store.checkpoint(j);}
   else j={id:crypto.randomUUID(),created:Date.now(),request:req||{source:override.id,definition:override.definition,symbols:override.manifest.files.map(x=>x.symbol).sort(),config:override.config,interval:'1m'},identity,sourceHash};
   job={...j,status:'RUNNING',error:null};await store.put('jobs',job);prepared=true;
   text('jobStage',checkpoint?'RUNNING · restoring verified cursor '+utc(checkpoint.finance.next_ms):'RUNNING · starting isolated browser workers');
   $('jobProgress').value=replayProgress(checkpoint?.finance.next_ms,bundle.config);
   engine=new BrowserEngine();
   const answer=await engine.run(bundle,p=>{
    const progress=Number.isFinite(p.next_ms)?replayProgress(p.next_ms,bundle.config):$('jobProgress').value;
    $('jobProgress').value=progress;text('jobStage','RUNNING · '+p.calls.toLocaleString()+' callbacks'+(p.checkpoint?' · checkpoint saved '+utc(p.next_ms):''));
   },{resume:checkpoint,onCheckpoint:async snapshot=>{job=await store.saveCheckpoint(job,snapshot);window.dispatchEvent(new CustomEvent('hks-checkpoint',{detail:{job:job.id,next_ms:snapshot.finance.next_ms}}));}});
   const raw=JSON.stringify(answer);if(new TextEncoder().encode(raw).length>64*1024**2)throw Error('64MiB completed report bound exceeded; no incomplete success');
   const packed=await new Response(new Blob([raw]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer(),hash=await sha256(packed),ref='report-'+job.id;
   await store.saveDataset(ref,packed,hash,{kind:'report'});await store.readDataset(ref);
   job={...job,status:'COMPLETE',report:ref,report_sha256:hash,metrics:answer.metrics,completed:Date.now()};await store.put('jobs',job);
   await store.put('settings',{id:'last-success',job:job.id,request:job.request});
   currentAnswer=answer;currentResult={...answer.result,...answer.view};renderResult(currentResult);page=1;renderTrades();$('jobProgress').value=100;
   text('jobStage','COMPLETE · '+(answer.metrics.wallMs/1000).toFixed(2)+'s · '+answer.metrics.calls+' callbacks'+(answer.metrics.resumed?' · resumed verified state':''));message('COMPLETE · '+answer.result.label+'. Funding/exchange filters are not certified. Browser trusted-code execution only.');return answer;
  }catch(e){
   if(prepared&&job?.status==='RUNNING'){job={...job,status:/Cancel|abort/i.test(e.message)?'CANCELLED':'FAILED',error:e.message};await store.put('jobs',job);}
   text('jobStage',(prepared?job.status:'REJECTED')+' · '+e.message);message(e.message);throw e;
  }finally{busy(false);engine=null;abort=null;$('retry').disabled=!job?.checkpoint||job.status==='COMPLETE'||job.sourceHash!==sourceHash;await history();await storageStatus();}
 });
 return currentAnswer;
}

  function renderResult(r) {
    $('result').hidden=false;const s=r.reports.summary;
    for(const id of ['exportTrades','exportCoins','downloadEquity'])$(id).disabled=false;
    text('resultMeta',r.label+' · '+r.config.mode+' · '+r.symbols.join(', ')+' · '+utc(r.config.start_ms)+' → '+utc(r.config.end_ms));
    text('pnlStat',money(s.net_equity_change));text('returnStat',number(s.return_on_total_starting_capital_pct)+'% of total starting capital');
    text('equityStat',money(s.ending_equity));text('capitalStat',money(s.starting_capital)+' start · '+s.capital_scope);
    const p=r.position_performance;
    const win=p?p.win_rate_pct:s.win_rate_pct;
    text('winStat',number(win)+(win==null?'':'%'));text('tradeCount',(p?p.closed_positions+' closed positions · ':'')+s.closed_trades+' exit segments · '+s.open_trades+' open');text('ddStat',money(s.max_drawdown));
    $('costMetrics').replaceChildren();
    for(const [label,value] of [['Realized net PnL',s.realized_net_pnl],['Unrealized PnL',s.unrealized_pnl],['Fees (closed + open)',Number(s.fees_closed_trades)+Number(s.open_entry_fees)],['Slippage (already in PnL)',s.slippage_already_in_pnl],['Available cash',s.available_cash],['Reserved capital',s.reserved_capital],['Reserved risk',s.reserved_risk],['Mean MFE / MAE (%)',number(s.mean_mfe_pct)+' / '+number(s.mean_mae_pct)]]) {
      const wrapper=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=label.includes('MFE')?value:money(value);wrapper.append(dt,dd);$('costMetrics').append(wrapper);
    }
    table('coinResults',['Coin','Signals','Closed / open','Win rate','Net realized','Fees','MFE / MAE %','Rejected'],r.reports.coins.map(c=>[c.symbol,c.qualified_signals,c.closed_trades+' / '+c.open_trades,number(c.win_rate_pct),money(c.realized_net_pnl),money(c.fees_closed_trades),number(c.mean_mfe_pct)+' / '+number(c.mean_mae_pct),Object.entries(c.rejections).map(([k,v])=>k+': '+v).join('; ')]));
    text('metadata',JSON.stringify({strategy_version:r.strategy_version,strategy_hash:r.strategy_hash,strategy_definition:r.strategy_definition,dataset_hash:r.dataset_hash,input_hashes:r.input_hashes,result_hash:r.result_hash,config:r.config,accounts:r.accounts,position_performance:r.position_performance,open_positions:r.open_positions,reconciliation:r.reconciliation,exit_reasons:r.reports.exit_reasons,warnings:r.warnings,detailed_journals:r.detailed_journals},null,2));
    chart();
  }
  function chart() {
    if(!currentResult)return;const points=currentResult.chart_sample||[],canvas=$('equityChart'),bounds=canvas.getBoundingClientRect();
    canvas.width=Math.max(280,Math.floor(bounds.width*devicePixelRatio));canvas.height=210*devicePixelRatio;
    const c=canvas.getContext('2d');c.scale(devicePixelRatio,devicePixelRatio);const w=canvas.width/devicePixelRatio,h=210;
    c.clearRect(0,0,w,h);if(!points.length)return;
    const values=points.map(p=>Number(p.equity)),lo=Math.min(...values),hi=Math.max(...values),range=hi-lo||1;
    c.strokeStyle='#273644';c.lineWidth=1;c.font='10px sans-serif';c.fillStyle='#91a6b8';
    for(let i=0;i<4;i++){const y=16+i*55;c.beginPath();c.moveTo(55,y);c.lineTo(w-8,y);c.stroke();c.fillText(number(hi-i*(hi-lo)/3),1,y+4);}
    c.beginPath();points.forEach((p,i)=>{const x=55+i/Math.max(1,points.length-1)*(w-66),y=16+(hi-Number(p.equity))/range*165;i?c.lineTo(x,y):c.moveTo(x,y);});c.strokeStyle='#74edc1';c.lineWidth=2;c.stroke();
    text('chartDates',utc(points[0].timestamp_ms)+' → '+utc(points.at(-1).timestamp_ms));
  }
function renderTrades(){
 if(!currentResult)return;const query=$('search').value.toUpperCase().trim(),all=currentResult.trades.filter(t=>t.symbol.includes(query)),data=all.slice((page-1)*25,page*25);
 text('pageInfo','Page '+page+' / '+Math.max(1,Math.ceil(all.length/25))+' · '+all.length+' exit segments');$('previous').disabled=page<=1;$('next').disabled=page*25>=all.length;
 table('trades',['Symbol','Side','Entry UTC','Exit UTC','Net PnL','Fees','Minutes','Exit / detail'],data.map(t=>{
  const b=document.createElement('button');b.textContent=t.exit_reason;b.onclick=()=>{text('tradeDetail',JSON.stringify(t,null,2));$('tradeDialog').showModal();};
  return [t.symbol,t.side,utc(t.entry_ms),utc(t.exit_ms),money(t.net_pnl),money(t.fees),number(t.holding_ms/60000),b];
 }));
}
function exportCSV(rows,name){
 if(!rows.length){message('No records to export');return;}
 const columns=[...new Set(rows.flatMap(Object.keys))];
 const safe=v=>{let s=v==null?'':typeof v==='object'?JSON.stringify(v):String(v);if(/^[=+@\t\r\n-]/.test(s)&&!/^[-+]?\d+(?:\.\d+)?$/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
 const csv=[columns.map(safe).join(','),...rows.map(r=>columns.map(k=>safe(r[k])).join(','))].join('\r\n');
 const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function choosePeriod(value){
 period=value;for(const b of document.querySelectorAll('[data-period]'))b.classList.toggle('active',b.dataset.period===value);
 if(value==='custom')return;
 if(value!=='3')throw Error('This longer period is unavailable until complete data and bounded streaming are validated');
 let end=Date.parse($('end').value+'Z');
 // A preset chooses an explicit covered window; a submitted custom range is
 // never changed. Full strategy warm-up is still validated independently.
 if(end-3*86400000<months[0].start_ms+501*60000)end=months[0].end_ms;
 $('end').value=inputUTC(end);$('start').value=inputUTC(end-3*86400000);coverage();
}
$('dataset').addEventListener('change',handle(async()=>{$('runButton').disabled=true;try{await selection();}finally{$('runButton').disabled=running||!crossOriginIsolated;}}));$('definition').addEventListener('input',lines);$('definition').addEventListener('scroll',()=>{$('lineNumbers').scrollTop=$('definition').scrollTop;});
$('runForm').addEventListener('submit',handle(()=>run()));$('cancel').onclick=()=>{engine?.cancel();abort?.abort();};
$('diagnostic').addEventListener('change',handle(async()=>{consentStatus();await store.put('settings',consentPreference($('diagnostic').checked));}));
$('validate').onclick=handle(async()=>{const spec=await new BrowserEngine().validate(definition());message('Syntax and metadata valid · '+spec.version_id+' · '+(spec.input_warmup_bars??spec.warmup_bars)+' required pre-window 1m warm-up bars'+(spec.context_timeframes?' · completed 15m/1H context':'')+'. Runtime behavior is checked in the opaque browser worker. No activation.');});
$('saveStrategy').onclick=handle(async()=>{const spec=await saveVersion(definition());message('Saved immutable version '+spec.version_id+'. Last successful test remains unchanged.');});
$('versions').onchange=handle(async()=>{const v=await store.get('versions',$('versions').value);if(v)setDefinition(v.definition);});
$('restore').onclick=handle(async()=>{const s=await store.get('settings','last-success');if(!s)throw Error('No successful test saved on this browser');applyRequest(s.request);await showJob(s.job);message('Restored the last SUCCESSFULLY TESTED Python and settings. Saving drafts never replaces this record.');});
$('universe').onchange=()=>{if($('universe').value!=='custom')selected=new Set(watchlist.slice(0,Number($('universe').value)));renderCoins();coverage();};
$('saveWatchlist').onclick=handle(async()=>{const next=$('watchlist').value.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean);if(!next.length||next.length>20||new Set(next).size!==next.length||next.some(s=>!/^[A-Z0-9]{2,20}USDT$/.test(s)))throw Error('Use 1–20 distinct valid USDT symbols');watchlist=next;await store.put('settings',{id:'watchlist',symbols:next});renderCoins();coverage();message('Local watchlist saved. Unavailable symbols remain unavailable; no substitution.');});
$('cacheAll').onclick=handle(async()=>{const r=await cacheAll();message('Verified 20 monthly chunks · '+r.downloaded+' downloaded · '+r.reused+' reused.');});
$('persist').onclick=handle(async()=>{const granted=await navigator.storage.persist();await storageStatus();message('Device persistence request: '+(granted?'granted':'not granted; browser may evict data. Export important results.'));});
$('refresh').onclick=handle(async()=>{await history();await storageStatus();});
$('retry').onclick=handle(()=>run(job.id));
$('previous').onclick=()=>{page=Math.max(1,page-1);renderTrades();};$('next').onclick=()=>{page++;renderTrades();};$('search').oninput=()=>{page=1;renderTrades();};
$('exportTrades').onclick=()=>currentResult&&exportCSV(currentResult.trades,'HKS-trades.csv');$('exportCoins').onclick=()=>currentResult&&exportCSV(currentResult.reports.coins,'HKS-coins.csv');$('downloadEquity').onclick=()=>currentResult&&exportCSV(currentResult.equity_curve,'HKS-equity.csv');
$('closeDetail').onclick=()=>$('tradeDialog').close();addEventListener('resize',chart);
for(const b of document.querySelectorAll('[data-period]'))b.onclick=handle(()=>choosePeriod(b.dataset.period));
$('start').onchange=()=>{choosePeriod('custom');coverage();};$('end').onchange=()=>coverage();
// Only supported 1m execution is exposed. A coarser interval is never substituted.
$('interval').replaceChildren(new Option('1 minute · verified execution','1m'));
$('dataset').replaceChildren(new Option('BINANCE USD-M Futures · November 2025 · 20 verified symbols','binance-november-2025'));
for(const c of catalog)$('dataset').append(new Option((c.synthetic?'SYNTHETIC · ':'GENUINE FUTURES · ')+c.id,c.id));
await store.recover();await versions();
const savedWatch=await store.get('settings','watchlist');if(savedWatch)watchlist=savedWatch.symbols;$('watchlist').value=watchlist.join(', ');
const last=await store.get('settings','last-success');
if(last){applyRequest(last.request);await showJob(last.job);}else{
 const sample=await fixture('genuine_2coin_1day');setDefinition(sample.definition);await selection();
}
// Explicit current preference wins over an older successful test. Legacy true
// is accepted only from the user's last successful request, never source data.
$('diagnostic').checked=savedConsent(await store.get('settings',FUTURES_CONSENT_ID),last?.request.config.allow_uncertified_futures);
consentStatus();
for(const id of ['runButton','saveStrategy','validate','restore','refresh','saveWatchlist'])$(id).disabled=false;
$('restore').disabled=!last;$('retry').disabled=!job?.checkpoint||job.status==='COMPLETE'||job.sourceHash!==sourceHash;$('cancel').disabled=true;
text('connection',crossOriginIsolated?'Browser Python ready':'Isolation headers missing');text('runtimeStatus','Context API v2 · Completed 15m / 1H candles · Trusted code only. 30s per computation chunk; 3s per strategy callback; 1h foreground session. No hard browser memory cap.');
if(!crossOriginIsolated){$('runButton').disabled=true;message('Unavailable: COOP/COEP headers required. There is no unsafe fallback.');}
await history();await storageStatus();
window.HKSStudio={store,catalog,months,cache,cacheAll,fixture,run,compose,saveVersion,showJob,applyRequest,sourceHash,BrowserEngine,SandboxClient,get running(){return running;},get job(){return job;},get result(){return currentAnswer;}};
if('serviceWorker' in navigator){try{await navigator.serviceWorker.register('sw.js',{updateViaCache:'none'});await navigator.serviceWorker.ready;}catch(e){message('Offline runtime caching unavailable: '+e.message);}}
