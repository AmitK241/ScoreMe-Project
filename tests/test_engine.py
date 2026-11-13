"""End-to-end engine tests: happy path, invalid input, duplicates, dependency failure, retries,
partial save failure, rule changes and conditional rules."""

import shutil

import pytest

from conftest import CONFIG_DIR, no_sleep
from decision.errors import IdempotencyConflict, InvalidTransition
from decision.factory import build_engine
from decision.state import APPROVED, INVALID, MANUAL_REVIEW, PROCESSING, REJECTED, RETRY_PENDING

WF = "application_approval"


def events(engine, request_id):
    return [e["event"] for e in engine.audit(request_id)["events"]]


# ---------- happy path and explanation ----------

def test_happy_path_is_approved_with_rule_trace(engine, bureau, approved_data):
    req = engine.submit(WF, approved_data)["request"]

    assert req["status"] == APPROVED
    decision = engine.decision(req["id"])
    assert decision["decision"] == "APPROVE"
    statuses = {t["rule"]: t["status"] for t in decision["trace"]}
    assert statuses["credit_score_minimum"] == "passed"
    assert statuses["loan_to_income_ratio"] == "passed"
    assert statuses["self_employed_documents_verified"] == "skipped"  # salaried applicant
    assert decision["facts"]["credit_score"] == 720
    assert bureau.calls == 1


# ---------- invalid input ----------

def test_invalid_input_is_stored_as_invalid_and_never_reaches_the_bureau(engine, bureau, invalid_data):
    req = engine.submit(WF, invalid_data)["request"]

    assert req["status"] == INVALID
    joined = " | ".join(req["errors"])
    assert "'pan' is required" in joined
    assert "'full_name' is required" in joined
    assert "'age' must be of type integer" in joined
    assert "'employment' must be one of" in joined
    assert "unknown field 'extra_field'" in joined
    assert bureau.calls == 0


# ---------- business rejection ----------

def test_underage_applicant_is_rejected_before_any_dependency_call(engine, bureau, underage_data):
    req = engine.submit(WF, underage_data)["request"]

    assert req["status"] == REJECTED
    reasons = engine.decision(req["id"])["reasons"]
    assert any("at least 18" in r for r in reasons)
    assert bureau.calls == 0


def test_self_employed_without_documents_goes_to_manual_review(engine, self_employed_data):
    req = engine.submit(WF, self_employed_data)["request"]

    assert req["status"] == MANUAL_REVIEW
    trace = {t["rule"]: t for t in engine.decision(req["id"])["trace"]}
    assert trace["self_employed_documents_verified"]["status"] == "failed"


def test_manual_review_then_reviewer_approves(engine, manual_data):
    req = engine.submit(WF, manual_data)["request"]
    assert req["status"] == MANUAL_REVIEW

    done = engine.review(req["id"], "approve", reviewer="Ravi", note="income verified")

    assert done["status"] == APPROVED
    assert "manual review by Ravi" in engine.decision(req["id"])["reasons"][-1]
    with pytest.raises(InvalidTransition):
        engine.review(req["id"], "reject", reviewer="Ravi")


# ---------- idempotency and duplicates ----------

def test_same_idempotency_key_returns_original_without_reprocessing(engine, bureau, approved_data):
    first = engine.submit(WF, approved_data, idempotency_key="order-42")["request"]
    second = engine.submit(WF, approved_data, idempotency_key="order-42")

    assert second["duplicate"] is True
    assert second["request"]["id"] == first["id"]
    assert bureau.calls == 1
    assert "duplicate_request" in events(engine, first["id"])


def test_identical_payload_without_a_key_is_treated_as_duplicate(engine, bureau, approved_data):
    first = engine.submit(WF, approved_data)["request"]
    again = engine.submit(WF, approved_data)

    assert again["duplicate"] is True
    assert again["request"]["id"] == first["id"]
    assert bureau.calls == 1


def test_same_key_with_different_payload_is_a_conflict(engine, approved_data):
    engine.submit(WF, approved_data, idempotency_key="k1")
    changed = dict(approved_data, income=70000)

    with pytest.raises(IdempotencyConflict):
        engine.submit(WF, changed, idempotency_key="k1")


# ---------- dependency failure and retries ----------

