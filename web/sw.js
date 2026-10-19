const CACHE='hks-premium-static-89075a3d4ba8f4e6';
self.addEventListener('install',event=>event.waitUntil((async()=>{
  const assets=await (await fetch('offline-assets.json',{cache:'no-store'})).json();
  // A new cache must contain this build, not fresh HTTP-cache entries from
  // the previous UI. This leaves IndexedDB, OPFS and all user records intact.
  await (await caches.open(CACHE)).addAll(assets.map(url=>new Request(url,{cache:'reload'})));self.skipWaiting();
})()));
self.addEventListener('activate',e=>e.waitUntil((async()=>{
  // Only superseded runtime assets owned by this proof. Candle OPFS/IDB stays.
  for(const key of await caches.keys())if(key.startsWith('hks-premium-static-')&&key!==CACHE)await caches.delete(key);
  await clients.claim();
})()));
self.addEventListener('fetch',e=>{
  const url=new URL(e.request.url);
  if(e.request.method!=='GET'||url.origin!==location.origin)return;
  // Candle payloads are deliberately NOT cached here: OPFS/IndexedDB owns them.
  if(url.pathname.startsWith('/fixtures/')||url.pathname.startsWith('/candles/'))return;
  e.respondWith((async()=>{
    // An old cached shell must not indefinitely serve an obsolete Context API.
    // Offline startup still falls back to the current atomic static cache.
    if(e.request.mode==='navigate'||['/boot.js','/runtime-manifest.json'].includes(url.pathname)){
      try{const fresh=await fetch(e.request,{cache:'no-store'});if(fresh.ok)return fresh;}catch(_){}
    }
    // Only this atomically installed build may supply application code. A
    // retained legacy/other cache must not override the consent UI or worker.
    const cache=await caches.open(CACHE);
    // Pages canonicalizes .html to extensionless routes. A versioned entry
    // query changes neither document identity nor the preserved local data.
    const documents={'/':'/','/index':'/index.html','/index.html':'/index.html','/sandbox':'/sandbox.html','/sandbox.html':'/sandbox.html'};
    const key=e.request.mode==='navigate'&&Object.hasOwn(documents,url.pathname)
      ?url.origin+documents[url.pathname]
      :url.searchParams.has('sha256')?url.origin+url.pathname:e.request;
    const hit=await cache.match(key);if(hit)return hit;
    return fetch(e.request);
  })());
});
