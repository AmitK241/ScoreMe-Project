"""Convenience launcher for the Decision Platform Frontend."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"

def main():
    port = int(os.environ.get("FRONTEND_PORT", "3000"))
    print(f"==================================================")
    print(f" Starting Frontend UI on http://localhost:{port}")
    print(f" Pointing to Backend at: http://127.0.0.1:8000")
    print(f"==================================================")

    # Check if node is available
    has_node = subprocess.run(["node", "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    if has_node:
        server_js = FRONTEND_DIR / "server.js"
        env = os.environ.copy()
        env["PORT"] = str(port)
        subprocess.run(["node", str(server_js)], env=env)
    else:
        # Fallback to python standard library http.server
        import http.server
        import socketserver

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

        with socketserver.TCPServer(("", port), Handler) as httpd:
            print(f"Serving frontend from {FRONTEND_DIR} via Python http.server on port {port}")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nStopped.")

if __name__ == "__main__":
    main()

