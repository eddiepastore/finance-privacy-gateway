"""Launch the Section 15 REST API. Run: python3 scripts/serve_api.py [port]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gateway.api.app import serve  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("GATEWAY_PORT", "8780"))
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")  # set to 0.0.0.0 in containers
    serve(host=host, port=port)
