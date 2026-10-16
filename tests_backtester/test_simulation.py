from dataclasses import replace
from decimal import Decimal as D
import unittest

from backtester.config import RunConfig
from backtester.errors import ValidationError
from backtester.simulation import simulate
from helpers import M,T,Scripted,candles,dataset


class ReplayTests(unittest.TestCase):
    def cfg(self,**kw):
        return RunConfig(start_ms=T+M,end_ms=T+6*M,fee_bps="0",slippage_bps="0",allocation_fraction="1",**kw)

    def test_independently_hand_calculated_long(self):
        # 1000 equity * 1% / (100*10%) = 1 unit. Buy100, sell110,
        # fees 0.1 + 0.11 -> net9.79, final1009.79.
        ds=dataset({"BTCUSDT":candles(prices=[(100,100,100,100)]*2+[(100,111,99,110)]+[(110,110,110,110)]*3)})
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,fee_bps="10",slippage_bps="0",allocation_fraction="1")
        r=simulate(ds,Scripted(target=".1"),c);t=r["trades"][0]
        self.assertEqual(D(t["quantity"]),D(1));self.assertEqual(D(t["net_pnl"]),D("9.79"))
        self.assertEqual(D(r["accounts"]["BTCUSDT"]["ending_equity"]),D("1009.79"))
        self.assertEqual(D(r["reconciliation"]["BTCUSDT"]["cash_residual"]),0)

    def test_next_bar_execution_not_signal_close(self):
        ds=dataset({"BTCUSDT":candles(prices=[(90,100,90,100),(105,106,104,105)]+[(105,106,104,105)]*4)})
        r=simulate(ds,Scripted(),self.cfg());p=r["open_positions"][0]
        self.assertEqual(p["entry_ms"],T+M);self.assertEqual(D(p["entry_price"]),105)

    def test_short_linear_pnl(self):
        ds=dataset({"BTCUSDT":candles(prices=[(100,100,100,100)]*2+[(100,101,89,90)]+[(90,90,90,90)]*3)},market="USDT_LINEAR_PERPETUAL")
        r=simulate(ds,Scripted({("BTCUSDT",T+M):"SHORT"},target=".1"),self.cfg(allow_uncertified_futures=True))
        self.assertEqual(D(r["trades"][0]["gross_pnl"]),10)
        self.assertEqual(D(r["accounts"]["BTCUSDT"]["ending_equity"]),1010)
        self.assertIsNone(r["trades"][0]["funding"])

    def test_spot_short_rejected(self):
        r=simulate(dataset(),Scripted({("BTCUSDT",T+M):"SHORT"}),self.cfg())
        self.assertEqual(r["decisions"][0]["reason"],"SPOT_SHORT_UNSUPPORTED")
        self.assertFalse(r["trades"])

    def test_stop_before_target_when_ambiguous(self):
        ds=dataset({"BTCUSDT":candles(prices=[(100,100,100,100),(100,115,85,100)]+[(100,100,100,100)]*4)})
        t=simulate(ds,Scripted(target=".1"),self.cfg())["trades"][0]
        self.assertEqual(t["exit_reason"],"STOP_AMBIGUOUS")
        self.assertEqual(D(t["gross_pnl"]),-10)
        self.assertTrue(t["ambiguous_stop_target"])
        self.assertEqual(t["timestamp_precision"],"CANDLE_INTERVAL_ONLY")

    def test_gap_stop_is_not_filled_at_stale_stop(self):
        ds=dataset({"BTCUSDT":candles(prices=[(100,100,100,100)]*2+[(80,85,79,81)]+[(81,81,81,81)]*3)})
        t=simulate(ds,Scripted(),self.cfg())["trades"][0]
        self.assertEqual(t["exit_reason"],"STOP_GAP")
        self.assertEqual(D(t["exit_price"]),80)
        self.assertEqual(D(t["gross_pnl"]),-20)

    def test_open_end_is_not_fabricated_closed_trade(self):
        r=simulate(dataset(),Scripted(),self.cfg())
        self.assertEqual(len(r["open_positions"]),1);self.assertEqual(r["trades"],[])
        self.assertEqual(D(r["accounts"]["BTCUSDT"]["available_cash"]),900)
        self.assertEqual(D(r["accounts"]["BTCUSDT"]["ending_equity"]),1000)

    def test_explicit_end_close_costs(self):
        r=simulate(dataset(),Scripted(),self.cfg(end_policy="CLOSE_AT_LAST_CLOSE"))
        self.assertEqual(r["trades"][0]["exit_reason"],"END_OF_TEST_EXPLICIT")
        self.assertEqual(r["open_positions"],[])

    def test_slippage_is_charged_once(self):
        c=RunConfig(start_ms=T+M,end_ms=T+6*M,fee_bps="10",slippage_bps="20",end_policy="CLOSE_AT_LAST_CLOSE",allocation_fraction="1")
        r=simulate(dataset(),Scripted(),c);t=r["trades"][0]
        self.assertAlmostEqual(float(D(t["gross_before_slippage"])-D(t["slippage_cost"])),float(t["gross_pnl"]),places=20)
        self.assertEqual(D(t["net_pnl"]),D(t["gross_pnl"])-D(t["fees"]))
        self.assertLess(D(r["accounts"]["BTCUSDT"]["ending_equity"]),1000)

    def test_zero_volume_rejects_entry(self):
        rows=list(candles());rows[1]=replace(rows[1],volume=D(0))
        r=simulate(dataset({"BTCUSDT":rows}),Scripted(),self.cfg())
        self.assertEqual(r["decisions"][0]["reason"],"ENTRY_UNFILLED_ZERO_VOLUME")

    def test_position_conflict_and_duplicate_candle(self):
        r=simulate(dataset(),Scripted({("BTCUSDT",T+M):"LONG",("BTCUSDT",T+2*M):"LONG"}),self.cfg())
        self.assertEqual([x["reason"] for x in r["decisions"]],["ACCEPTED","POSITION_ALREADY_OPEN"])
        self.assertEqual(len(r["open_positions"]),1)

    def test_no_next_bar_signal_is_audited(self):
        r=simulate(dataset(),Scripted({("BTCUSDT",T+6*M):"LONG"}),self.cfg())
        self.assertEqual(r["decisions"][0]["reason"],"NO_NEXT_BAR_INSIDE_TEST")

    def test_no_signal_reports_zero(self):
        r=simulate(dataset(),Scripted({}),self.cfg())
        self.assertEqual(r["trades"],[]);self.assertEqual(r["open_positions"],[])
        self.assertEqual(r["signal_counts"]["BTCUSDT"]["qualified_signals"],0)

    def test_warmup_and_no_silent_shortening(self):
        for start,end in ((T,T+6*M),(T+M,T+7*M)):
            with self.assertRaisesRegex(ValidationError,"unavailable"):
                simulate(dataset(),Scripted(),RunConfig(start_ms=start,end_ms=end))

    def test_future_candles_not_passed_to_strategy(self):
        class Spy(Scripted):
            def evaluate(self,history):
                self.assertions.append((len(history),history[-1].end_ms))
                return super().evaluate(history)
        s=Spy({});s.assertions=[];simulate(dataset(),s,self.cfg())
        self.assertEqual(s.assertions,[(1,T+i*M) for i in range(1,7)])

    def test_repeatability(self):
        a=simulate(dataset(),Scripted(),self.cfg())
        b=simulate(dataset(),Scripted(),self.cfg())
        self.assertEqual(a,b)

    def test_future_path_does_not_change_earlier_entry(self):
        a=simulate(dataset(),Scripted(),self.cfg())
        bars=list(candles());bars[-1]=replace(bars[-1],high=D(500),close=D(400))
        b=simulate(dataset({"BTCUSDT":bars}),Scripted(),self.cfg())
        self.assertEqual(a["decisions"],b["decisions"])


if __name__ == "__main__":unittest.main()
