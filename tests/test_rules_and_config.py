"""Unit tests for rule evaluation, input validation and config checking."""

import pytest

from conftest import CONFIG_DIR
from decision.config import ConfigError, WorkflowRegistry, parse_workflow
from decision.rules import derive_facts, evaluate_rule, evaluate_rules
from decision.config import Rule, Condition
from decision.validation import validate_input


def threshold(rule_id="r", field="x", op="gte", value=10, on_fail="reject", when=None):
    return Rule(id=rule_id, type="threshold", field=field, op=op, value=value, on_fail=on_fail, when=when)


# ---------- rules ----------

def test_missing_field_fails_with_clear_message():
    entry = evaluate_rule(threshold(), {})
    assert entry.status == "failed"
    assert "field is missing" in entry.message


def test_reject_wins_over_manual_review():
    rules = [threshold("soft", value=100, on_fail="manual_review"), threshold("hard", value=100, on_fail="reject")]
    result, _ = evaluate_rules(rules, {"x": 1})
    assert result == "reject"


def test_manual_review_when_only_soft_rules_fail():
    rules = [threshold("soft", value=100, on_fail="manual_review")]
    result, _ = evaluate_rules(rules, {"x": 1})
    assert result == "manual_review"


def test_condition_false_means_rule_is_skipped_and_cannot_fail():
    rule = threshold(value=100, when=Condition(field="kind", op="eq", value="special"))
    entry = evaluate_rule(rule, {"x": 1, "kind": "normal"})
    assert entry.status == "skipped"
    result, _ = evaluate_rules([rule], {"x": 1, "kind": "normal"})
    assert result == "pass"


def test_derived_loan_ratio():
    assert derive_facts({"loan_amount": 20000, "income": 60000})["loan_ratio"] == 0.3333
    assert "loan_ratio" not in derive_facts({"loan_amount": 1, "income": 0})


# ---------- validation ----------

SCHEMA = {"age": {"type": "integer", "required": True}, "tag": {"type": "string", "required": False,
                                                              "allowed": ["a", "b"]}}


def test_validation_accepts_good_input():
    assert validate_input(SCHEMA, {"age": 3}) == []


def test_validation_reports_type_enum_and_unknown_fields():
    errors = validate_input(SCHEMA, {"age": True, "tag": "z", "oops": 1})
    assert "'age' must be of type integer" in errors
    assert any("'tag' must be one of" in e for e in errors)
    assert "unknown field 'oops'" in errors


def test_validation_rejects_non_object():
    assert validate_input(SCHEMA, [1, 2]) == ["request data must be a JSON object"]


# ---------- config ----------

def test_unknown_rule_reference_is_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "workflow: bad\nrules: {}\nstages:\n  - name: s\n    type: rules\n    rules: [ghost]\n    next: APPROVE\n"
    )
    with pytest.raises(ConfigError, match="unknown rule"):
        WorkflowRegistry(tmp_path)


def test_unknown_next_stage_is_rejected():
    data = {"workflow": "w", "rules": {"r": {"type": "mandatory", "field": "a", "op": "exists"}},
            "stages": [{"name": "s", "type": "rules", "rules": ["r"], "next": "nowhere"}]}
    with pytest.raises(ConfigError, match="unknown next stage"):
        parse_workflow(data)


def test_unknown_operator_is_rejected():
    data = {"workflow": "w", "rules": {"r": {"type": "threshold", "field": "a", "op": "approximately"}},
            "stages": [{"name": "s", "type": "rules", "rules": ["r"], "next": "APPROVE"}]}
    with pytest.raises(ConfigError, match="unknown operator"):
        parse_workflow(data)


def test_reload_keeps_previous_config_when_new_file_is_broken(tmp_path):
    for f in CONFIG_DIR.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text())
    registry = WorkflowRegistry(tmp_path)
    (tmp_path / "broken.yaml").write_text("workflow: [unclosed")

    with pytest.raises(ConfigError):
        registry.reload()
    assert registry.get("application_approval")   # still usable


def test_both_example_workflows_load():
    registry = WorkflowRegistry(CONFIG_DIR)
    names = {w["name"] for w in registry.summary()}
    assert {"application_approval", "vendor_approval"} <= names
