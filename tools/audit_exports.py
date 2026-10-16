"""Independent Decimal journal audit; does not import the simulation/account code."""
import argparse
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path


def audit(path):
    r=json.loads((path/"result.json").read_text());config=r["config"]
    payload={k:v for k,v in r.items() if k!="result_hash"}
    actual=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    assert actual==r["result_hash"],"result hash mismatch"
    fee_rate=D(config["fee_bps"])/10000;residuals={};checked=0
    for name,a in r["accounts"].items():
        cash=D(a["initial_capital"]);open_value=D(0);closed_net=D(0);events=[]
        closed=[t for t in r["trades"] if t["account"]==name]
        opened=[t for t in r["open_positions"] if t["account"]==name]
        for t in closed+opened:
            q=D(t["quantity"]);entry=D(t["entry_price"]);notional=q*entry;entry_fee=notional*fee_rate
            assert abs(notional-D(t["notional"]))<D("1e-20")
            assert abs(entry_fee-D(t["entry_fee"]))<D("1e-20")
            events.append((t["entry_ms"],1,t["trade_id"],-(notional+entry_fee)))
            assert D(t["planned_risk"])<=D(t["risk_budget"])+D("1e-20")
            assert abs(q*abs(entry-D(t["initial_stop"]))-D(t["planned_risk"]))<D("1e-20")
            if t["state"]=="CLOSED":
                exit=D(t["exit_price"]);sign=1 if t["side"]=="LONG" else -1
                gross=sign*(exit-entry)*q;exit_fee=exit*q*fee_rate;net=gross-entry_fee-exit_fee
                assert abs(gross-D(t["gross_pnl"]))<D("1e-20")
                assert abs(net-D(t["net_pnl"]))<D("1e-20")
                reference=sign*(D(t["exit_raw"])-D(t["entry_raw"]))*q
                assert abs(reference-D(t["slippage_cost"])-gross)<D("1e-20")
                credit=(exit*q if r["market"]=="SPOT" else notional+gross)-exit_fee
                events.append((t["exit_ms"],0,t["trade_id"],credit));closed_net+=net
            else:
                mark=D(t["mark_price"])
                open_value+=(q*mark if r["market"]=="SPOT" else notional+(mark-entry)*q*(1 if t["side"]=="LONG" else -1))
            checked+=1
        minimum_cash=cash
        for ts,kind,trade_id,amount in sorted(events):
            cash+=amount;minimum_cash=min(minimum_cash,cash)
            assert cash>=-D("1e-20"),"negative available cash in independent chronological ledger"
        cash_residual=cash-D(a["available_cash"]);equity_residual=cash+open_value-D(a["ending_equity"])
        assert abs(cash_residual)<D("1e-20") and abs(equity_residual)<D("1e-20")
        residuals[name]={"cash_residual":str(cash_residual),"equity_residual":str(equity_residual),"minimum_available_cash":str(minimum_cash)}
    for decision in r["decisions"]:
        if decision["outcome"]=="ENTERED":
            assert abs(D(decision["equity_before"])*D(config["risk_fraction"])-D(decision["risk_budget"]))<D("1e-20")
    return {"status":"PASS","result_hash":actual,"positions_checked":checked,"accounts":residuals,
            "scope":"Independent arithmetic and chronological cash reservations from recorded journal; not an independent tick/funding/filter certification"}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("exports",nargs="+",type=Path);p.add_argument("--out",required=True,type=Path);args=p.parse_args()
    with localcontext() as ctx:
        ctx.prec=50;result={str(path):audit(path) for path in args.exports}
    args.out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))


if __name__=="__main__":main()
