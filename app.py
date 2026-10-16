"""Gunicorn/Replit entrypoint. No legacy scanner, wallets or executable sandbox."""
import os
from backtester.web import create_app

# A published process defaults to fail-closed persistent production settings.
app=create_app(hosted=os.environ.get("HKS_BACKTEST_ENV","production")!="local",
               async_jobs=True,port=int(os.environ.get("PORT","8080")))
