"""Command-line interface. Same engine as the API, useful for demos and quick checks.

Examples (from the project folder):
  python run_cli.py submit --workflow application_approval --file examples/inputs/approved.json
  python run_cli.py show req_xxxxx
  python run_cli.py audit req_xxxxx
"""

import argparse
import json
import sys
from pathlib import Path

from .errors import DecisionError
from .factory import build_engine

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="decision-cli", description="Configurable workflow decision platform")
    parser.add_argument("--db", default=str(ROOT / "data" / "decisions.db"), help="SQLite file to use")
    parser.add_argument("--config-dir", default=str(ROOT / "config"), help="folder with workflow YAML files")
    parser.add_argument("--fail-bureau", type=int, default=0,
                        help="make the simulated credit bureau fail its next N calls")
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit", help="submit a JSON file to a workflow")
    submit.add_argument("--workflow", required=True)
    submit.add_argument("--file", required=True)
    submit.add_argument("--key", help="idempotency key (defaults to a hash of the payload)")

    for name, help_text in [("show", "show a request"), ("audit", "show the audit trail"),
                            ("decision", "show the decision and its rule trace"),
                            ("retry", "retry a RETRY_PENDING request")]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("request_id")

    review = sub.add_parser("review", help="complete a MANUAL_REVIEW request")
    review.add_argument("request_id")
    review.add_argument("--decision", choices=["approve", "reject"], required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", default="")

    sub.add_parser("workflows", help="list loaded workflows")

    args = parser.parse_args(argv)
    engine = build_engine(args.db, args.config_dir, fail_bureau=args.fail_bureau)

    try:
        if args.command == "submit":
            data = json.loads(Path(args.file).read_text())
            result = engine.submit(args.workflow, data, args.key)
        elif args.command == "show":
            result = engine.get(args.request_id)
        elif args.command == "audit":
            result = engine.audit(args.request_id)
        elif args.command == "decision":
            result = engine.decision(args.request_id)
        elif args.command == "retry":
            result = engine.retry(args.request_id)
        elif args.command == "review":
            result = engine.review(args.request_id, args.decision, args.reviewer, args.note)
        else:
            result = engine.registry.summary()
    except DecisionError as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0