def test_dependency_failure_goes_to_retry_pending_then_retry_succeeds(engine, bureau, approved_data):
    bureau.fail_next = 2   # max_attempts is 2, so the first run uses up both attempts

    req = engine.submit(WF, approved_data)["request"]

    assert req["status"] == RETRY_PENDING
    assert bureau.calls == 2
    done = engine.retry(req["id"])
    assert done["status"] == APPROVED
    assert done["retry_count"] == 1
    evs = events(engine, req["id"])
    assert evs.count("dependency_failed") == 2
    assert "dependency_succeeded" in evs


def test_request_stays_retryable_until_the_dependency_recovers(engine, bureau, approved_data):
    bureau.fail_next = 4

    req = engine.submit(WF, approved_data)["request"]
    assert req["status"] == RETRY_PENDING

    still_down = engine.retry(req["id"])
    assert still_down["status"] == RETRY_PENDING
    assert still_down["retry_count"] == 1

    final = engine.retry(req["id"])
    assert final["status"] == APPROVED
    assert final["retry_count"] == 2


def test_cannot_retry_a_finished_request(engine, approved_data):
    req = engine.submit(WF, approved_data)["request"]
    with pytest.raises(InvalidTransition):
        engine.retry(req["id"])


# ---------- partial save failure ----------

def test_partial_save_failure_rolls_back_and_retry_reuses_bureau_result(engine, bureau, approved_data, monkeypatch):
    original = engine.store._insert_decision
    failures = {"left": 1}

    def flaky(*args, **kwargs):
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("simulated disk failure while saving the decision")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine.store, "_insert_decision", flaky)
    with pytest.raises(RuntimeError):
        engine.submit(WF, approved_data)

    stuck = engine.store.list_requests()[0]
    assert stuck["status"] == PROCESSING                # the failed save did not half-apply
    assert engine.store.get_decision(stuck["id"]) is None
    assert bureau.calls == 1

    done = engine.retry(stuck["id"])
    assert done["status"] == APPROVED
    # The bureau result was committed before the failing save, and the retry resumes after that stage,
    # so the bureau is not called a second time.
    assert bureau.calls == 1
    assert "dependency_succeeded" in events(engine, stuck["id"])


def test_failure_right_after_bureau_call_means_retry_does_not_call_bureau_again(engine, bureau, approved_data, monkeypatch):
    original_commit = engine.store.commit_transition
    failures = {"left": 1}

    def flaky_commit(request_id, to_status, *, stage=None, **kwargs):
        # Fail the save that moves the request from the bureau stage to the rules stage.
        if stage == "risk_rules" and failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("simulated crash between stages")
        return original_commit(request_id, to_status, stage=stage, **kwargs)

    monkeypatch.setattr(engine.store, "commit_transition", flaky_commit)
    with pytest.raises(RuntimeError):
        engine.submit(WF, approved_data)

    stuck = engine.store.list_requests()[0]
    assert stuck["current_stage"] == "credit_check"
    assert bureau.calls == 1

    done = engine.retry(stuck["id"])
    assert done["status"] == APPROVED
    assert bureau.calls == 1
    assert "dependency_reused" in events(engine, stuck["id"])


# ---------- configurability ----------

def test_rule_change_alters_decision_without_code_change(tmp_path, approved_data):
    strict_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, strict_dir)
    rule_file = strict_dir / "application_approval.yaml"
    rule_file.write_text(rule_file.read_text().replace("value: 650", "value: 750"))

    original = build_engine(tmp_path / "a.db", CONFIG_DIR, sleep=no_sleep)
    stricter = build_engine(tmp_path / "b.db", strict_dir, sleep=no_sleep)

    old = original.submit(WF, approved_data)["request"]
    new = stricter.submit(WF, approved_data)["request"]

    assert old["status"] == APPROVED
    assert new["status"] == MANUAL_REVIEW
    assert "720" in " ".join(stricter.decision(new["id"])["reasons"])
    # Each decision records the config version it was made under.
    assert original.decision(old["id"])["config_hash"] != stricter.decision(new["id"])["config_hash"]


def test_conditional_rule_only_applies_when_its_condition_is_true(engine, approved_data):
    req = engine.submit(WF, approved_data)["request"]
    trace = {t["rule"]: t for t in engine.decision(req["id"])["trace"]}
    assert trace["self_employed_documents_verified"]["status"] == "skipped"
