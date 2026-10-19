// Runtime delivery checks only; no strategy decisions or financial calculations.
export const CONTEXT_CONTRACT='HKS_BROWSER_COMPLETED_CONTEXT/2';
export async function verifiedBytes(name,expected,fetcher=fetch){
  if(!/^[a-f0-9]{64}$/.test(expected))throw Error('Invalid pinned runtime checksum');
  const r=await fetcher(name+'?sha256='+expected,{cache:'no-store'});
  if(!r.ok)throw Error('Runtime asset HTTP '+r.status+': '+name);
  const bytes=await r.arrayBuffer();
  const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  if(actual!==expected)throw Error('Cached runtime checksum mismatch: '+name+'. Reload the website to load the verified Sandbox. Saved candles and reports are preserved.');
  return bytes;
}
export function assertContextAPI(info,manifest){
  if(info.contextContract!==CONTEXT_CONTRACT||JSON.stringify(info.contextTimeframes)!==JSON.stringify(['15m','1h'])||info.runtimeManifest!==manifest){
    throw Error('Outdated Sandbox Context API refused before strategy execution. Reload the website to update the Sandbox; saved candles and reports are preserved.');
  }
}
