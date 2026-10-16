from dataclasses import replace
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backtester.config import RunConfig
from backtester.data import load_dataset, read_candles
from backtester.errors import ValidationError
from backtester.strategies import DEMO_DEFINITION, build_strategy, validate_definition
from helpers import M, T, candles, write_bundle


class DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_bundle(self.root)
    def tearDown(self): self.tmp.cleanup()

    def test_valid_manifest_and_count(self):
        ds = load_dataset(self.root)
        self.assertTrue(ds.synthetic)
        self.assertEqual(len(ds.candles["BTCUSDT"]), 6)

    def test_gaps_rejected(self):
        rows = list(candles()); del rows[2]
        write_bundle(self.root, {"BTCUSDT": rows})
        with self.assertRaisesRegex(ValidationError,"gap"): load_dataset(self.root)

    def test_duplicates_rejected(self):
        rows = list(candles()); rows[2] = rows[1]
        write_bundle(self.root, {"BTCUSDT": rows})
        with self.assertRaisesRegex(ValidationError,"duplicate"): load_dataset(self.root)

    def test_misaligned_timestamp(self):
        rows = list(candles()); rows[2] = replace(rows[2], open_ms=rows[2].open_ms+1)
        write_bundle(self.root, {"BTCUSDT": rows})
        with self.assertRaisesRegex(ValidationError,"misalignment"): load_dataset(self.root)

    def test_partial_candle_rejected(self):
        with self.assertRaisesRegex(ValidationError,"incomplete"):
            load_dataset(self.root,as_of_ms=T+6*M-1)

    def test_bad_ohlc(self):
        rows = list(candles()); rows[0] = replace(rows[0],high=D(90))
        write_bundle(self.root,{"BTCUSDT":rows})
        with self.assertRaisesRegex(ValidationError,"OHLC"): load_dataset(self.root)

    def test_negative_volume(self):
        rows = list(candles()); rows[0] = replace(rows[0],volume=D(-1))
        write_bundle(self.root,{"BTCUSDT":rows})
        with self.assertRaises(ValidationError): load_dataset(self.root)

    def test_checksum_mismatch(self):
        (self.root/"BTCUSDT.csv").write_text("corrupt")
        with self.assertRaisesRegex(ValidationError,"SHA-256"): load_dataset(self.root)

    def test_path_escape(self):
        m=json.loads((self.root/"manifest.json").read_text()); m["files"][0]["file"]="../private.csv"
        (self.root/"manifest.json").write_text(json.dumps(m))
        with self.assertRaises(ValidationError): load_dataset(self.root)

    def test_symlink_rejected(self):
        p=self.root/"alias.csv"; p.symlink_to(self.root/"BTCUSDT.csv")
        m=json.loads((self.root/"manifest.json").read_text()); m["files"][0]["file"]="alias.csv"
        (self.root/"manifest.json").write_text(json.dumps(m))
        with self.assertRaises(ValidationError): load_dataset(self.root)

    def test_empty_csv(self):
        p=self.root/"BTCUSDT.csv";p.write_text("open_time,open,high,low,close,volume\n")
        with self.assertRaisesRegex(ValidationError,"empty"): read_candles(p,"BTCUSDT","1m")

    def test_unsupported_interval(self):
        with self.assertRaisesRegex(ValidationError,"interval"): read_candles(self.root/"BTCUSDT.csv","BTCUSDT","2m")

    def test_nan_price_and_duplicate_symbols(self):
        p=self.root/"BTCUSDT.csv";p.write_text("open_time,open,high,low,close,volume\n"+f"{T},NaN,1,1,1,1\n")
        with self.assertRaises(ValidationError): read_candles(p,"BTCUSDT","1m")
        m=write_bundle(self.root);m["files"].append(m["files"][0]);(self.root/"manifest.json").write_text(json.dumps(m))
        with self.assertRaisesRegex(ValidationError,"duplicate"):load_dataset(self.root)


class StrategyTests(unittest.TestCase):
    def test_unknown_code_rejected(self):
        for key in ("python","javascript","__import__"):
            with self.assertRaises(ValidationError):validate_definition(DEMO_DEFINITION|{key:"print(1)"})

    def test_invalid_definitions(self):
        for changes in ({"fast":True},{"slow":2},{"stop_fraction":"NaN"},{"kind":"NORMAL"},{"direction":"REVERSE"},{"direction":"BOTH","target_fraction":"1.2"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):validate_definition(DEMO_DEFINITION|changes)

    def test_causal_sma_cross(self):
        s=build_strategy(DEMO_DEFINITION|{"fast":2,"slow":3})
        up=candles(prices=[(p,p,p,p) for p in (100,99,98,110,1)])
        self.assertEqual(s.evaluate(up[:4]).side,"LONG")
        self.assertEqual(s.evaluate(up[:4]).timestamp_ms,T+4*M)
        self.assertEqual(s.evaluate(up[:3]).reason,"WARMUP")

    def test_content_hash_changes_only_with_definition(self):
        a=build_strategy(DEMO_DEFINITION);b=build_strategy(dict(reversed(list(DEMO_DEFINITION.items()))))
        self.assertEqual(a.version_id,b.version_id)
        self.assertNotEqual(a.version_id,build_strategy(DEMO_DEFINITION|{"fast":6}).version_id)

    def test_configuration_validation(self):
        base={"start_ms":T,"end_ms":T+M}
        for changes in ({"fee_bps":"nonsense"},{"initial_capital":0},{"mode":"portfolio"},{"max_positions":True},{"wallet_file":"x"}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):RunConfig.from_dict(base|changes)


if __name__ == "__main__": unittest.main()
