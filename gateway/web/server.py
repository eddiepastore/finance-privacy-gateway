"""Dependency-free web server (stdlib http.server).

Routes:
  GET  /                      -> dashboard SPA (static/index.html)
  GET  /api/run?period=&privacy_mode=&role=  -> dashboard JSON payload
  POST /api/review/<id>/approve  (body: {"approved_text": "..."}) -> in-memory approval

Run: python3 scripts/serve.py  (then open http://127.0.0.1:8765)
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .api import build_dashboard_payload

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# In-memory approval state (review_item_id -> {"status","approved_text"}). Demo-grade only.
_APPROVALS: dict = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            path = os.path.join(STATIC_DIR, "index.html")
            with open(path, "rb") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/run":
            q = parse_qs(parsed.query)
            try:
                payload = build_dashboard_payload(
                    period=q.get("period", ["2026-03"])[0],
                    privacy_mode=q.get("privacy_mode", ["generalized_semantic_labels"])[0],
                    role=q.get("role", ["cfo"])[0],
                )
                # overlay any in-memory approvals
                for ri in payload["review_items"]:
                    a = _APPROVALS.get(ri["review_item_id"])
                    if a:
                        ri["status"] = a["status"]
                        ri["approved_text"] = a.get("approved_text")
                self._json(200, payload)
            except Exception as e:  # surface errors to the UI instead of a blank 500
                self._json(500, {"error": str(e)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "review" and parts[3] == "approve":
            rid = parts[2]
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            _APPROVALS[rid] = {"status": "approved", "approved_text": body.get("approved_text")}
            self._json(200, {"status": "approved", "review_item_id": rid})
            return
        self._json(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8765):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Gateway dashboard on http://{host}:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()
