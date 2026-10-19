// This document has an opaque origin (sandbox=allow-scripts, NO same-origin).
// Only its parent may supply a transferred private channel. No network/storage.
addEventListener('message', event => {
  if (event.source !== parent || event.data?.type !== 'ATTACH' || !event.ports[0]) return;
  const port = event.ports[0];
  const worker = new Worker(URL.createObjectURL(new Blob([event.data.source], {type:'text/javascript'})));
  worker.onmessage = e => port.postMessage(e.data);
  worker.onerror = e => port.postMessage({type:'fatal',error:e.message});
  port.onmessage = e => {
    if(e.data?.type==='STOP'){worker.terminate();port.close();return;}
    worker.postMessage(e.data);
  };
  port.start();
  port.postMessage({type:'attached'});
}, {once:true});
parent.postMessage({type:'HKS_OPAQUE_FRAME_READY'}, '*');
