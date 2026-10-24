"""Regression tests for independent HKS Bot2 MEXC Spot PAPER engine.
No public network requests. No exchange keys. Temporary SQLite only.
"""
import os
import tempfile
import unittest
from decimal import Decimal as D
from unittest import mock

TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DIR.name + "/hks_test.sqlite3"
os.environ.pop("VERCEL", None)
os.environ.pop("REPLIT_DEPLOYMENT", None)
os.environ["HKS_CRON_TOKEN"] = "test-only-cron-token-12345678901234567890123"

import app as hks
import bot2_spot as b2
from sqlalchemy import select, delete


class Bot2Regression(unittest.TestCase):
    def setUp(self):
        self.bot = hks.app.extensions["hks_bot2"]
        m = self.bot["models"]
        with hks.Session.begin() as db:
            for key in ("bar", "position", "trade"):
                db.execute(delete(m[key]))
            db.execute(delete(hks.ClosedTrade))
            db.execute(delete(hks.Position))
            db.execute(delete(m["coin"]))
            for symbol in b2.COINS:
                db.add(m["coin"](symbol=symbol, signal="WAIT"))
            db.get(m["wallet"], 1).cash = D("1000")
            db.get(hks.Wallet, 1).cash = D("1000")
            health = db.get(m["health"], 1)
            health.last_attempt_ms = None
            health.last_success_ms = None
            health.scan_status = "NOT STARTED"
        self._auto_patcher = mock.patch.object(hks, "_ensure_automatic_scanner", return_value=None)
        self._auto_patcher.start()
        self.addCleanup(self._auto_patcher.stop)

    def test_01_separate_schema_and_dashboard(self):
        with hks.app.test_client() as client:
            page = client.get("/bot2")
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            self.assertIn('href="/">Future</a>', html)
            self.assertIn('href="/bot2" aria-current="page">Spot</a>', html)
            self.assertIn("TNKUSDT", html)
            self.assertIn("CYSUSDT", html)
            self.assertIn("MEXC Spot", html)
            self.assertIn("LIGHTWEIGHT PAPER ENGINE · BOT 2", html)
            self.assertIn('class="market-switch"', html)
            self.assertIn("TradingView Chart", html)
            self.assertIn("Wallet Performance", html)
            self.assertIn("Last 10 Closed Trades", html)
            self.assertIn("Reset 1K", html)
            self.assertNotIn("Spot paper trading dashboard", html)
            self.assertNotIn("Locked Strategy V1", html)
            root = client.get("/")
            self.assertEqual(root.status_code, 200)
            self.assertIn('href="/bot2">Spot</a>', root.get_data(as_text=True))
            self.assertIn("LIGHTWEIGHT PAPER ENGINE · BOT 1", root.get_data(as_text=True))
            self.assertIn("Reset 1K", root.get_data(as_text=True))
            data = client.get("/api/bot2/state").json
            self.assertEqual(data["bot"], "BOT 2")
            self.assertEqual(data["long_only"], True)
            self.assertEqual(data["score_min"], 85)
            self.assertEqual(data["initial_sl_multiplier"], 2)
            self.assertEqual({x["symbol"] for x in data["coins"]}, set(b2.COINS))
            self.assertEqual(data["realized_balance"], "1000.00")
            self.assertEqual(data["open_positions"], [])
            self.assertEqual(client.get("/api/state").status_code, 200)
        names = set(hks.Base.metadata.tables)
        self.assertIn("hks_wallet", names)
        self.assertIn("hks_b2_wallet", names)
        self.assertIn("hks_b2_closed_trade", names)
        self.assertIn("hks_b2_1m_bar", names)

    def _open(self, symbol="TNKUSDT", original=D("0.03")):
        with mock.patch.object(b2, "PAPER_ENABLED", True):
            with hks.Session.begin() as db:
                coins = self.bot["models"]["coin"]
                coin = db.get(coins, symbol)
                ok = self.bot["enter"](db, coin, 85, original, 1_000_000,
                    asks=[(D("0.1"), D("100000"))],
                    bids=[(D("0.0998"), D("100000"))])
                self.assertTrue(ok)
        with hks.Session() as db:
            return db.get(self.bot["models"]["position"], symbol)

    def test_02_lock_initial_sl_200pct_but_trail_100pct(self):
        p = self._open()
        self.assertEqual(p.direction, "LONG")
        self.assertEqual(p.score, 85)
        self.assertEqual(p.entry_price, D("0.1"))
        self.assertEqual(p.initial_stop, D("0.094"))
        self.assertEqual(p.reference_distance, D("0.006"))
        # Original 2R reference: 40% activation at +2.4%, not +4.8%.
        self.assertFalse(hks.trail_stop(p, D("0.1023")))
        self.assertTrue(hks.trail_stop(p, D("0.1030")))
        self.assertEqual(p.stop, D("0.1015"))
        with hks.Session() as db:
            self.assertEqual(db.get(hks.Wallet, 1).cash, D("1000"))
            self.assertEqual(db.scalar(select(hks.Position)), None)

    def test_03_stop_checked_before_next_candle_trail(self):
        p = self._open()
        with hks.Session.begin() as db:
            pos = db.get(self.bot["models"]["position"], "TNKUSDT")
            # Bar HIGH would raise trailing above this same bar LOW.
            # It cannot retroactively fill the raised stop within this bar.
            first = {"t": 1_000_000, "end": 1_060_000,
                     "o": D("0.1"), "h": D("0.103"),
                     "l": D("0.098"), "c": D("0.102")}
            self.assertIsNone(self.bot["process_position"](db, pos, [first]))
            self.assertEqual(pos.stop, D("0.1015"))
            self.assertIsNotNone(db.get(self.bot["models"]["position"], "TNKUSDT"))
        with hks.Session.begin() as db:
            pos = db.get(self.bot["models"]["position"], "TNKUSDT")
            nextbar = {"t": 1_060_000, "end": 1_120_000,
                       "o": D("0.102"), "h": D("0.102"),
                       "l": D("0.101"), "c": D("0.101")}
            trade = self.bot["process_position"](db, pos, [nextbar])
            self.assertIsNotNone(trade)
            self.assertEqual(trade.exit_reason, "TRAILING SL")
            self.assertEqual(trade.exit_price, D("0.1015") * (1 - b2.EXIT_SLIPPAGE))
        with hks.Session() as db:
            self.assertIsNone(db.get(self.bot["models"]["position"], "TNKUSDT"))
            self.assertEqual(db.scalar(select(hks.ClosedTrade)), None)
            self.assertEqual(db.get(hks.Wallet, 1).cash, D("1000"))

    def test_04_both_coins_one_wallet_no_futures_mutation(self):
        self._open("TNKUSDT")
        self._open("CYSUSDT")
        with hks.Session() as db:
            m = self.bot["models"]
            positions = db.scalars(select(m["position"])).all()
            self.assertEqual({p.symbol for p in positions}, set(b2.COINS))
            self.assertEqual(db.get(m["wallet"], 1).cash, D("899.900000000000"))
            self.assertEqual(db.get(hks.Wallet, 1).cash, D("1000"))
            self.assertEqual(db.scalar(select(hks.Position)), None)

    def test_05_public_cron_no_header_keeps_owner_routes_private(self):
        # Replace exactly the scanner captured by the Flask view's closure:
        # no exchange calls and no database writes from this route test.
        view = hks.app.view_functions["bot2_cron"]
        freevars = dict(zip(view.__code__.co_freevars, view.__closure__))
        cell = freevars["scan_once"]
        original_scan = cell.cell_contents
        stub = mock.Mock(return_value={"status": "ok", "processed": 2, "errors": {}})
        try:
            cell.cell_contents = stub
            with hks.app.test_client() as client:
                with mock.patch.object(b2, "PAPER_ENABLED", False):
                    for route in ("/bot2/wake", "/api/bot2/cron"):
                        r = client.get(route)
                        self.assertEqual(r.status_code, 503)
                        self.assertEqual(r.json["status"], "disabled")
                    stub.assert_not_called()
                with mock.patch.object(b2, "PAPER_ENABLED", True):
                    # Both direct URLs accept a bare GET (no secret/header).
                    for route in ("/bot2/wake", "/api/bot2/cron"):
                        r = client.get(route)
                        self.assertEqual(r.status_code, 200)
                        self.assertEqual(r.json["scan_status"], "ok")
                        self.assertEqual(r.json["scanned"], 2)
                    self.assertEqual(stub.call_count, 2)
                    for status in ("busy", "skipped"):
                        stub.return_value = {"status": status}
                        self.assertEqual(client.get("/bot2/wake").status_code, 202)
                    stub.return_value = {"status": "error", "reason": "fake test"}
                    self.assertEqual(client.get("/bot2/wake").status_code, 503)
                # Bot 1 secret control and all owner actions remain protected.
                self.assertEqual(client.get("/api/cron").status_code, 403)
                self.assertEqual(client.post("/api/bot2/position/TNKUSDT/close",
                                headers={"Origin": "http://localhost"}, json={}).status_code, 401)
        finally:
            cell.cell_contents = original_scan
        import inspect
        source = inspect.getsource(b2)
        self.assertNotIn("/api/v3/order", source)
        self.assertNotIn("PRIVATE_KEY", source)
        self.assertEqual(b2.COINS, ("TNKUSDT", "CYSUSDT"))

    def test_06_ohlc_continuity_refuses_fabricated_bars(self):
        rows = [[0, "1", "2", ".8", "1.1", "2", 0, "1"],
                [120000, "1.1", "1.5", "1", "1.2", "2", 0, "1"]]
        with mock.patch.object(b2, "_http_get", return_value=rows):
            with self.assertRaisesRegex(ValueError, "noncontiguous"):
                b2._bars("TNKUSDT", "1m", 100, 300000)
        with self.assertRaises(ValueError):
            b2._bars("BTCUSDT", "1m", 100, 300000)

    def test_07_manual_close_requires_owner_and_uses_real_public_book(self):
        self._open("TNKUSDT")
        with hks.app.test_client() as client:
            unauthenticated = client.post("/api/bot2/position/TNKUSDT/close",
                                           headers={"Origin": "http://localhost"},
                                           json={})
            self.assertEqual(unauthenticated.status_code, 401)
            with hks.Session() as db:
                self.assertIsNotNone(db.get(self.bot["models"]["position"], "TNKUSDT"))
            with mock.patch.object(hks, "owner_logged_in", return_value=True):
                with mock.patch.object(b2, "_book", return_value=(
                    [(D("0.0996"), D("5000"))], [(D("0.1000"), D("5000"))])):
                    response = client.post("/api/bot2/position/TNKUSDT/close",
                                           headers={"Origin": "http://localhost"},
                                           json={})
                    self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                    self.assertTrue(response.json["ok"])
        with hks.Session() as db:
            self.assertIsNone(db.get(self.bot["models"]["position"], "TNKUSDT"))
            trade = db.scalar(select(self.bot["models"]["trade"]))
            self.assertEqual(trade.exit_reason, "MANUAL PAPER CLOSE")
            self.assertEqual(db.get(hks.Wallet, 1).cash, D("1000"))
            self.assertEqual(db.scalar(select(hks.ClosedTrade)), None)

    def test_08_bot2_history_equity_and_isolated_reset(self):
        pos = self._open("TNKUSDT")
        with hks.Session.begin() as db:
            coin = db.get(self.bot["models"]["coin"], "TNKUSDT")
            coin.last_decision_end = 123456000
            db.add(self.bot["models"]["bar"](
                symbol="TNKUSDT",start_ms=900000,
                o=D("0.10"), h=D("0.11"), l=D("0.09"), c=D("0.10")))
        with hks.app.test_client() as client:
            h=client.get("/api/bot2/history?limit=100")
            e=client.get("/api/bot2/equity")
            self.assertEqual(h.status_code,200)
            self.assertEqual(e.status_code,200)
            self.assertEqual(h.json["trades"],[])
            self.assertGreaterEqual(len(e.json["points"]),1)
            # Headerless public endpoints do not unlock destructive controls.
            rejected=client.post("/api/bot2/reset",
                headers={"Origin":"http://localhost"},
                json={"password":"example-test-password","confirm":"RESET 1K"})
            self.assertEqual(rejected.status_code,401)
            with mock.patch.dict(os.environ,{"HKS_RESET_PASSWORD":"example-test-password"}):
                with mock.patch.object(hks,"owner_logged_in",return_value=True):
                    reset=client.post("/api/bot2/reset",
                        headers={"Origin":"http://localhost"},
                        json={"password":"example-test-password","confirm":"RESET 1K"})
                    self.assertEqual(reset.status_code,200,reset.get_data(as_text=True))
                    self.assertEqual(reset.json["bot"],2)
        with hks.Session() as db:
            m=self.bot["models"]
            self.assertIsNone(db.get(m["position"],"TNKUSDT"))
            self.assertEqual(db.get(m["wallet"],1).cash,D("1000"))
            self.assertEqual(db.get(hks.Wallet,1).cash,D("1000"))
            self.assertEqual(db.scalar(select(hks.Position)),None)
            self.assertIsNotNone(db.get(m["bar"],("TNKUSDT",900000)))
            self.assertEqual(db.get(m["coin"],"TNKUSDT").last_decision_end,123456000)

    def test_09_book_notional_and_spread(self):


        midprice, qty = b2._buy_quote([(D("0.1"), D("10000"))], D("50"))
        self.assertEqual(midprice, D("0.1"))
        self.assertEqual(qty, D("500"))
        with self.assertRaisesRegex(ValueError, "depth"):
            b2._buy_quote([(D("0.1"), D("1"))], D("50"))


if __name__ == "__main__":
    unittest.main()
