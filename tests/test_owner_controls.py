"""Regression tests for owner access, one-click paper close and Reset 1K isolation."""
import os
import sys
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

_TMP = tempfile.TemporaryDirectory(prefix="hks-owner-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_TMP.name) / "paper.sqlite3")
os.environ["HKS_RESET_PASSWORD"] = "owner-only-test-password"
os.environ.pop("VERCEL", None)
os.environ.pop("REPLIT_DEPLOYMENT", None)
os.environ.pop("REPLIT_ENVIRONMENT", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as hks  # noqa: E402

# Prevent background scanner/network calls in test_client; route semantics unchanged.
hks.ON_VERCEL = True


def post(client, path, payload):
    return client.post(path, json=payload, base_url="https://localhost",
                       headers={"Origin": "https://localhost"})


def session_coin(symbol, score=62, mode="NORMAL", signal="WAIT"):
    return hks.Coin(symbol=symbol, mode=mode, score=score, trade_score=79,
                    signal=signal, last_bar_end=900000, last_decision_end=900000)


class OwnerControlsTest(unittest.TestCase):
    def test_auth_close_reset_and_market_preservation(self):
        client = hks.app.test_client()
        self.assertFalse(client.get("/api/owner/status", base_url="https://localhost").json["owner"])
        self.assertEqual(post(client, "/api/mode/all", {"mode":"REVERSE","confirm":"ALL COINS"}).status_code, 401)
        self.assertEqual(post(client, "/api/position/ETHUSDT/close", {}).status_code, 401)
        self.assertEqual(post(client, "/api/reset", {"password":"owner-only-test-password","confirm":"RESET 1K"}).status_code, 401)
        self.assertEqual(post(client, "/api/owner/login", {"password":"wrong"}).status_code, 403)
        login = post(client, "/api/owner/login", {"password":"owner-only-test-password"})
        self.assertEqual(login.status_code, 200, login.json)
        self.assertIn("HttpOnly", login.headers["Set-Cookie"])
        self.assertIn("Secure", login.headers["Set-Cookie"])
        self.assertTrue(client.get("/api/owner/status", base_url="https://localhost").json["owner"])

        with hks.Session.begin() as db:
            db.add(session_coin("BTCUSDT", score=46, mode="REVERSE", signal="OPEN LONG"))
            db.get(hks.Wallet,1).cash = D("850")
            db.get(hks.GlobalMode,1).mode = "REVERSE"
            db.add(hks.Position(symbol="BTCUSDT", direction="LONG", mode="REVERSE",
                                original_signal="LONG", score=80, entry_ms=123,
                                entry_price=D("100"), qty=D("1"), stop=D("98"),
                                initial_stop=D("98"), margin=D("100"),
                                entry_fee=D("0.04"), mfe_frac=D("0"), mae_frac=D("0"),
                                reference_distance=D("4")))

        self.assertEqual(post(client, "/api/reset", {"password":"bad","confirm":"RESET 1K"}).status_code, 403)
        with hks.Session() as db:
            self.assertEqual(db.get(hks.Wallet,1).cash, D("850"))
            self.assertIsNotNone(db.get(hks.Position,"BTCUSDT"))

        response = post(client, "/api/reset", {"password":"owner-only-test-password","confirm":"RESET 1K"})
        self.assertEqual(response.status_code, 200, response.json)
        with hks.Session() as db:
            self.assertEqual(db.get(hks.Wallet,1).cash, D("1000"))
            self.assertIsNone(db.get(hks.Position,"BTCUSDT"))
            coin = db.get(hks.Coin,"BTCUSDT")
            self.assertEqual(coin.score, 46)
            self.assertEqual(coin.trade_score, 79)
            self.assertEqual(coin.last_decision_end, 900000)
            self.assertEqual(coin.mode, "REVERSE")
            self.assertEqual(coin.signal, "WAIT")
            self.assertEqual(db.get(hks.GlobalMode,1).mode, "REVERSE")

        with hks.Session.begin() as db:
            db.add(session_coin("ETHUSDT", score=58, mode="NORMAL", signal="OPEN LONG"))
            db.get(hks.Wallet,1).cash = D("900")
            db.add(hks.Position(symbol="ETHUSDT", direction="LONG", mode="NORMAL",
                                original_signal="LONG", score=80, entry_ms=123,
                                entry_price=D("100"), qty=D("1"), stop=D("98"),
                                initial_stop=D("98"), margin=D("100"),
                                entry_fee=D("0.04"), mfe_frac=D("0"), mae_frac=D("0"),
                                reference_distance=D("4")))
        with patch.object(hks, "market_prices", return_value={"ETHUSDT": D("105")}):
            result = post(client, "/api/position/ETHUSDT/close", {})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["reason"], "MANUAL CLOSE")
        with hks.Session() as db:
            self.assertIsNone(db.get(hks.Position,"ETHUSDT"))
            self.assertEqual(db.scalar(hks.select(hks.func.count()).select_from(hks.ClosedTrade)), 1)

        self.assertEqual(post(client, "/api/owner/logout", {}).status_code, 200)
        self.assertFalse(client.get("/api/owner/status", base_url="https://localhost").json["owner"])
        self.assertEqual(post(client, "/api/mode/all", {"mode":"NORMAL","confirm":"ALL COINS"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
