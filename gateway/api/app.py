"""Stdlib HTTP server exposing the Section 15 API contracts.

File upload uses a raw CSV body with ?file_type=&filename= query params (avoids a multipart
dependency). All other endpoints take/return JSON. A lock serializes writes to the SQLite connection.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .repository import Repository
from .service import ApiService

_LOCK = threading.Lock()
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_STATIC = os.path.join(_ROOT, "gateway", "web", "static")
_SAMPLE = os.path.join(_ROOT, "sample_data")


class ApiHandler(BaseHTTPRequestHandler):
    service: ApiService = None  # injected in serve()

    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw) if raw else {}

    # ---- dispatch ---------------------------------------------------------------------------
    def _html(self, path):
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        parts = p.path.strip("/").split("/")
        q = parse_qs(p.query)
        try:
            if p.path in ("/", "/index.html"):
                return self._html(os.path.join(_STATIC, "index.html"))
            if p.path == "/api/health":
                return self._json(200, {"status": "ok"})
            # stateless demo payload (no persistence) — kept for the quick visual story
            if p.path == "/api/run":
                from ..web.api import build_dashboard_payload
                return self._json(200, build_dashboard_payload(
                    period=q.get("period", ["2026-03"])[0],
                    privacy_mode=q.get("privacy_mode", ["generalized_semantic_labels"])[0],
                    role=q.get("role", ["cfo"])[0],
                    llm_preference=q.get("model_provider", ["mock"])[0]))
            if p.path == "/api/datasets":
                return self._json(200, {"datasets": self.service.repo.list_datasets()})
            if len(parts) == 4 and parts[:2] == ["api", "datasets"] and parts[3] == "review-items":
                return self._json(200, self.service.list_review_items(
                    parts[2], role=q.get("role", ["cfo"])[0], period=q.get("period", [None])[0]))
            if len(parts) == 4 and parts[:2] == ["api", "datasets"] and parts[3] == "audit":
                return self._json(200, {"audit": self.service.repo.audit(parts[2])})
            # persisted dashboard payload for a real dataset
            if len(parts) == 4 and parts[:2] == ["api", "datasets"] and parts[3] == "dashboard":
                return self._json(200, self.service.dashboard_payload(
                    parts[2], role=q.get("role", ["cfo"])[0], period=q.get("period", [None])[0]))
            return self._json(404, {"error": "not found"})
        except Exception as e:
            return self._json(500, {"error": str(e)})

    def do_POST(self):
        p = urlparse(self.path)
        parts = p.path.strip("/").split("/")
        q = parse_qs(p.query)
        try:
            with _LOCK:
                # POST /api/fpa/commentary -> stateless: obfuscate an FP&A variance set, gate, model,
                # validate, rehydrate, and return drafts + privacy proof (no dataset/DB lifecycle).
                if parts == ["api", "fpa", "commentary"]:
                    from .fpa_bridge import fpa_commentary
                    return self._json(200, fpa_commentary(self._json_body()))

                # POST /api/datasets
                if parts == ["api", "datasets"]:
                    b = self._json_body()
                    ds = self.service.create_dataset(
                        b.get("name", "Untitled"), b.get("reporting_period", "2026-03"),
                        b.get("privacy_mode", "generalized_semantic_labels"), b.get("company_name"))
                    return self._json(201, {"dataset_id": ds["id"], "status": "created"})

                # POST /api/demo/seed  -> create dataset from bundled sample CSVs + run pipeline
                if parts == ["api", "demo", "seed"]:
                    b = self._json_body()
                    return self._json(200, self.service.seed_sample_dataset(
                        _SAMPLE, privacy_mode=b.get("privacy_mode", "generalized_semantic_labels"),
                        viewer_role=b.get("viewer_role", "cfo"),
                        llm_preference=b.get("model_provider", "mock")))

                # POST /api/analysis-runs
                if parts == ["api", "analysis-runs"]:
                    b = self._json_body()
                    return self._json(200, self.service.analyze(
                        b["dataset_id"], b["obfuscation_run_id"],
                        viewer_role=b.get("viewer_role", "cfo"),
                        llm_preference=b.get("model_provider", "mock"), period=b.get("period")))

                # POST /api/review-items/{id}/approve
                if len(parts) == 4 and parts[:2] == ["api", "review-items"] and parts[3] == "approve":
                    b = self._json_body()
                    res = self.service.approve(parts[2], b.get("approved_text"),
                                               b.get("reviewer_id", "user"), role=b.get("role", "cfo"))
                    return self._json(200 if res else 404, res or {"error": "not found"})

                # POST /api/review-items/{id}/request-revision
                if len(parts) == 4 and parts[:2] == ["api", "review-items"] and parts[3] == "request-revision":
                    b = self._json_body()
                    res = self.service.request_revision(parts[2], b.get("reason"),
                                                        b.get("reviewer_id", "user"))
                    return self._json(200 if res else 404, res or {"error": "not found"})

                # /api/datasets/{id}/...
                if len(parts) >= 4 and parts[:2] == ["api", "datasets"]:
                    did, action = parts[2], parts[3]
                    if action == "files":
                        content = self._body().decode("utf-8")
                        return self._json(200, self.service.upload_file(
                            did, q.get("file_type", ["actuals"])[0],
                            q.get("filename", ["upload.csv"])[0], content))
                    if action == "mappings":
                        b = self._json_body()
                        return self._json(200, self.service.save_mapping(did, b["file_id"], b["mapping"]))
                    if action == "calculate":
                        b = self._json_body()
                        return self._json(200, self.service.calculate(did, period=b.get("period")))
                    if action == "run":  # convenience: calculate + obfuscate + analyze
                        b = self._json_body()
                        return self._json(200, self.service.run_pipeline_steps(
                            did, viewer_role=b.get("viewer_role", "cfo"),
                            llm_preference=b.get("model_provider", "mock"), period=b.get("period"),
                            privacy_mode=b.get("privacy_mode")))
                    if action == "obfuscation-runs":
                        b = self._json_body()
                        return self._json(200, self.service.obfuscate(
                            did, b.get("calculation_run_id"), b.get("privacy_mode"), period=b.get("period")))
                    if action == "board-narrative":
                        b = self._json_body()
                        return self._json(200, self.service.board_narrative(
                            did, b.get("include_only_approved_items", True),
                            b.get("audience", "board"), b.get("tone", "concise_board_ready"),
                            period=b.get("period")))

                return self._json(404, {"error": "not found"})
        except KeyError as e:
            return self._json(400, {"error": f"missing field: {e}"})
        except Exception as e:
            return self._json(500, {"error": str(e)})


def serve(host="127.0.0.1", port=8780, db_path="output/gateway_api.db"):
    import os
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    ApiHandler.service = ApiService(Repository(db_path))
    httpd = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"Gateway API on http://{host}:{port}  (DB: {db_path})  Ctrl-C to stop")
    httpd.serve_forever()
