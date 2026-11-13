"""Rule evaluation. Rules are plain data from config; this module only knows how to interpret them.

Every rule produces a TraceEntry, so the final decision can say exactly which rule fired and why.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import Rule

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class TraceEntry:
    rule: str
    status: str
    field: str
    actual: Any
    op: str
    expected: Any
    on_fail: str
    message: str

    def to_dict(self):
        return asdict(self)


def derive_facts(data):
    """Adds computed fields that rules can refer to. Keep this list short and documented."""
    facts = dict(data)
    loan, income = data.get("loan_amount"), data.get("income")
    if isinstance(loan, (int, float)) and isinstance(income, (int, float)) and income > 0:
        facts["loan_ratio"] = round(loan / income, 4)
    return facts


def compare(actual, op, expected):
    if op == "exists":
        return actual is not None and actual != ""
    if actual is None:
        return False
    try:
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op == "gte":
            return actual >= expected
        if op == "gt":
            return actual > expected
        if op == "lte":
            return actual <= expected
        if op == "lt":
            return actual < expected
        if op == "in":
            return actual in expected
        if op == "not_in":
            return actual not in expected
    except TypeError:
        return False
    return False


def evaluate_rule(rule: Rule, facts: dict) -> TraceEntry:
    actual = facts.get(rule.field)
    label = rule.description or rule.id

    if rule.when is not None and not compare(facts.get(rule.when.field), rule.when.op, rule.when.value):
        return TraceEntry(
            rule.id, SKIPPED, rule.field, actual, rule.op, rule.value, rule.on_fail,
            f"skipped: condition {rule.when.field} {rule.when.op} {rule.when.value!r} is not true",
        )

    if compare(actual, rule.op, rule.value):
        return TraceEntry(rule.id, PASSED, rule.field, actual, rule.op, rule.value, rule.on_fail, label)

    reason = "field is missing" if actual is None else f"actual {actual!r} is not {rule.op} {rule.value!r}"
    return TraceEntry(rule.id, FAILED, rule.field, actual, rule.op, rule.value, rule.on_fail, f"{label}: {reason}")


def evaluate_rules(rules, facts):
    """Returns (result, trace). result is 'pass', 'manual_review' or 'reject'.

    'reject' wins over 'manual_review': if any failed rule says reject, the request is rejected.
    """
    trace = [evaluate_rule(rule, facts) for rule in rules]
    failed = [t for t in trace if t.status == FAILED]
    if any(t.on_fail == "reject" for t in failed):
        result = "reject"
    elif failed:
        result = "manual_review"
    else:
        result = "pass"
    return result, trace
