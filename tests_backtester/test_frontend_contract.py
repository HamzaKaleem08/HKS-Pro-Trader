from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

from backtester.config import RunConfig
from backtester.errors import ValidationError
from backtester.simulation import simulate
from helpers import M,T,Scripted,dataset


class Inventory(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.assets=[];self.forms=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if "id" in attrs:self.ids.append(attrs["id"])
        if tag in ("script","link"):
            self.assets.append(attrs.get("src",attrs.get("href")))
        if tag=="form":self.forms.append(attrs)


class FrontendContracts(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]/"backtester"/"web"
        self.html=(self.root/"index.html").read_text();self.js=(self.root/"app.js").read_text()
        self.dom=Inventory();self.dom.feed(self.html)

    def test_all_direct_javascript_ids_exist_once(self):
        self.assertEqual(len(self.dom.ids),len(set(self.dom.ids)))
        self.assertFalse(set(re.findall(r'\$\("([A-Za-z]+)"\)',self.js))-set(self.dom.ids))

    def test_assets_local_and_present(self):
        self.assertEqual(set(self.dom.assets),{"/assets/app.js","/assets/style.css"})
        self.assertTrue(all((self.root/Path(x).name).is_file() for x in self.dom.assets))

    def test_no_persistent_token_or_dynamic_html_injection(self):
        for term in ("localStorage","sessionStorage","innerHTML","eval(","new Function("):
            self.assertNotIn(term,self.js)

    def test_mobile_and_non_executable_editor_disclosures(self):
        self.assertIn('name="viewport"',self.html)
        self.assertIn("not a Python/JavaScript sandbox",self.html)
        self.assertIn("@media(max-width:850px)",(self.root/"style.css").read_text())

    def test_futures_replay_requires_explicit_diagnostic_acknowledgment(self):
        cfg=RunConfig(start_ms=T+M,end_ms=T+6*M)
        with self.assertRaisesRegex(ValidationError,"explicit allow_uncertified_futures"):
            simulate(dataset(market="USDT_LINEAR_PERPETUAL"),Scripted(),cfg)
        self.assertIn('id="futuresAck" type="checkbox"',self.html)


if __name__=="__main__":unittest.main()
