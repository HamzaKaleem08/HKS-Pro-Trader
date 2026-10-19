"""Loopback-only static proof server. No Python strategies or trading run here."""
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import argparse, hashlib, base64, json

ROOT=Path(__file__).resolve().parent
def policies():
    script=(ROOT/'web'/'sandbox-frame.js').read_bytes()
    h=base64.b64encode(hashlib.sha256(script).digest()).decode()
    common="default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'"
    return {
       'app':common+"; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self'; connect-src 'self'; frame-src 'self'; img-src 'self'; frame-ancestors 'none'",
       'sandbox':common+f"; script-src 'sha256-{h}' blob: 'unsafe-eval'; worker-src blob:; connect-src 'none'; frame-src 'none'; frame-ancestors 'self'",
       'financial':common+"; script-src 'self' 'unsafe-eval'; worker-src 'self'; connect-src 'self'",
       'inert':"default-src 'none'; sandbox; frame-ancestors 'none'"
    }

class Handler(SimpleHTTPRequestHandler):
    extensions_map={**SimpleHTTPRequestHandler.extensions_map,'.wasm':'application/wasm','.js':'text/javascript','.json':'application/json','.gz':'application/gzip'}
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy','same-origin')
        self.send_header('Cross-Origin-Embedder-Policy','require-corp')
        self.send_header('Cross-Origin-Resource-Policy','cross-origin' if self.path.startswith('/vendor/') else 'same-origin')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        path=self.path.split('?')[0]
        key='inert' if path=='/vendor/pyodide/console.html' else ('sandbox' if path=='/sandbox.html' else ('financial' if path=='/financial-worker.js' else 'app'))
        self.send_header('Content-Security-Policy',policies()[key])
        super().end_headers()
    def log_message(self,*a):pass

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8096);args=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print('Static browser proof on loopback port',server.server_port,flush=True)
    server.serve_forever()
