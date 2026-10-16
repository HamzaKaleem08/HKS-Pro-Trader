import ast
import hashlib
from pathlib import Path
import unittest

from backtester.common import decimal, digest, timestamp, utc
from backtester.errors import ValidationError


class FoundationTests(unittest.TestCase):
    def test_legacy_source_unchanged(self):
        data = (Path(__file__).resolve().parent / "fixtures" / "legacy_scanner.py").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), "88eef04b3501730e8d719aec399ce0899909024931b93a9e456f75de18259a9d")
        tree = ast.parse(data)
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == "scan_logic" for n in tree.body))

    def test_decimal_errors_are_controlled(self):
        for v in ["not decimal", "NaN", "Infinity", True, {}, "1e999", "1e-1000"]:
            with self.subTest(v=v), self.assertRaises(ValidationError):
                decimal(v)

    def test_explicit_utc(self):
        t = timestamp("2025-11-01T00:00:00Z")
        self.assertEqual(utc(t), "2025-11-01T00:00:00.000Z")
        for v in ["2025-11-01", "2025-11-01T00:00:00", 1_761_955_200]:
            with self.assertRaises(ValidationError): timestamp(v)

    def test_stable_decimal_hash(self):
        self.assertEqual(digest({"x": decimal("1.2"), "y": 4}), digest({"y": 4, "x": decimal("1.2")}))


if __name__ == "__main__":
    unittest.main()
