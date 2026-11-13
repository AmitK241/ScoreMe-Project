"""Entry point for the command-line interface. Run: python scripts/run_cli.py --help"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from decision.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
