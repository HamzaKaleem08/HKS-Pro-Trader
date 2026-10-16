"use strict";
let accessToken = "", catalog = null, currentRun = null, page = 1, total = 0;
const $ = id => document.getElementById(id);
const num = x => x === null || x === undefined ? "—" : Number(x).toLocaleString("en-US", {maximumFractionDigits:6});
const date = ms => new Date(ms).toISOString();
function message(text,error=false){$("message").textContent=text;$("message").classList.toggle("error",error);}
async function api(path,body){
 const res=await fetch(path,{method:body===undefined?"GET":"POST",headers:{"Authorization":"Bearer "+accessToken,...(body===undefined?{}:{"Content-Type":"application/json"})},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await res.json();if(!res.ok){if(res.status===401){accessToken="";$("connection").textContent="Locked";}throw new Error(data.error||"Request failed");}return data;
}
function option(value,label){const n=document.createElement("option");n.value=value;n.textContent=label;return n;}
function table(id,heads,rows){const t=$(id);t.replaceChildren();const h=document.createElement("tr");for(const v of heads){const c=document.createElement("th");c.textContent=v;h.append(c);}t.append(h);for(const values of rows){const r=document.createElement("tr");for(const v of values){const c=document.createElement("td");if(v instanceof Node)c.append(v);else c.textContent=String(v??"—");r.append(c);}t.append(r);}}
function datasetChanged(){
 const ds=catalog.datasets.find(x=>x.id===$("dataset").value);if(!ds)return;
 $("futuresWarning").hidden=ds.market!=="USDT_LINEAR_PERPETUAL";$("futuresAck").checked=false;
 $("symbols").replaceChildren(...ds.coverage.map(c=>{const n=option(c.symbol,c.symbol);n.selected=true;return n;}));
 $("datasetInfo").textContent=(ds.synthetic?"SYNTHETIC FIXTURE":"SUPPLIER-DECLARED HISTORY")+" · "+ds.exchange+" · "+ds.market+" · "+ds.interval+" · "+ds.coverage.reduce((n,c)=>n+c.candles,0)+" candles";
 const def=catalog.strategies.find(x=>x.version_id===$("strategy").value)?.definition;
 const interval={"1m":60000,"5m":300000,"15m":900000,"1h":3600000}[ds.interval];
 const start=Math.max(...ds.coverage.map(c=>c.first_open_ms))+(def?def.slow+1:21)*interval;
 const end=Math.min(...ds.coverage.map(c=>c.last_complete_ms));
 $("start").value=date(start).slice(0,16);$("end").value=date(end).slice(0,16);
}
async function refresh(keepInputs=false){
 catalog=await api("/api/catalog");const selected=$("strategy").value,selectedDataset=$("dataset").value;
 $("dataset").replaceChildren(...catalog.datasets.filter(d=>!d.invalid).map(d=>option(d.id,d.id+(d.synthetic?" [SYNTHETIC]":" [declared history]"))));
 if(keepInputs&&catalog.datasets.some(d=>d.id===selectedDataset))$("dataset").value=selectedDataset;
 $("strategy").replaceChildren(...catalog.strategies.map(s=>option(s.version_id,s.definition.name+" · "+s.content_hash.slice(0,12))));
 if(catalog.strategies.some(s=>s.version_id===selected))$("strategy").value=selected;
 if(!$("definition").value&&catalog.strategies.length)$("definition").value=JSON.stringify(catalog.strategies[0].definition,null,2);
 $("history").replaceChildren();for(const r of catalog.runs){const n=document.createElement("div");n.className="history-row";const span=document.createElement("span");span.textContent=r.id+" · "+r.status+(r.error?" · "+r.error:"");n.append(span);if(r.status==="COMPLETE"||r.status==="RUNNING"){const b=document.createElement("button");b.textContent=r.status==="COMPLETE"?"Open report":"Watch progress";b.onclick=()=>watchRun(r.id).catch(e=>message(e.message,true));n.append(b);}$("history").append(n);}
 $("saveStrategy").disabled=false;$("runButton").disabled=!catalog.strategies.length||!catalog.datasets.some(d=>!d.invalid);if(!keepInputs||!selectedDataset)datasetChanged();
 for(const id of ["importData","planData","fetchData"])$(id).disabled=false;
 $("storageStatus").textContent=catalog.storage.durable_configured?"PostgreSQL durable backend configured. Actual Replit restart/redeploy persistence must still be verified in your account.":"LOCAL SQLITE ONLY. Files persist on this computer; this mode does not establish Replit deployment durability.";
 await refreshData();
}
$("authForm").addEventListener("submit",async e=>{e.preventDefault();accessToken=$("token").value;$("token").value="";try{await refresh();$("connection").textContent="Authenticated · local only";message("Connected. Choose verified local inputs and an explicit saved demonstration version.");}catch(err){message(err.message,true);}});
$("dataset").onchange=datasetChanged;$("strategy").onchange=datasetChanged;
$("strategyForm").onsubmit=async e=>{e.preventDefault();try{const res=await api("/api/strategies",JSON.parse($("definition").value));await refresh();$("strategy").value=res.version_id;datasetChanged();message("Immutable version saved for testing. Trading activation was not changed.");}catch(err){message(err.message,true);}};
function percent(id){const text=$(id).value;if(text.length>80||!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(text))throw new Error(id+": finite decimal required");const parts=text.split("."),whole=parts[0].padStart(3,"0"),fraction=parts[1]||"";return (whole.slice(0,-2).replace(/^0+/,"")||"0")+"."+whole.slice(-2)+fraction;}
$("runForm").onsubmit=async e=>{
 e.preventDefault();$("runButton").disabled=true;message("Running bounded replay in a separate worker. No trading orders are submitted.");
 try{const body={dataset_id:$("dataset").value,strategy_version:$("strategy").value,symbols:Array.from($("symbols").selectedOptions,x=>x.value),config:{start_ms:$("start").value+":00Z",end_ms:$("end").value+":00Z",mode:$("mode").value,initial_capital:$("capital").value,max_positions:Number($("capacity").value),fee_bps:$("fees").value,slippage_bps:$("slippage").value,risk_fraction:percent("risk"),allocation_fraction:percent("allocation"),end_policy:$("endPolicy").value}};
 body.config.allow_uncertified_futures=$("futuresAck").checked;
 body.config.sizing=$("sizing").value;body.config.fixed_notional=$("fixedNotional").value;
 const r=await api("/api/runs",body);await watchRun(r.id);await refresh(true);message("Replay complete. Read provenance, assumptions, open exposure and reconciliation before interpreting PnL.");
 }catch(err){message(err.message,true);try{await refresh(true);}catch(ignore){}}finally{$("runButton").disabled=!accessToken;}
};
async function showRun(id){
 currentRun=id;page=1;const r=await api("/api/runs/"+id);$("result").hidden=false;
 $("summary").replaceChildren();for(const [label,val] of [["Closed / open trades",r.summary.closed_trades+" / "+r.summary.open_trades],["Ending equity ($)",num(r.summary.ending_equity)],["Realized net PnL ($)",num(r.summary.realized_net_pnl)],["Unrealized PnL ($)",num(r.summary.unrealized_pnl)],["Sampled drawdown ($)",num(r.summary.max_drawdown)],["Win rate after fees (%)",num(r.summary.win_rate_pct)],["Fees on closed trades ($)",num(r.summary.fees_closed_trades)],["Rejected entries",r.summary.rejected_entries]]){const n=document.createElement("div");n.className="metric";const s=document.createElement("span"),b=document.createElement("strong");s.textContent=label;b.textContent=val;n.append(s,b);$("summary").append(n);}
 table("coins",["Symbol","Signals","Closed","Open","Wins","Losses","WR %","Gross $","Fees $","Slip $ (included)","Net realized $","Unrealized $","Ending equity $","Drawdown $","Mean MFE %","Mean MAE %","Capital scope"],r.coins.map(c=>[c.symbol,c.qualified_signals,c.closed_trades,c.open_trades,c.wins,c.losses,num(c.win_rate_pct),num(c.gross_pnl_after_slippage),num(c.fees_closed_trades),num(c.slippage_already_in_pnl),num(c.realized_net_pnl),num(c.unrealized_pnl),num(c.ending_equity),num(c.drawdown),num(c.mean_mfe_pct),num(c.mean_mae_pct),c.starting_capital===null?"Shared account":"Independent $"+num(c.starting_capital)]));
 $("metadata").textContent=JSON.stringify({summary:r.summary,...r.metadata},null,2);$("breakdowns").textContent=JSON.stringify({monthly_realized_by_exit:r.monthly_realized_by_exit,exit_reasons:r.exit_reasons},null,2);$("openPositions").textContent=JSON.stringify(r.open_positions,null,2);await loadTrades();
}
async function watchRun(id){
 for(let attempt=0;attempt<180;attempt++){
  const r=await api("/api/runs/"+id);$("jobProgress").value=r.progress?.percent??(r.status==="COMPLETE"?100:0);$("jobStage").textContent=r.progress?.stage||r.status;
  if(r.status==="COMPLETE"){await showRun(id);return;}
  if(r.status!=="RUNNING")throw new Error(r.error||"Job "+r.status);
  await new Promise(resolve=>setTimeout(resolve,1000));
 }throw new Error("Progress wait expired. Check run history; no completed result is assumed.");
}
function sourceMetadata(){return {exchange:$("dataSynthetic").checked?"SYNTHETIC":"BINANCE",market:$("dataMarket").value,symbol:$("dataSymbol").value,interval:$("dataInterval").value,synthetic:$("dataSynthetic").checked,source:$("dataSource").value,retrieved_at:null};}
async function refreshData(){const data=await api("/api/data?q="+encodeURIComponent($("dataSearch").value));table("dataInventory",["Symbol","Exchange / market","Interval","Records","Start UTC","End UTC","Missing grid intervals","Source"],data.series.map(s=>[s.symbol,s.exchange+" / "+s.market,s.interval,s.records,date(s.first_open_ms),date(s.last_complete_ms),s.missing_intervals,s.source]));$("importHistory").textContent=JSON.stringify(data.imports,null,2);}
$("dataSearch").onchange=()=>refreshData().catch(e=>message(e.message,true));
$("dataForm").onsubmit=async e=>{e.preventDefault();const file=$("dataFile").files[0];if(!file)return;const form=new FormData();form.append("file",file);form.append("metadata",JSON.stringify(sourceMetadata()));if($("dataChecksum").files[0])form.append("checksum",$("dataChecksum").files[0]);$("importData").disabled=true;$("dataStatus").textContent="Validating and storing bounded chunks; incomplete inputs cannot become usable data.";const timer=setInterval(()=>refreshData().catch(()=>{}),1500);try{const response=await fetch("/api/data/import",{method:"POST",headers:{Authorization:"Bearer "+accessToken},body:form});const r=await response.json();if(!response.ok)throw new Error(r.error||"Import failed");$("dataStatus").textContent="Stored "+r.inserted+" new candles; "+r.reused+" existing identical candles reused. SHA256 "+r.source_sha256;await refresh(true);}catch(err){$("dataStatus").textContent=err.message;message(err.message,true);}finally{clearInterval(timer);$("importData").disabled=!accessToken;await refreshData();}};
function historyRange(){return {metadata:sourceMetadata(),start_ms:$("dataStart").value+":00Z",end_ms:$("dataEnd").value+":00Z"};}
$("planData").onclick=async()=>{try{$("dataPlan").textContent=JSON.stringify(await api("/api/data/plan",historyRange()),null,2);}catch(e){message(e.message,true);}};
$("fetchData").onclick=async()=>{$("fetchData").disabled=true;$("dataStatus").textContent="Requesting a bounded batch from official Binance only. No denied-connection retries or substitute sources.";try{const r=await api("/api/data/fetch",historyRange());$("dataPlan").textContent=JSON.stringify(r,null,2);$("dataStatus").textContent=r.status+" · "+r.requests+" historical requests · "+(r.remaining?.length||0)+" missing ranges";await refresh(true);}catch(e){message(e.message,true);$("dataStatus").textContent=e.message;}finally{$("fetchData").disabled=!accessToken;}};
async function loadTrades(){if(!currentRun)return;const q=new URLSearchParams({page:String(page),size:"25",q:$("search").value,sort:$("sort").value,direction:$("direction").value});const r=await api("/api/runs/"+currentRun+"/trades?"+q);total=r.total;
 table("trades",["Symbol","Side","Entry UTC","Exit availability UTC","Net $","Duration (minutes)","Exit","Details"],r.trades.map(t=>{const b=document.createElement("button");b.textContent="View";b.onclick=async()=>{try{$("tradeDetail").textContent=JSON.stringify(await api("/api/runs/"+currentRun+"/trade/"+t.trade_id),null,2);$("tradeDialog").showModal();}catch(err){message(err.message,true);}};return[t.symbol,t.side,date(t.entry_ms),date(t.exit_ms),num(t.net_pnl),num(t.holding_ms/60000),t.exit_reason,b];}));$("pageInfo").textContent="Page "+page+" · "+total+" matching closed trades";$("previous").disabled=page<=1;$("next").disabled=page*25>=total;
}
for(const id of ["search","sort","direction"]){$(id).onchange=()=>{page=1;loadTrades().catch(e=>message(e.message,true));};}
$("previous").onclick=()=>{page--;loadTrades().catch(e=>message(e.message,true));};$("next").onclick=()=>{page++;loadTrades().catch(e=>message(e.message,true));};$("closeDetail").onclick=()=>$("tradeDialog").close();
async function download(kind){try{const r=await fetch("/api/runs/"+currentRun+"/export/"+kind,{headers:{Authorization:"Bearer "+accessToken}});if(!r.ok)throw new Error("CSV export failed");const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=currentRun+"-"+kind+".csv";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(err){message(err.message,true);}}
$("exportTrades").onclick=()=>download("trades");$("exportCoins").onclick=()=>download("coins");$("exportDecisions").onclick=()=>download("decisions");
