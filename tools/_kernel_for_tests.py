"""Expose only the bundled trusted kernel for portable host-side test oracles.

Never execute uploaded/pasted strategies. Actual on_bar runs only in Pyodide.
"""
import json,re,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEMP=tempfile.TemporaryDirectory(prefix='hks-smc-trusted-kernel-')
for name,source in json.loads((ROOT/'web/kernel.json').read_text()).items():
    if not re.fullmatch(r'backtester/[a-z_]+\.py|browser_adapter\.py|browser_stream\.py',name):
        raise ValueError('Unexpected trusted-kernel source path')
    path=Path(TEMP.name)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
sys.path.insert(0,TEMP.name)
