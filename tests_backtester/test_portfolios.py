from decimal import Decimal as D
import csv
import io
import unittest

from backtester.config import RunConfig
from backtester.reports import build_reports,csv_report,_safe_cell
from backtester.simulation import simulate
from helpers import M,T,Scripted,candles,dataset


class PortfolioTests(unittest.TestCase):
    def config(self,mode="shared",**kw):
        return RunConfig(start_ms=T+M,end_ms=T+6*M,mode=mode,fee_bps="0",slippage_bps="0",
                         allocation_fraction="1",sizing="fixed_notional",fixed_notional="600",
                         max_total_risk_fraction="1",**kw)

    def data(self,order=("BTCUSDT","ETHUSDT")):
        return dataset({s:candles(s) for s in order})

    def signals(self):return Scripted({(s,T+M):"LONG" for s in ("BTCUSDT","ETHUSDT")})

    def test_shared_does_not_spend_same_cash_twice(self):
        r=simulate(self.data(),self.signals(),self.config(risk_fraction=".1"))
        self.assertEqual(len(r["open_positions"]),1)
        self.assertEqual([d["reason"] for d in r["decisions"]],["ACCEPTED","INSUFFICIENT_AVAILABLE_FUNDS"])
        self.assertEqual(D(r["accounts"]["SHARED"]["available_cash"]),400)
        self.assertEqual(D(r["accounts"]["SHARED"]["reserved_capital"]),600)
        self.assertEqual(D(r["accounts"]["SHARED"]["ending_equity"]),1000)

    def test_individual_accounts_each_have_full_starting_capital(self):
        r=simulate(self.data(),self.signals(),self.config("individual",risk_fraction=".1"))
        self.assertEqual(len(r["open_positions"]),2)
        self.assertEqual(D(build_reports(r)["summary"]["starting_capital"]),2000)
        self.assertEqual(set(r["accounts"]),{"BTCUSDT","ETHUSDT"})

    def test_capacity_rejection(self):
        r=simulate(self.data(),self.signals(),self.config(max_positions=1,risk_fraction=".1"))
        self.assertEqual(r["decisions"][1]["reason"],"MAX_CONCURRENT_POSITIONS")

    def test_aggregate_risk_is_reserved_once(self):
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,mode="shared",fee_bps="0",slippage_bps="0",
                    allocation_fraction="1",max_total_risk_fraction=".015")
        r=simulate(self.data(),self.signals(),c)
        self.assertEqual(r["decisions"][1]["reason"],"AGGREGATE_RISK_LIMIT")
        self.assertEqual(D(r["accounts"]["SHARED"]["reserved_risk"]),10)
        self.assertEqual(D(r["accounts"]["SHARED"]["available_cash"]),900)

    def test_symbol_input_order_does_not_change_allocation(self):
        a=simulate(self.data(),self.signals(),self.config(risk_fraction=".1"))
        b=simulate(self.data(("ETHUSDT","BTCUSDT")),self.signals(),self.config(risk_fraction=".1"))
        self.assertEqual(a["decisions"],b["decisions"])
        self.assertEqual(a["trades"],b["trades"])
        self.assertEqual(a["open_positions"][0]["symbol"],"BTCUSDT")

    def test_global_chronology_reuses_capital_only_after_exit(self):
        btc=candles("BTCUSDT",[(100,100,100,100)]*2+[(100,100,89,90)]+[(90,90,90,90)]*3)
        eth=candles("ETHUSDT")
        s=Scripted({("BTCUSDT",T+M):"LONG",("ETHUSDT",T+3*M):"LONG"})
        r=simulate(dataset({"ETHUSDT":eth,"BTCUSDT":btc}),s,self.config(risk_fraction=".1"))
        self.assertEqual([x["reason"] for x in r["decisions"]],["ACCEPTED","ACCEPTED"])
        self.assertEqual(r["trades"][0]["exit_ms"],T+3*M)
        self.assertEqual(r["open_positions"][0]["entry_ms"],T+3*M)

    def test_intrabar_future_proceeds_cannot_fund_same_open(self):
        btc=candles("BTCUSDT",[(100,100,100,100)]*2+[(100,120,100,110)]+[(110,110,110,110)]*3)
        s=Scripted({("BTCUSDT",T+M):"LONG",("ETHUSDT",T+2*M):"LONG"},target=".1")
        r=simulate(dataset({"BTCUSDT":btc,"ETHUSDT":candles("ETHUSDT")}),s,self.config(risk_fraction=".1"))
        self.assertEqual(r["decisions"][1]["reason"],"INSUFFICIENT_AVAILABLE_FUNDS")

    def test_fee_reserve_prevents_unfunded_entry(self):
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,mode="shared",fee_bps="10",slippage_bps="0",
                    allocation_fraction="1",risk_fraction=".1",max_total_risk_fraction="1",sizing="fixed_notional",fixed_notional="1000")
        r=simulate(self.data(),self.signals(),c)
        self.assertTrue(all(x["reason"]=="INSUFFICIENT_AVAILABLE_FUNDS" for x in r["decisions"]))

    def test_risk_changes_with_current_equity(self):
        rows=candles(prices=[(100,100,100,100),(100,111,99,110),(100,100,100,100)]+[(100,100,100,100)]*3)
        s=Scripted({("BTCUSDT",T+M):"LONG",("BTCUSDT",T+3*M):"LONG"},target=".1")
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,fee_bps="0",slippage_bps="0",allocation_fraction="1")
        r=simulate(dataset({"BTCUSDT":rows}),s,c)
        self.assertEqual(D(r["decisions"][1]["risk_budget"]),D("10.10"))

    def test_coin_summary_includes_zero_trade_coins(self):
        r=simulate(self.data(),Scripted({("BTCUSDT",T+M):"LONG"}),self.config(risk_fraction=".1"))
        coins=build_reports(r)["coins"]
        self.assertEqual(coins[1]["symbol"],"ETHUSDT")
        self.assertEqual(coins[1]["qualified_signals"],0)
        self.assertIsNone(coins[1]["starting_capital"])

    def test_csv_and_exit_summary_reconcile(self):
        c=self.config("individual",risk_fraction=".1",end_policy="CLOSE_AT_LAST_CLOSE")
        r=simulate(self.data(),self.signals(),c)
        rows=list(csv.DictReader(io.StringIO(csv_report(r,"trades"))))
        self.assertEqual(len(rows),len(r["trades"]))
        self.assertEqual(sum(D(t["net_pnl"]) for t in rows),D(build_reports(r)["summary"]["realized_net_pnl"]))
        self.assertEqual(sum(build_reports(r)["exit_reasons"].values()),len(rows))

    def test_csv_excel_formula_protection(self):
        self.assertEqual(_safe_cell("=HYPERLINK(1)"),"'=HYPERLINK(1)")
        self.assertEqual(_safe_cell("-12.5"),"-12.5")


if __name__ == "__main__":unittest.main()
