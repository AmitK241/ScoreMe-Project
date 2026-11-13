"""Launch both Backend (port 8000) and Frontend (port 3000) concurrently."""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    print("==================================================")
    print(" Starting Full Decision Platform (Backend + Frontend)")
    print("==================================================")

    # Launch Backend
    backend_proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "start_backend.py")])
    time.sleep(1)

    # Launch Frontend
    frontend_proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "start_frontend.py")])

    print("\n[OK] Both services are running!")
    print("-> Frontend Dashboard: http://localhost:3000")
    print("-> Backend API & Docs: http://127.0.0.1:8000/docs\n")
    print("Press Ctrl+C to terminate both services.\n")

    try:
        backend_proc.wait()
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\nStopping services...")
        backend_proc.terminate()
        frontend_proc.terminate()
        backend_proc.wait()
        frontend_proc.wait()
        print("All stopped.")

if __name__ == "__main__":
    main()

