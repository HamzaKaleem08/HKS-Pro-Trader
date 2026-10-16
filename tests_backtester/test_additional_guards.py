from dataclasses import replace
from decimal import Decimal as D
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from backtester.common import timestamp,utc
from backtester.config import RunConfig
from backtester.data import read_candles
from backtester.errors import ValidationError,ResourceLimit
from backtester.models import Signal
from backtester.simulation import simulate
from helpers import M,T,Scripted,candles,dataset


class AdditionalGuards(unittest.TestCase):
    def config(self,**kw):return RunConfig(start_ms=T+M,end_ms=T+6*M,fee_bps="0",slippage_bps="0",**kw)

    def test_zero_volume_does_not_release_same_open_reserved_cash(self):
        btc=list(candles());btc[1]=replace(btc[1],volume=D(0))
        ds=dataset({"BTCUSDT":btc,"ETHUSDT":candles("ETHUSDT")})
        s=Scripted({("BTCUSDT",T+M):"LONG",("ETHUSDT",T+M):"LONG"})
        c=self.config(mode="shared",sizing="fixed_notional",fixed_notional="600",risk_fraction=".1",max_total_risk_fraction="1",allocation_fraction="1")
        r=simulate(ds,s,c)
        self.assertEqual([d["reason"] for d in r["decisions"]],["ENTRY_UNFILLED_ZERO_VOLUME","INSUFFICIENT_AVAILABLE_FUNDS"])
        self.assertFalse(r["trades"]);self.assertFalse(r["open_positions"])
        self.assertEqual(D(r["accounts"]["SHARED"]["ending_equity"]),1000)

    def test_zero_volume_final_close_remains_open(self):
        rows=list(candles());rows[-1]=replace(rows[-1],volume=D(0))
        r=simulate(dataset({"BTCUSDT":rows}),Scripted(),self.config(end_policy="CLOSE_AT_LAST_CLOSE"))
        self.assertEqual(len(r["open_positions"]),1);self.assertFalse(r["trades"])
        self.assertTrue(any("requested end close unfilled" in w for w in r["warnings"]))

    def test_exact_millisecond_conversion(self):
        for offset in (0,1,5,10,999):
            self.assertEqual(timestamp(utc(T+offset)),T+offset)
        with self.assertRaises(ValidationError):timestamp("2025-11-01Z")

    def test_bad_signal_timestamp_side_and_distance(self):
        class Bad(Scripted):
            def evaluate(self,h):return self.value
        for change in ({"timestamp_ms":T},{"side":"BUY"},{"stop_fraction":".1"}):
            s=Bad();s.value=replace(Scripted().evaluate(candles()[:1]),**change)
            with self.assertRaises(ValidationError):simulate(dataset(),s,self.config())

    def test_oversized_csv_field_is_controlled(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.csv";p.write_text("open_time,open,high,low,close,volume\n"+f"{T},"+"1"*150000+",1,1,1,1\n")
            with self.assertRaises(ValidationError):read_candles(p,"BTCUSDT","1m")

    def test_engine_resource_limit_is_not_partial_success(self):
        with patch("backtester.simulation.MAX_TRADES",0),self.assertRaises(ResourceLimit):
            simulate(dataset(),Scripted(),self.config())

    def test_empty_symbol_selection_rejected(self):
        with self.assertRaises(ValidationError):simulate(dataset(),Scripted(),self.config(),[])


class LegacyScannerPreservation(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parent/"fixtures"/"legacy_scanner.py"
        spec=importlib.util.spec_from_file_location("legacy_scanner_disposable_test",path)
        self.module=importlib.util.module_from_spec(spec)
        from unittest.mock import Mock
        with patch.dict("sys.modules",{"requests":types.SimpleNamespace(get=Mock(side_effect=AssertionError("network is forbidden in this historical fixture")))}):
            spec.loader.exec_module(self.module)

    def test_original_scanner_with_mocked_market_data(self):
        market=[[T+i*900000,"100","101","99","100","1"] for i in range(50)]
        wallet={"balance":1000.,"open_positions":{},"trades":[],"history":[1000.]}
        with patch.object(self.module,"get_klines",return_value=market):
            r=self.module.scan_logic("BTCUSDT",wallet)
        self.assertEqual(r["symbol"],"BTCUSDT");self.assertEqual(wallet["balance"],1000.)

    def test_original_routes_write_disposable_paths_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.module,"WALLET_FILE",str(Path(tmp)/"wallet.json")),patch.object(self.module,"CACHE_FILE",str(Path(tmp)/"cache.json")):
                client=self.module.app.test_client()
                self.assertEqual(client.get("/").status_code,200)
                r=client.get("/api/data")
                self.assertEqual(r.status_code,200);self.assertEqual(r.json["wallet"]["balance"],1000.)

    def test_old_scanner_confirmed_unreachable_entry_score_is_preserved(self):
        # The previous closes lie within the exact swing extrema window, so
        # MSS cannot break it. Same-side FVG also contradicts the sweep extrema.
        # This is an observed old-source defect, not authority to change it.
        for high,low in ((101,98),(102,99),(102,98)):
            market=[[T+i*900000,"100","101","99","100","1"] for i in range(50)]
            market[-1]=[market[-1][0],"100",str(high),str(low),"100","1"]
            wallet={"balance":1000.,"open_positions":{},"trades":[],"history":[1000.]}
            with patch.object(self.module,"get_klines",return_value=market),patch.object(self.module,"get_session_info",return_value=("SYNTHETIC_SESSION","08:00",True)):
                row=self.module.scan_logic("BTCUSDT",wallet)
            self.assertEqual(row["score"],45)
            self.assertFalse(wallet["open_positions"])


if __name__=="__main__":unittest.main()
