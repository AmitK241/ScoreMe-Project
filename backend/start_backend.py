"""Launcher for the Decision Platform Backend (runnable from inside backend/ or root)."""

import os
import sys
from pathlib import Path

# Locate project root and backend dir
CURRENT_DIR = Path(__file__).resolve().parent
if CURRENT_DIR.name == "backend":
    BACKEND_DIR = CURRENT_DIR
    ROOT = CURRENT_DIR.parent
else:
    ROOT = CURRENT_DIR
    BACKEND_DIR = ROOT / "backend"

SRC_DIR = ROOT / "src"

for p in [ROOT, BACKEND_DIR, SRC_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import uvicorn
from main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print("==================================================")
    print(f" Starting Backend API on http://{host}:{port}")
    print(f" Interactive Swagger Docs: http://{host}:{port}/docs")
    print("==================================================")
    uvicorn.run(app, host=host, port=port)

