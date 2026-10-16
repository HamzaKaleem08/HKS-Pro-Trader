"""Actual local Chromium QA using an already installed Playwright/browser.

Run with the system Python that contains Playwright. No package/browser install.
Starts and stops only its own local server with disposable synthetic state.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    from playwright.sync_api import sync_playwright
    project=Path(__file__).resolve().parents[1]
    evidence=project/"evidence"/"browser"
    evidence.mkdir(parents=True,exist_ok=True)
    runtime=os.environ.get("HKS_TEST_PYTHON",sys.executable)
    checks=[];errors=[];external=[]
    with tempfile.TemporaryDirectory(prefix="hks-backtester-browser-") as tmp:
        state=Path(tmp)/"state";token=secrets.token_urlsafe(40)
        env=dict(os.environ,HKS_BACKTEST_TOKEN=token,PYTHONDONTWRITEBYTECODE="1")
        subprocess.run([runtime,"-m","backtester.cli","--state",str(state),"init-demo"],cwd=project,env=env,check=True,capture_output=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        origin=f"http://127.0.0.1:{port}"
        with (evidence/"local-server.log").open("w") as log:
            server=subprocess.Popen([runtime,"-m","backtester.cli","--state",str(state),"serve","--port",str(port)],cwd=project,env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(origin+"/health",timeout=1) as r:
                            if r.status==200:break
                    except OSError:time.sleep(.05)
                else:raise AssertionError("local server not ready")
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path=shutil.which("chromium"),headless=True,chromium_sandbox=True)
                    context=browser.new_context(viewport={"width":1440,"height":1000},accept_downloads=True)
                    page=context.new_page()
                    page.on("pageerror",lambda e:errors.append(str(e)))
                    page.on("request",lambda r:external.append(r.url) if not r.url.startswith(origin+"/") else None)
                    page.goto(origin,wait_until="networkidle")
                    assert page.locator("#runButton").is_disabled();checks.append("unauthenticated run control disabled")
                    page.locator("#token").fill(token);page.locator("#authForm button").click()
                    page.wait_for_function("document.getElementById('connection').textContent.includes('Authenticated')")
                    assert page.locator("#token").input_value()=="";checks.append("bearer authentication and password-field clearing")
                    assert "SYNTHETIC FIXTURE" in page.locator("#datasetInfo").inner_text();checks.append("synthetic provenance label")
                    page.select_option("#mode","shared");page.click("#runButton")
                    page.wait_for_selector("#result:not([hidden])",timeout=45000)
                    page.wait_for_function("document.querySelectorAll('#trades tr').length>1")
                    checks.append("actual worker-backed shared replay and computed report")
                    assert page.locator("#coins tr").count()==3;checks.append("two per-coin summary rows")
                    assert not page.locator("#next").is_disabled()
                    first_page=page.locator("#trades").inner_text();page.click("#next")
                    page.wait_for_function("document.getElementById('pageInfo').textContent.startsWith('Page 2')")
                    assert page.locator("#trades").inner_text()!=first_page;checks.append("server-side page 2 navigation")
                    page.select_option("#sort","net_pnl");page.select_option("#direction","desc")
                    page.wait_for_function("document.getElementById('pageInfo').textContent.startsWith('Page 1')")
                    page.wait_for_timeout(200)
                    values=page.locator("#trades tr").evaluate_all("rows=>rows.slice(1).map(r=>Number(r.children[4].textContent.replaceAll(',','')))")
                    assert values==sorted(values,reverse=True);checks.append("numeric net-PnL descending sort")
                    page.locator("#search").fill("ETHUSDT");page.locator("#search").dispatch_event("change")
                    page.wait_for_timeout(200)
                    symbols=page.locator("#trades tr").evaluate_all("rows=>rows.slice(1).map(r=>r.children[0].textContent)")
                    assert symbols and set(symbols)=={"ETHUSDT"};checks.append("symbol filtering")
                    page.locator("#trades button").first.click();page.wait_for_selector("#tradeDialog[open]")
                    detail=json.loads(page.locator("#tradeDetail").inner_text())
                    assert detail["holding_ms"]%60000==0
                    checks.append("trade-detail dialog and integer-minute duration evidence")
                    page.click("#closeDetail")
                    with page.expect_download() as download_info:page.click("#exportTrades")
                    download=download_info.value;download.save_as(evidence/"synthetic-browser-export.csv")
                    body=(evidence/"synthetic-browser-export.csv").read_bytes()
                    assert len(list(csv.DictReader(io.StringIO(body.decode()))))>25
                    checks.append("authenticated complete CSV browser download")
                    page.screenshot(path=str(evidence/"desktop-report.png"),full_page=True)
                    checks.append("actual desktop screenshot captured")
                    page.set_viewport_size({"width":390,"height":844});page.wait_for_timeout(100)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path=str(evidence/"mobile-width-report.png"),full_page=True)
                    checks.append("390px responsive layout without page overflow; actual mobile-width screenshot")
                    page.set_viewport_size({"width":1440,"height":1000})
                    definition=json.loads(page.locator("#definition").input_value());definition["fast"]=6
                    page.locator("#definition").fill(json.dumps(definition));page.click("#saveStrategy")
                    page.wait_for_function("document.getElementById('strategy').options.length===2")
                    checks.append("structured strategy save creates another immutable version")
                    page.select_option("#mode","individual");page.click("#runButton")
                    page.wait_for_function("document.getElementById('message').textContent.startsWith('Replay complete')",timeout=45000)
                    meta=json.loads(page.locator("#metadata").inner_text())
                    assert meta["config"]["mode"]=="individual" and meta["summary"]["starting_capital"]=="2000"
                    checks.append("actual independent-wallet run, $2000 total start for two symbols")
                    assert page.evaluate("localStorage.length===0 && sessionStorage.length===0")
                    page.reload(wait_until="networkidle");assert page.locator("#runButton").is_disabled()
                    checks.append("no persistent browser credential storage; reload relocks")
                    assert not errors,errors;assert not external,external
                    checks.append("no JavaScript exceptions or external network/asset requests")
                    browser.close()
                receipt={"status":"PASS","checks":checks,"check_count":len(checks),"javascript_errors":errors,
                         "external_requests":external,"browser":"system Chromium, headless with Chromium sandbox enabled",
                         "platform_limitations":["Native Windows and physical Android not executed","Mobile viewport is desktop Chromium emulation"],
                         "csv_sha256":hashlib.sha256(body).hexdigest()}
                (evidence/"BROWSER_RESULTS.json").write_text(json.dumps(receipt,indent=2))
                print(json.dumps(receipt,indent=2))
            finally:
                server.terminate()
                try:server.wait(timeout=5)
                except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=="__main__":main()
