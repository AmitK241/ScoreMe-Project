"""Convenience launcher for the Decision Platform Backend."""

import os
import sys
from pathlib import Path

# Add src, root, and backend to sys.path
ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
SRC_DIR = ROOT / "src"

for p in [ROOT, BACKEND_DIR, SRC_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import uvicorn
from backend.main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print("==================================================")
    print(f" Starting Backend API on http://{host}:{port}")
    print(f" Interactive Swagger Docs: http://{host}:{port}/docs")
    print("==================================================")
    uvicorn.run(app, host=host, port=port)
