"""REST API. A thin layer: read HTTP, call the engine, map errors to status codes.

Run it with:  uvicorn decision.api:create_app --factory --app-dir src --reload
Interactive docs appear at http://127.0.0.1:8000/docs
"""

import os
from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .errors import DecisionError
from .factory import build_engine

ROOT = Path(__file__).resolve().parents[2]


class SubmitBody(BaseModel):
    workflow: str
    data: dict = Field(default_factory=dict)


class ReviewBody(BaseModel):
    decision: str            # "approve" or "reject"
    reviewer: str
    note: str = ""


def create_app(db_path=None, config_dir=None, fail_bureau=None):
    db_path = db_path or os.environ.get("DECISION_DB", ROOT / "data" / "decisions.db")
    config_dir = config_dir or os.environ.get("DECISION_CONFIG_DIR", ROOT / "config")
    if fail_bureau is None:
        fail_bureau = int(os.environ.get("SIMULATE_CREDIT_BUREAU_FAILURES", "0"))

    engine = build_engine(db_path, config_dir, fail_bureau=fail_bureau)
    app = FastAPI(title="Configurable Workflow Decision Platform", version="1.0.0")
    app.state.engine = engine

    @app.exception_handler(DecisionError)
    async def _decision_error(request, exc):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": type(exc).__name__, "detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/workflows")
    def list_workflows():
        return engine.registry.summary()

    @app.post("/workflows/reload")
    def reload_workflows():
        return {"loaded": engine.registry.reload()}

    @app.post("/requests")
    def submit(body: SubmitBody, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        result = engine.submit(body.workflow, body.data, idempotency_key)
        request = result["request"]
        if request["status"] == "INVALID":
            return JSONResponse(status_code=422, content={"request": request, "errors": request["errors"]})
        code = 200 if result["duplicate"] else 201
        return JSONResponse(status_code=code, content={"request": request, "duplicate": result["duplicate"]})

    @app.get("/requests/{request_id}")
    def get_request(request_id: str):
        return engine.get(request_id)

    @app.get("/requests/{request_id}/audit")
    def get_audit(request_id: str):
        return engine.audit(request_id)

    @app.get("/requests/{request_id}/decision")
    def get_decision(request_id: str):
        return engine.decision(request_id)

    @app.post("/requests/{request_id}/retry")
    def retry_request(request_id: str):
        return engine.retry(request_id)

    @app.post("/requests/{request_id}/review")
    def review_request(request_id: str, body: ReviewBody):
        return engine.review(request_id, body.decision, body.reviewer, body.note)

    return app
