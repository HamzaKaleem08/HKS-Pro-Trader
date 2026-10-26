"""Focused tests for isolated Bot 1 parallel NORMAL/REVERSE ledger."""
import unittest
from decimal import Decimal as D
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from bot1_parallel import (
    BaseParallel, MODES, ModeWallet, ModePosition, ModeTrade, ModeEquity,
    ModeDecision, ModeExit, bootstrap, open_pair, close_position,
    check_position, reset_parallel, realized_equity, strategy_equity,
)

FEE=D("0.0004")
RISK=D("0.01")
CAP=D("0.3333333333")


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite:///:memory:",future=True)
        self.Session=sessionmaker(bind=self.engine,expire_on_commit=False,future=True)
        bootstrap(self.engine,self.Session,900000)
        self.coin=type("Coin",(),{"symbol":"BTCUSDT"})()
        self.signal={"original":"LONG","trade_score":85,
                     "stop_fraction":D("0.01"),"end_ms":1800000}

    def pair(self):
        with self.Session.begin() as db:
            return open_pair(db,self.coin,self.signal,D("100"),1800000,FEE,RISK,CAP,5)

    def test_initial_independent_wallets(self):
        with self.Session() as db:
            for mode in MODES:
                self.assertEqual(db.get(ModeWallet,mode).cash,D("2000"))
                self.assertEqual(realized_equity(db,mode),D("1000"))
                self.assertEqual(db.scalar(select(func.count()).select_from(ModeEquity).where(ModeEquity.mode==mode)),1)

    def test_qualified_signal_opens_opposite_positions(self):
        res=self.pair()
        self.assertEqual(res["NORMAL"][1],"OPEN")
        self.assertEqual(res["REVERSE"][1],"OPEN")
        with self.Session() as db:
            n=db.get(ModePosition,("NORMAL","BTCUSDT"))
            r=db.get(ModePosition,("REVERSE","BTCUSDT"))
            self.assertEqual(n.direction,"LONG")
            self.assertEqual(r.direction,"SHORT")
            self.assertEqual(n.qty,r.qty)
            self.assertLess(n.margin,D("334"))
            self.assertGreater(n.margin,D("330"))
            self.assertEqual(db.scalar(select(func.count()).select_from(ModeDecision)),2)

    def test_cap_and_cash_are_separate(self):
        self.pair()
        with self.Session() as db:
            n=db.get(ModePosition,("NORMAL","BTCUSDT"))
            self.assertGreater(db.get(ModeWallet,"NORMAL").cash,D("1600"))
            self.assertEqual(realized_equity(db,"NORMAL"),D("1000"))
            self.assertLess(n.margin,D("334"))
            eq,_=strategy_equity(db,"NORMAL",{"BTCUSDT":D("100")})
            self.assertEqual(eq,D("1000"))

    def test_close_one_mode_does_not_close_other(self):
        self.pair()
        with self.Session.begin() as db:
            long=db.get(ModePosition,("NORMAL","BTCUSDT"))
            trade=close_position(db,long,D("101"),1860000,"MANUAL CLOSE",FEE)
            self.assertEqual(trade.mode,"NORMAL")
        with self.Session() as db:
            self.assertIsNone(db.get(ModePosition,("NORMAL","BTCUSDT")))
            self.assertIsNotNone(db.get(ModePosition,("REVERSE","BTCUSDT")))
            self.assertGreater(realized_equity(db,"NORMAL"),D("1000"))
            self.assertEqual(realized_equity(db,"REVERSE"),D("1000"))
            self.assertIsNotNone(db.get(ModeExit,("NORMAL","BTCUSDT")))

    def test_stop_applied_before_next_bar_trailing(self):
        self.pair()
        with self.Session.begin() as db:
            p=db.get(ModePosition,("NORMAL","BTCUSDT"))
            original=p.stop
            def mark(_p,_b):pass
            def get_stop(pos,bar):
                return pos.stop if bar["l"]<=pos.stop else None
            def trail(pos,_):
                pos.stop+=D("0.01")
            check_position(db,p,[{"t":1800000,"end":1860000,
                                  "o":D("100"),"h":D("101"),"l":original-D("0.1")}],
                                  FEE,mark,get_stop,trail)
        with self.Session() as db:
            t=db.scalar(select(ModeTrade))
            self.assertEqual(t.exit_reason,"INITIAL SL HIT")

    def test_reset_clears_both_and_reseeds(self):
        self.pair()
        with self.Session.begin() as db:
            reset_parallel(db,2400000)
        with self.Session() as db:
            for mode in MODES:
                self.assertIsNone(db.get(ModePosition,(mode,"BTCUSDT")))
                self.assertEqual(realized_equity(db,mode),D("1000"))
                self.assertEqual(db.get(ModeWallet,mode).cash,D("2000"))
                self.assertEqual(db.scalar(select(func.count()).select_from(ModeEquity).where(ModeEquity.mode==mode)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(ModeDecision)),0)

    def test_existing_mode_does_not_duplicate(self):
        self.pair()
        with self.Session.begin() as db:
            # Next distinct decision on an open symbol should not duplicate positions.
            later=dict(self.signal,end_ms=2700000)
            res=open_pair(db,self.coin,later,D("100"),2700000,FEE,RISK,CAP,5)
            self.assertEqual(res["NORMAL"][1],"ALREADY_OPEN")
            self.assertEqual(res["REVERSE"][1],"ALREADY_OPEN")


if __name__=="__main__":
    unittest.main()
