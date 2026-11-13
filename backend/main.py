"""Backend API server for Configurable Workflow Decision Platform.

Features:
- Full CORS support for decoupled frontend
- Workflow execution, idempotency, retries, and manual reviews
- Schema discovery for dynamic frontend forms
- Historical request auditing and live stats
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Ensure src/ is importable
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from decision.api import create_app  # noqa: E402
from decision.errors import DecisionError  # noqa: E402

# Models
class SubmitBody(BaseModel):
    workflow: str
    data: dict[str, Any] = Field(default_factory=dict)


class ReviewBody(BaseModel):
    decision: str  # "approve" or "reject"
    reviewer: str
    note: str = ""


def build_backend_app(db_path=None, config_dir=None, fail_bureau=None) -> FastAPI:
    base_app = create_app(db_path=db_path, config_dir=config_dir, fail_bureau=fail_bureau)
    engine = base_app.state.engine

    app = FastAPI(
        title="Decision Platform Backend API",
        version="1.0.0",
        description="REST API powering the Decision Engine with workflow execution and audit trails.",
    )
    app.state.engine = engine

    # Enable CORS for frontend running on any host/port
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DecisionError)
    async def _decision_error_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    # Health & Meta
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "decision-backend", "version": "1.0.0"}

    @app.get("/stats")
    def get_stats():
        reqs = engine.store.list_requests()
        counts_by_status: dict[str, int] = {}
        counts_by_workflow: dict[str, int] = {}
        for r in reqs:
            s = r["status"]
            w = r["workflow"]
            counts_by_status[s] = counts_by_status.get(s, 0) + 1
            counts_by_workflow[w] = counts_by_workflow.get(w, 0) + 1
        return {
            "total_requests": len(reqs),
            "by_status": counts_by_status,
            "by_workflow": counts_by_workflow,
        }

    # Workflows
    @app.get("/workflows")
    def list_workflows():
        return engine.registry.summary()

    @app.get("/workflows/{workflow_name}")
    def get_workflow_details(workflow_name: str):
        try:
            wf = engine.registry.get(workflow_name)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found: {e}")

        # Serialize workflow info for the frontend
        rules_serialized = {}
        for r_id, r in wf.rules.items():
            rules_serialized[r_id] = {
                "id": r.id,
                "type": r.type,
                "field": r.field,
                "op": r.op,
                "value": r.value,
                "on_fail": r.on_fail,
                "description": r.description,
                "when": {"field": r.when.field, "op": r.when.op, "value": r.when.value} if r.when else None,
            }

        stages_serialized = []
        for s_name, s in wf.stages.items():
            stages_serialized.append({
                "name": s.name,
                "type": s.type,
                "next": s.next,
                "rules": list(s.rules),
                "dependency": s.dependency,
                "max_attempts": s.max_attempts,
                "backoff_seconds": s.backoff_seconds,
                "on_error": s.on_error,
            })

        return {
            "name": wf.name,
            "version": wf.version,
            "description": wf.description,
            "config_hash": wf.config_hash,
            "input_schema": wf.input_schema,
            "rules": rules_serialized,
            "stages": stages_serialized,
        }

    @app.post("/workflows/reload")
    def reload_workflows():
        loaded = engine.registry.reload()
        return {"status": "reloaded", "loaded": loaded}

    # Built-in Samples & Examples
    @app.get("/examples")
    def get_examples():
        return {
            "application_approval": [
                {
                    "id": "approved_salaried",
                    "label": "1. Salaried Approved (Age 30, Score 720)",
                    "data": {
                        "applicant_id": "APP-1001",
                        "full_name": "Asha Rao",
                        "age": 30,
                        "income": 60000,
                        "pan": "ABCDE1234F",
                        "loan_amount": 20000,
                        "employment": "salaried",
                    },
                },
                {
                    "id": "manual_review_score",
                    "label": "2. Manual Review Needed (Score 600)",
                    "data": {
                        "applicant_id": "APP-2002",
                        "full_name": "Karan Verma",
                        "age": 28,
                        "income": 45000,
                        "pan": "BCDEF2345G",
                        "loan_amount": 15000,
                        "employment": "salaried",
                    },
                },
                {
                    "id": "rejected_underage",
                    "label": "3. Immediate Rejection (Underage, 17)",
                    "data": {
                        "applicant_id": "APP-4004",
                        "full_name": "Pooja Roy",
                        "age": 17,
                        "income": 30000,
                        "pan": "DEFGH4567J",
                        "loan_amount": 5000,
                        "employment": "salaried",
                    },
                },
                {
                    "id": "self_employed_no_docs",
                    "label": "4. Self-Employed Without Docs (Manual Review)",
                    "data": {
                        "applicant_id": "APP-5005",
                        "full_name": "Deepak Patel",
                        "age": 35,
                        "income": 120000,
                        "pan": "EFGHI5678K",
                        "loan_amount": 40000,
                        "employment": "self_employed",
                        "documents_uploaded": False,
                    },
                },
                {
                    "id": "invalid_payload",
                    "label": "5. Schema Validation Failure",
                    "data": {
                        "applicant_id": "APP-3003",
                        "age": "thirty",
                        "income": 50000,
                        "pan": "CDEFG3456H",
                        "loan_amount": 10000,
                        "employment": "freelance",
                        "extra": "unsupported",
                    },
                },
            ],
            "vendor_approval": [
                {
                    "id": "vendor_approved",
                    "label": "1. Compliant Enterprise Vendor",
                    "data": {
                        "vendor_id": "V-501",
                        "company_name": "TechGlobal Solutions Pvt Ltd",
                        "gst_number": "29ABCDE1234F1Z5",
                        "annual_turnover": 2500000,
                        "country": "IN",
                    },
                },
                {
                    "id": "vendor_sanctioned_country",
                    "label": "2. Sanctioned Country (Immediate Reject)",
                    "data": {
                        "vendor_id": "V-502",
                        "company_name": "Eurasia Import Export",
                        "gst_number": "29ABCDE9999F1Z0",
                        "annual_turnover": 4500000,
                        "country": "KP",
                    },
                },
                {
                    "id": "vendor_missing_gst",
                    "label": "3. Missing GST (Manual Review Required)",
                    "data": {
                        "vendor_id": "V-503",
                        "company_name": "Sunrise Handicrafts",
                        "annual_turnover": 1500000,
                        "country": "US",
                    },
                },
                {
                    "id": "vendor_low_turnover",
                    "label": "4. Below Minimum Turnover (Manual Review)",
                    "data": {
                        "vendor_id": "V-504",
                        "company_name": "Micro Small Scale Services",
                        "gst_number": "29XYZ1234F1Z9",
                        "annual_turnover": 400000,
                        "country": "IN",
                    },
                },
            ],
        }

    # Requests
    @app.post("/requests")
    def submit_request(
        body: SubmitBody,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        result = engine.submit(body.workflow, body.data, idempotency_key)
        request = result["request"]
        if request["status"] == "INVALID":
            return JSONResponse(
                status_code=422,
                content={"request": request, "errors": request["errors"]},
            )
        status_code = 200 if result["duplicate"] else 201
        return JSONResponse(
            status_code=status_code,
            content={"request": request, "duplicate": result["duplicate"]},
        )

    @app.get("/requests")
    def list_requests(workflow: str | None = Query(default=None), limit: int = 50):
        reqs = engine.store.list_requests()
        # newest first
        reqs = list(reversed(reqs))
        if workflow:
            reqs = [r for r in reqs if r["workflow"] == workflow]
        return reqs[:limit]

    @app.get("/requests/{request_id}")
    def get_request(request_id: str):
        return engine.get(request_id)

    @app.get("/requests/{request_id}/decision")
    def get_decision(request_id: str):
        return engine.decision(request_id)

    @app.get("/requests/{request_id}/audit")
    def get_audit(request_id: str):
        return engine.audit(request_id)

    @app.post("/requests/{request_id}/retry")
    def retry_request(request_id: str):
        return engine.retry(request_id)

    @app.post("/requests/{request_id}/review")
    def review_request(request_id: str, body: ReviewBody):
        return engine.review(request_id, body.decision, body.reviewer, body.note)

    # Mount frontend static files if available (enables single-service full-stack deployment)
    frontend_dir = ROOT / "frontend"
    if frontend_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = build_backend_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Starting Decision Platform Backend on http://{host}:{port}...")
    uvicorn.run(app, host=host, port=port)

