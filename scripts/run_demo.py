"""Runs seven scripted scenarios end to end and writes examples/decision_examples.md.

    python scripts/run_demo.py

It uses its own database under data/demo, so it never touches your real data.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from decision.errors import NotFound  # noqa: E402
from decision.factory import build_engine  # noqa: E402

INPUTS = ROOT / "examples" / "inputs"
WORK = ROOT / "data" / "demo"
OUT = ROOT / "examples" / "decision_examples.md"
WF = "application_approval"


def load(name, **changes):
    data = json.loads((INPUTS / name).read_text())
    data.update(changes)
    return data


def maybe_decision(engine, request_id):
    try:
        return engine.decision(request_id)
    except NotFound:
        return None


def audit_lines(engine, request_id):
    return [f"{e['stage'] or '-'} / {e['event']}" for e in engine.audit(request_id)["events"]]


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    engine = build_engine(WORK / "demo.db", ROOT / "config", sleep=lambda s: None)
    bureau = engine.dependencies["credit_bureau"]
    sections = []

    def add(title, what, data, request_id, extra=None):
        request = engine.get(request_id)
        decision = maybe_decision(engine, request_id)
        result = {"request_id": request_id, "status": request["status"], "retry_count": request["retry_count"]}
        if decision:
            result["decision"] = decision["decision"]
            result["reasons"] = decision["reasons"]
            result["rule_trace"] = [f"{t['rule']}: {t['status']} - {t['message']}" for t in decision["trace"]]
        if extra:
            result.update(extra)
        if request["errors"]:
            result["errors"] = request["errors"]
        sections.append({"title": title, "what": what, "input": data, "result": result,
                         "events": audit_lines(engine, request_id)})

    # 1. Happy path
    data = load("approved.json")
    rid = engine.submit(WF, data)["request"]["id"]
    add("1. Happy path: approved",
        "A complete, valid salaried application. Mandatory checks pass, the credit bureau returns 720, "
        "the loan-to-income ratio is 0.33, and the conditional self-employed rule is skipped.",
        data, rid)

    # 2. Invalid input
    data = load("invalid.json")
    rid = engine.submit(WF, data)["request"]["id"]
    add("2. Invalid input",
        "Missing required fields, a wrong type, a value outside the allowed list, and an unknown field. "
        "The request is stored as INVALID and the bureau is never called.",
        data, rid)

    # 3. Business rejection
    data = load("rejected_underage.json")
    rid = engine.submit(WF, data)["request"]["id"]
    add("3. Business rejection: applicant under 18",
        "The minimum-age rule fails with reject. The request stops at the first stage, so no bureau call is made.",
        data, rid)

    # 4. Manual review, then a human decides
    data = load("manual_review.json")
    rid = engine.submit(WF, data)["request"]["id"]
    engine.review(rid, "approve", reviewer="Ravi K.", note="income slips verified")
    add("4. Manual review, then reviewer approves",
        "The bureau returns 600, below the 650 minimum. That rule says manual_review, so the request waits for a "
        "person. The reviewer's decision is appended to the reasons and the audit trail.",
        data, rid)

    # 5. Duplicate request
    data = load("approved.json")
    before = bureau.calls
    dup = engine.submit(WF, data)
    add("5. Duplicate request",
        f"The same payload is sent again with no key, so it is matched by payload hash. The response says "
        f"duplicate=true, the original request is returned, and the bureau call count stays at {before} "
        f"-> {bureau.calls}.",
        data, dup["request"]["id"], extra={"duplicate": dup["duplicate"]})

    # 6. Dependency failure, then retry
    data = load("approved.json", applicant_id="APP-1002", full_name="Ritu Sen")
    bureau.fail_next = 2   # max_attempts is 2 for credit_check, so the first run gives up
    rid = engine.submit(WF, data)["request"]["id"]
    first_state = engine.get(rid)["status"]
    engine.retry(rid)
    add("6. Dependency failure, then retry succeeds",
        f"The bureau times out twice. The engine waits, retries, and gives up for this run, so the request is "
        f"{first_state}. Calling retry resumes at the failed stage and the bureau answers this time.",
        data, rid)

    # 7. Rule change without code change
    strict = WORK / "config_strict"
    shutil.copytree(ROOT / "config", strict)
    rule_file = strict / "application_approval.yaml"
    rule_file.write_text(rule_file.read_text().replace("value: 650", "value: 750"))
    strict_engine = build_engine(WORK / "demo.db", strict, sleep=lambda s: None)
    data = load("approved.json", applicant_id="APP-1003", full_name="Dev Mehta")
    rid = strict_engine.submit(WF, data)["request"]["id"]
    old_decision = engine.decision(sections[0]["result"]["request_id"])
    new_decision = strict_engine.decision(rid)
    sections.append({
        "title": "7. Requirement change: minimum score raised 650 -> 750",
        "what": "The same applicant data (credit score 720) is evaluated with a stricter YAML file and no code "
                "change. It now goes to manual review. The earlier APPROVE decision still records the config "
                f"it was made under (config {old_decision['config_hash']}), and this one records "
                f"{new_decision['config_hash']}.",
        "input": data,
        "result": {"request_id": rid, "status": strict_engine.get(rid)["status"],
                   "decision": new_decision["decision"], "reasons": new_decision["reasons"]},
        "events": audit_lines(strict_engine, rid),
    })

    lines = ["# Decision explanation examples", "",
             "Generated by `python run_demo.py`. Each example shows the input, the rules that fired, "
             "the output, and the audit trail.", ""]
    for s in sections:
        lines += [f"## {s['title']}", "", s["what"], "", "**Input**", "```json",
                  json.dumps(s["input"], indent=2), "```", "", "**Output**", "```json",
                  json.dumps(s["result"], indent=2, default=str), "```", "",
                  "**Audit trail (stage / event)**", "```", *s["events"], "```", ""]
    OUT.write_text("\n".join(lines))

    print(f"Wrote {OUT.relative_to(ROOT)}\n")
    for s in sections:
        r = s["result"]
        outcome = r.get("decision") or r["status"]
        print(f"{s['title']:<52} -> {r['status']:<14} {outcome}")


if __name__ == "__main__":
    main()
