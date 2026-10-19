// Update only application assets before enabling Run. Never clear IDB/OPFS,
// restart another tab, or reload a running calculation.
async function start(){
 if('serviceWorker' in navigator){
  const r=await navigator.serviceWorker.register('sw.js',{updateViaCache:'none'});
  try{await r.update();}catch(error){if(!r.active)throw error;}
  const w=r.installing||r.waiting;
  if(w&&w.state!=='activated')await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Error('Sandbox update is incomplete; reload when connected')),45000);
   const state=()=>{if(w.state==='activated'){clearTimeout(timer);resolve();}else if(w.state==='redundant'){clearTimeout(timer);reject(Error('Sandbox update failed; saved data is intact'));}};
   w.addEventListener('statechange',state);state();
  });
 }
 await import('./app.js?sha256=f94a5e5947957996eddc67fb776a9b50065b98683f867df3d83d6ed24cfcee06');
}
start().catch(error=>{
 const box=document.getElementById('message');
 if(box)box.textContent='Cannot initialize this browser workspace: '+String(error.message||error)+'. Use current Chrome/Edge over HTTPS with site storage enabled. No calculation was accepted.';
 const status=document.getElementById('runtimeStatus');if(status)status.textContent='Browser initialization failed';
 const run=document.getElementById('runButton');if(run)run.disabled=true;
});
