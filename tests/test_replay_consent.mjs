import assert from 'node:assert/strict';
import test from 'node:test';
import {assertReplayConsent,consentPreference,savedConsent,FUTURES_CONSENT_ID} from '../web/replay-consent.js';

const market='USDT_LINEAR_PERPETUAL';
test('explicit checked consent preserves the complete request unchanged',()=>{
  const config=Object.freeze({allow_uncertified_futures:true,mode:'shared',fee_bps:'10'});
  assert.doesNotThrow(()=>assertReplayConsent(config,market,true));
  assert.deepEqual(config,{allow_uncertified_futures:true,mode:'shared',fee_bps:'10'});
});
test('unchecked current consent rejects even if saved request had consent',()=>{
  assert.throws(()=>assertReplayConsent({allow_uncertified_futures:true},market,false,true),/before starting or resuming/);
});
test('late checkbox edits cannot authorize a captured false request',()=>{
  const config={allow_uncertified_futures:false};
  assert.throws(()=>assertReplayConsent(config,market,true),/captured request/);
  assert.equal(config.allow_uncertified_futures,false);
});
test('resume cannot promote missing or false saved consent',()=>{
  for(const config of [{},{allow_uncertified_futures:false}]){
    assert.throws(()=>assertReplayConsent(config,market,true,true),/saved checkpoint settings cannot be changed/);
    assert.notEqual(config.allow_uncertified_futures,true);
  }
});
test('true saved consent plus fresh acknowledgement allows resume',()=>{
  const config=Object.freeze({allow_uncertified_futures:true});
  assert.doesNotThrow(()=>assertReplayConsent(config,market,true,true));
});
test('truthy strings and numbers are not boolean consent',()=>{
  for(const value of ['true',1,{},undefined,null]){
    assert.throws(()=>assertReplayConsent({allow_uncertified_futures:value},market,true));
    assert.throws(()=>assertReplayConsent({allow_uncertified_futures:true},market,value));
  }
});
test('Spot synthetic fixtures do not require Futures consent',()=>{
  assert.doesNotThrow(()=>assertReplayConsent({},'SPOT',false));
});

test('explicit per-device consent persists independently of old successful tests',()=>{
 assert.equal(savedConsent(consentPreference(true),false),true);
 assert.equal(savedConsent(consentPreference(false),true),false);
 assert.equal(savedConsent(null,true),true);
 assert.equal(savedConsent(null,false),false);
 assert.equal(savedConsent({id:FUTURES_CONSENT_ID,market:'SPOT',accepted:true},true),false);
 assert.equal(savedConsent({id:FUTURES_CONSENT_ID,market:'USDT_LINEAR_PERPETUAL',accepted:'true'},true),false);
 assert.throws(()=>consentPreference('true'));
});

test('service worker binds code lookup to current build, not retained legacy caches',async()=>{
 const {readFile}=await import('node:fs/promises');const vm=await import('node:vm');const handlers={};let opened;
 const current={marker:'CURRENT_CHECKED_CONSENT_BUILD'},legacy={marker:'LEGACY_MISSING_CONSENT_BUILD'};
 const sandbox={self:{addEventListener:(name,fn)=>handlers[name]=fn},URL,location:{origin:'https://hks-pro-trader-browser-staging.pages.dev'},
 caches:{match:async()=>legacy,open:async name=>{opened=name;return {match:async()=>current};}},fetch:async()=>{throw Error('unexpected network fallback');}};
 vm.runInNewContext(await readFile(new URL('../web/sw.js',import.meta.url),'utf8'),sandbox);
 let response;handlers.fetch({request:{url:sandbox.location.origin+'/app.js',method:'GET'},respondWith:p=>response=p});
 assert.equal(await response,current);assert.match(opened,/^hks-premium-static-/);
});
