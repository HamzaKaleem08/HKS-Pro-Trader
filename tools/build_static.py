"""Build static metadata only. Never runs research, strategy Python or deployment."""
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from serve import policies
web=ROOT/'web';kernel=json.loads((web/'kernel.json').read_text())
for name in ['browser_adapter.py','browser_stream.py']:kernel[name]=(ROOT/name).read_text()
for name in ['browser_context.py','browser_sandbox_context.py']:
 context=ROOT/'runtime/backtester'/name
 if context.exists():kernel['backtester/'+name]=context.read_text()
(web/'kernel.json').write_text(json.dumps(kernel,sort_keys=True))
script=(web/'sandbox-frame.js').read_text()
(web/'sandbox.html').write_text('<!doctype html><meta charset="utf-8"><title>Opaque strategy realm</title><script>'+script+'</script>')
# Content-pinned URLs prevent an older service-worker or HTTP cache from mixing
# the new UI with the pre-context worker. Hashes are verified again by client.js.
digest=lambda name:hashlib.sha256((web/name).read_bytes()).hexdigest()
runtime=['kernel.json','strategy-worker.js','financial-worker.js','sandbox.html','runtime-integrity.js']
runtime+=['vendor/pyodide/'+n for n in ['pyodide.js','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']]
(web/'runtime-manifest.json').write_text(json.dumps({'schema':1,'context_contract':'HKS_BROWSER_COMPLETED_CONTEXT/2','assets':{n:digest(n) for n in runtime}},sort_keys=True))
import re
client=(web/'client.js').read_text()
client=re.sub(r"const MANIFEST_SHA256='[^']+';",f"const MANIFEST_SHA256='{digest('runtime-manifest.json')}';",client)
client=re.sub(r"from './runtime-integrity.js(?:\?sha256=[a-f0-9]+)?'",f"from './runtime-integrity.js?sha256={digest('runtime-integrity.js')}'",client)
(web/'client.js').write_text(client)
app=(web/'app.js').read_text()
app=re.sub(r"from './client.js(?:\?sha256=[a-f0-9]+)?'",f"from './client.js?sha256={digest('client.js')}'",app)
(web/'app.js').write_text(app)
boot=(web/'boot.js').read_text()
boot=re.sub(r"import\('./app.js(?:\?sha256=[a-f0-9]+)?'\)",f"import('./app.js?sha256={digest('app.js')}')",boot)
(web/'boot.js').write_text(boot)
index=(web/'index.html').read_text()
index=re.sub(r'src="boot.js(?:\?sha256=[a-f0-9]+)?"',f'src="boot.js?sha256={digest("boot.js")}"',index)
(web/'index.html').write_text(index)
p=policies()
headers='''/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
  Cross-Origin-Resource-Policy: same-origin
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=()
'''
# Pages redirects .html to extensionless paths. Both final and original paths
# need the exact sandbox/console policies; a desktop-only local test misses this.
for route,policy in [('/',p['app']),('/index.html',p['app']),('/index',p['app']),('/sandbox.html',p['sandbox']),('/sandbox',p['sandbox']),('/financial-worker.js',p['financial']),('/vendor/pyodide/console.html',p['inert']),('/vendor/pyodide/console',p['inert'])]:
 headers+=route+'\n  Content-Security-Policy: '+policy+'\n'
(web/'_headers').write_text(headers)
assets=['/','/index.html','/style.css','/boot.js','/app.js','/replay-consent.js','/storage.js','/client.js','/runtime-integrity.js','/runtime-manifest.json','/financial-worker.js','/strategy-worker.js','/sandbox.html','/kernel.json','/catalog.json','/candle-catalog.json']
assets += ['/vendor/pyodide/'+n for n in ['pyodide.js','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json']]
(web/'offline-assets.json').write_text(json.dumps(assets))
sw=(web/'sw.js').read_text()
sw_template=re.sub(r"const CACHE='[^']+';","const CACHE='BUILD';",sw)
version=hashlib.sha256(b''.join((web/n.lstrip('/')).read_bytes() for n in assets if n!='/')+sw_template.encode()).hexdigest()[:16]
sw=re.sub(r"const CACHE='[^']+';",f"const CACHE='hks-premium-static-{version}';",sw).replace("key.startsWith('hks-browser-proof-')","key.startsWith('hks-premium-static-')")
(web/'sw.js').write_text(sw)
receipt={'files':len([p for p in web.rglob('*') if p.is_file()]),'bytes':sum(p.stat().st_size for p in web.rglob('*') if p.is_file()),'build_id':version,'static_only':True,'cloudflare_functions':False}
(ROOT/'evidence/STATIC_BUILD.json').write_text(json.dumps(receipt,indent=2));print(receipt)
