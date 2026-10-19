"""Independent source-signal, fill, sizing and wallet checks for actual browser runs."""
import csv,gzip,hashlib,json,sys
from bisect import bisect_right
from decimal import Decimal as D,localcontext,ROUND_FLOOR,ROUND_HALF_EVEN
from pathlib import Path
from smc_cached_evidence import load
from smc_reference import snapshot
from verify_consent_browser import reconcile
ROOT=Path(__file__).resolve().parents[1]
import _kernel_for_tests
from backtester.browser_context import aggregate

def main():
    folder=ROOT/'evidence/smc-compat-v1/browser'
    data={s:load(s)[0] for s in ('BTCUSDT','ETHUSDT')}
    by_open={s:{b.open_ms:b for b in bars} for s,bars in data.items()}
    m15={s:aggregate(bars,'15m') for s,bars in data.items()}
    h1={s:aggregate(bars,'1h') for s,bars in data.items()}
    out=[]
    with localcontext() as ctx:
        ctx.prec=50
        for name in ('shared-genuine-result','individual-genuine-result','shared-reverse-short-result','individual-reverse-short-result'):
            answer=json.loads(gzip.decompress((folder/(name+'.json.gz')).read_bytes()));r=answer['result']
            assert hashlib.sha256(json.dumps({k:v for k,v in r.items() if k!='result_hash'},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==r['result_hash']
            checks=reconcile(r);entries=[e for e in r['decisions'] if e['outcome']=='ENTERED']
            assert entries
            for e in entries:
                s=e['symbol'];t=e['signal_ms'];assert t%900000==0
                a=[b for b in m15[s] if b.end_ms<=t][-50:];hours=[b for b in h1[s] if b.end_ms<=t][-21:]
                source=snapshot(a,hours)
                assert source['qualifies'] and source['executed_side']==e['side']
                p=next(p for p in r['trades']+r['open_positions'] if p['trade_id']==e['trade_id'])
                sign=D(1) if e['side']=='LONG' else D(-1)
                raw=by_open[s][t].open
                entry=raw*(1+sign*D(r['config']['slippage_bps'])/10000)
                rounded=D(source['stop_fraction']).quantize(D('1e-18'),rounding=ROUND_HALF_EVEN)
                assert abs(rounded-D(source['stop_fraction']))<=D('0.5e-18')
                stop=entry*(1-sign*rounded)
                tol=D('1e-20')
                assert abs(entry-D(p['entry_price']))<tol
                assert abs(stop-D(p['initial_stop']))<tol
                assert p['target'] is None
                eq=D(e['equity_before']);risk=eq*D('.01')
                distance=abs(entry-stop)
                quantity=(min(risk/distance,eq*D('.25')/entry)/D('.00000001')).to_integral_value(rounding=ROUND_FLOOR)*D('.00000001')
                assert abs(quantity-D(p['quantity']))<tol
                assert abs(D(p['risk_budget'])-risk)<tol
                assert abs(D(p['planned_risk'])-quantity*distance)<tol
                # Independent replay of close-based 15m trailing decisions.
                # A proposal from the final candle has no next executable open.
                active=D(p['initial_stop']);projection=distance*2
                cutoff=p.get('fill_window_start_ms',r['config']['end_ms'])
                for bar in m15[s]:
                    if not t<bar.end_ms<cutoff:continue
                    progress=sign*(bar.close-entry)/projection*100
                    if progress<50:continue
                    locked=(progress//5)*5-10 if progress>=80 else D(10)
                    candidate=(entry+sign*projection*locked/100).quantize(D('1e-18'),rounding=ROUND_HALF_EVEN)
                    active=max(active,candidate) if sign==1 else min(active,candidate)
                assert abs(active-D(p['stop']))<tol,(name,active,p['stop'])
                out.append(dict(run=name,symbol=s,signal_ms=t,original_side=source['original_side'],
                    executed_side=e['side'],score=source['score'],stop_fraction=source['stop_fraction'],
                    entry_price=p['entry_price'],initial_stop=p['initial_stop'],quantity=p['quantity'],
                    final_stop=p['stop'],independently_derived_stop=str(active),
                    risk_budget=p['risk_budget'],actual_planned_risk=p['planned_risk'],
                    exit_reason=p.get('exit_reason','OPEN'),result_hash=r['result_hash'],independent_checks=True))
            print(name,checks,'signal/fill/sizing parity PASS')
    with (folder/'INDEPENDENT_ENTRY_AUDIT.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
    (folder/'INDEPENDENT_RECONCILIATION.json').write_text(json.dumps({'passed':True,'entries_checked':len(out),
        'checks':['result SHA256','legacy qualification and final reverse direction','completed-hour causality','adverse fill',
                  'initial ATR stop','1% current-equity budget','unchanged 25% capital cap and quantity flooring',
                  'completed-15m original 50/80 trailing and final active stop','no TP or partial exits',
                  'trade fees/slippage/net PnL','available cash, reserve, unrealized PnL and equity']},indent=2))

if __name__=='__main__':main()
