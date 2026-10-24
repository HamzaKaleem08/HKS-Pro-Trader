"""Verify Bot2 separate dashboard embedded JavaScript parses in Node."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

class Bot2DashboardJavaScript(unittest.TestCase):
    def test_dashboard_script_syntax(self):
        html=(Path(__file__).resolve().parents[1]/"templates"/"bot2.html").read_text(encoding="utf-8")
        snippets=re.findall(r"<script[^>]*>(.*?)</script>",html,re.S|re.I)
        self.assertEqual(len(snippets),1)
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",suffix=".js") as f:
            f.write(snippets[0].replace("{{ reset_ready | tojson }}","false"));f.flush()
            result=subprocess.run(["node","--check",f.name],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("doManualClose",snippets[0])
        self.assertIn("renderChart",snippets[0])
        self.assertIn("selectEquityPoints",snippets[0])
        self.assertIn("setEquityRange",snippets[0])
        self.assertIn("TNK",html)
        self.assertIn("CYS",html)
if __name__=="__main__":
    unittest.main()
