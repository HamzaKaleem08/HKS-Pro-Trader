// Consent is part of the captured request, never inferred from checkbox truthiness
// later in the worker. Resume must preserve the original source-bound settings.
export const FUTURES_CONSENT_ID='diagnostic-futures-consent-v1';
export function consentPreference(accepted){
  if(typeof accepted!=='boolean')throw Error('Diagnostic consent must be an explicit boolean');
  return {id:FUTURES_CONSENT_ID,market:'USDT_LINEAR_PERPETUAL',accepted};
}
export function savedConsent(preference,fallback=false){
  if(preference===undefined||preference===null)return fallback===true;
  return preference.id===FUTURES_CONSENT_ID&&preference.market==='USDT_LINEAR_PERPETUAL'&&preference.accepted===true;
}
export function assertReplayConsent(config, market, currentConsent, resumed=false){
  if(market!=='USDT_LINEAR_PERPETUAL')return;
  if(currentConsent!==true)throw Error('Check diagnostic Futures consent before starting or resuming this test. No replay has started.');
  if(config?.allow_uncertified_futures!==true){
    throw Error(resumed
      ? 'This saved test has no explicit diagnostic Futures consent. Start a new test with consent checked; saved checkpoint settings cannot be changed.'
      : 'The captured request has no explicit diagnostic Futures consent. Check consent before Run and start a new test.');
  }
}
