const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const py = fs.readFileSync('app.py', 'utf8');
const selector = py.match(/function selectEquityPoints\(source,range\)\{[\s\S]*?\n\}/);
const renderer = py.match(/function renderEquity\(\)\{[\s\S]*?\n\}\nfunction rowOfTrade/);
assert.ok(selector, 'selectEquityPoints function must exist');
assert.ok(renderer, 'renderEquity function must exist');
const nodes = [];
const summary = {textContent:''};
const svg = {replaceChildren(){nodes.length = 0}, appendChild(n){nodes.push(n)}};
const ctx = {
  document: {createElementNS(tag) {
    return {tag, attrs:{}, setAttribute(k,v){this.attrs[k]=String(v)},
            appendChild(){}, set textContent(v){this.txt=v}};
  }},
  el(name){return name === 'equity-chart' ? svg : summary},
  fmt(v){return Number(v).toFixed(2)},
  money(v){return '$'+Number(v).toFixed(2)},
};
vm.createContext(ctx);
vm.runInContext('let equityRange=30, equityRecent=[], equityAll=[], equityAllLoadedCount=-1, equityTotalTrades=0;\n' +
  selector[0]+'\n'+renderer[0].slice(0,renderer[0].lastIndexOf('\nfunction rowOfTrade')), ctx);
const ledger = [
  {balance:1000, t:1}, {balance:1007, t:2}, {balance:1002, t:3},
  {balance:1005, t:4}, {balance:1001, t:5}
];
assert.deepEqual(Array.from(vm.runInContext('selectEquityPoints',ctx)(ledger, 2)).map(x=>x.t),[3,4,5]);
assert.equal(vm.runInContext('selectEquityPoints',ctx)(ledger,30).length,5);
assert.equal(vm.runInContext('selectEquityPoints',ctx)(ledger,'all').length,5);
ctx.equityRecent=ledger; // context lexical bindings are assigned below
// Use assignment into the original context, not a new lexical realm.
ctx.argumentsLedger=ledger;
vm.runInContext('equityRecent=argumentsLedger; equityRange=30;',ctx);
vm.runInContext('renderEquity()',ctx);
console.log('DEBUG NODES',nodes.map(x=>({tag:x.tag,strokeWidth:x.attrs['stroke-width'],stroke:x.attrs.stroke})));console.log('DEBUG SUMMARY',summary.textContent);
const strokes=nodes.filter(x=>x.tag==='path'&&x.attrs['stroke-width']==='4.25');
assert.equal(strokes.length,4,'One segment for each real closed-trade balance change');
assert.deepEqual(strokes.map(x=>x.attrs.stroke),['#35df9f','#ff687a','#35df9f','#ff687a']);
assert.ok(strokes.every(x=>x.attrs.d.includes(' C')),'Smooth segments connect actual endpoints');
assert.match(summary.textContent,/4 closed trades/);
console.log('Equity chart selection, actual-point segments and green/red logic: OK');
