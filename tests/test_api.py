"""HTTP-level tests: status codes, idempotency header, error mapping."""

from fastapi.testclient import TestClient

from conftest import CONFIG_DIR, sample
from decision.api import create_app


def make_client(tmp_path):
    app = create_app(db_path=tmp_path / "api.db", config_dir=CONFIG_DIR, fail_bureau=0)
    return TestClient(app)


def test_valid_submission_returns_201_and_duplicate_key_returns_200(tmp_path):
    client = make_client(tmp_path)
    body = {"workflow": "application_approval", "data": sample("approved.json")}
    headers = {"Idempotency-Key": "api-key-1"}

    first = client.post("/requests", json=body, headers=headers)
    second = client.post("/requests", json=body, headers=headers)

    assert first.status_code == 201
    assert first.json()["request"]["status"] == "APPROVED"
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["request"]["id"] == first.json()["request"]["id"]


def test_invalid_input_returns_422_with_errors(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/requests", json={"workflow": "application_approval", "data": {"age": "x"}})
    assert resp.status_code == 422
    assert "'pan' is required" in resp.json()["errors"]


def test_unknown_workflow_returns_404(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/requests", json={"workflow": "nope", "data": {}})
    assert resp.status_code == 404
    assert resp.json()["error"] == "UnknownWorkflow"


def test_audit_and_decision_endpoints(tmp_path):
    client = make_client(tmp_path)
    rid = client.post("/requests", json={"workflow": "application_approval",
                                          "data": sample("approved.json")}).json()["request"]["id"]

    audit = client.get(f"/requests/{rid}/audit")
    decision = client.get(f"/requests/{rid}/decision")

    assert audit.status_code == 200
    assert any(e["event"] == "decision" for e in audit.json()["events"])
    assert decision.status_code == 200
    assert decision.json()["decision"] == "APPROVE"


def test_review_of_non_manual_request_returns_409(tmp_path):
    client = make_client(tmp_path)
    rid = client.post("/requests", json={"workflow": "application_approval",
                                          "data": sample("approved.json")}).json()["request"]["id"]
    resp = client.post(f"/requests/{rid}/review", json={"decision": "approve", "reviewer": "X"})
    assert resp.status_code == 409


def test_manual_review_flow_over_http(tmp_path):
    client = make_client(tmp_path)
    rid = client.post("/requests", json={"workflow": "application_approval",
                                          "data": sample("manual_review.json")}).json()["request"]["id"]
    resp = client.post(f"/requests/{rid}/review",
                       json={"decision": "reject", "reviewer": "Ravi", "note": "docs mismatch"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"


def test_workflows_listing(tmp_path):
    client = make_client(tmp_path)
    names = [w["name"] for w in client.get("/workflows").json()]
    assert "application_approval" in names and "vendor_approval" in names
