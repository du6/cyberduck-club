#!/usr/bin/env python3
# Tiny frame collector: POST /<name> with a data-URL or raw bytes body -> written to OUTDIR/<name>.
import base64, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tiktok_frames"
os.makedirs(OUT, exist_ok=True)
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    def do_OPTIONS(self): self.send_response(204); self._cors(); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        name = os.path.basename(self.path.strip("/")) or "frame.bin"
        if body.startswith(b"data:"): body = base64.b64decode(body.split(b",", 1)[1])
        with open(os.path.join(OUT, name), "wb") as f: f.write(body)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
HTTPServer(("127.0.0.1", 8899), H).serve_forever()
