"""Entry point for the command-line interface. Run: python run_cli.py --help"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from decision.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
