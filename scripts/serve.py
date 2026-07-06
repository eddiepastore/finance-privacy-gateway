"""Launch the unified gateway product (dashboard UI + Section-15 API + persistence).

Run: python3 scripts/serve.py [port]   (default 8770)
Then open http://127.0.0.1:8770 — use the Data tab to load the sample dataset or upload your own.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gateway.api.app import serve  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("GATEWAY_PORT", "8770"))
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")  # set to 0.0.0.0 in containers
    serve(host=host, port=port)
