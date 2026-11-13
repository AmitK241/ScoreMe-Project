"""The orchestrator. It takes a request through the configured stages and records what it does.

    submit()  validate -> deduplicate (idempotency) -> persist -> run
    _run()    walk stages; call dependencies with retries; evaluate rules; finish
    retry()   resume a request that stopped at RETRY_PENDING (or stalled mid-run)
    review()  a human completes a MANUAL_REVIEW request
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from .config import APPROVE
from .dependencies import DependencyError
from .errors import IdempotencyConflict, InvalidReview, InvalidTransition, NotFound
from .rules import derive_facts, evaluate_rules
from .state import APPROVED, INVALID, MANUAL_REVIEW, PROCESSING, RECEIVED, REJECTED, RETRY_PENDING
from .validation import validate_input


def payload_hash(workflow, data):
    raw = json.dumps({"workflow": workflow, "data": data}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class Engine:
    def __init__(self, store, registry, dependencies, sleep=time.sleep):
        self.store = store
        self.registry = registry
        self.dependencies = dependencies   # name -> client object with check(request_id, data)
        self.sleep = sleep

    # ----- public operations -----

    def submit(self, workflow_name, data, idempotency_key=None):
        workflow = self.registry.get(workflow_name)
        digest = payload_hash(workflow_name, data)
        key = idempotency_key or digest      # no key supplied: identical payloads count as duplicates

        existing = self.store.find_by_key(key)
        if existing is not None:
            return self._duplicate(existing, digest, key)

        errors = validate_input(workflow.input_schema, data)
        try:
            request_id = self.store.create_request(
                workflow=workflow.name,
                workflow_version=workflow.version,
                config_hash=workflow.config_hash,
                idempotency_key=key,
                payload_hash=digest,
                input_data=data if isinstance(data, dict) else {},
                status=INVALID if errors else RECEIVED,
                errors=errors,
            )
        except sqlite3.IntegrityError:
            # Another request with the same key was saved between our check and our insert.
            return self._duplicate(self.store.find_by_key(key), digest, key)

        if not errors:
            self._run(request_id, reason="received")
        return {"request": self.store.get(request_id), "duplicate": False}

    def get(self, request_id):
        return self._require(request_id)

    def audit(self, request_id):
        self._require(request_id)
        return self.store.audit_log(request_id)

    def decision(self, request_id):
        self._require(request_id)
        decision = self.store.get_decision(request_id)
        if decision is None:
            raise NotFound(f"request '{request_id}' has no decision yet (status {self.get(request_id)['status']})")
        return decision

    def retry(self, request_id):
        request = self._require(request_id)
        if request["status"] not in (RETRY_PENDING, PROCESSING):
            raise InvalidTransition(f"request is {request['status']}; only RETRY_PENDING can be retried")
        self.store.increment_retry(request_id)
        self._run(request_id, reason="retry requested")
        return self.store.get(request_id)

    def review(self, request_id, decision, reviewer, note=""):
        request = self._require(request_id)
        if request["status"] != MANUAL_REVIEW:
            raise InvalidTransition(f"request is {request['status']}; only MANUAL_REVIEW requests can be reviewed")
        if decision not in ("approve", "reject"):
            raise InvalidReview("decision must be 'approve' or 'reject'")

        final_status = APPROVED if decision == "approve" else REJECTED
        prior = self.store.get_decision(request_id) or {}
        note_text = f" ({note})" if note else ""
        record = {
            "decision": "APPROVE" if decision == "approve" else "REJECT",
            "reasons": list(prior.get("reasons", [])) + [f"manual review by {reviewer}: {decision}{note_text}"],
            "trace": prior.get("trace", []),
            "facts": prior.get("facts", {}),
            "workflow_version": prior.get("workflow_version", request["workflow_version"]),
            "config_hash": prior.get("config_hash", request["config_hash"]),
        }
        self.store.commit_transition(
            request_id,
            final_status,
            stage=request["current_stage"],
            context=request["context"],
            reason=f"manual review by {reviewer}",
            audit=[(request["current_stage"], "manual_review_completed",
                    {"reviewer": reviewer, "decision": decision, "note": note})],
            decision=record,
        )
        return self.store.get(request_id)

    # ----- internals -----

    def _require(self, request_id):
        request = self.store.get(request_id)
        if request is None:
            raise NotFound(f"request '{request_id}' not found")
        return request

    def _duplicate(self, existing, digest, key):
        if existing["payload_hash"] != digest:
            raise IdempotencyConflict(f"idempotency key '{key}' was already used for a different payload")
        self.store.add_audit(existing["id"], None, "duplicate_request", {"idempotency_key": key})
        return {"request": self.store.get(existing["id"]), "duplicate": True}

    @staticmethod
    def _facts(request, context):
        facts = derive_facts(request["input"])
        facts.update(context.get("dependency_facts", {}))
        return facts

    def _run(self, request_id, reason):
        request = self._require(request_id)
        workflow = self.registry.get(request["workflow"])
        context = request["context"]
        pending = []   # audit rows waiting to be saved together with the next state change

        if request["config_hash"] != workflow.config_hash:
            pending.append((request["current_stage"], "config_changed",
                            {"from": request["config_hash"], "to": workflow.config_hash}))
        stage_name = request["current_stage"]
        if stage_name not in workflow.stages:
            stage_name = workflow.first_stage

        self.store.commit_transition(
            request_id, PROCESSING, stage=stage_name, context=context, reason=reason,
            audit=pending, workflow_version=workflow.version, config_hash=workflow.config_hash,
        )
        pending = []

        while True:
            stage = workflow.stages[stage_name]

            if stage.type == "external":
                ok, error = self._call_dependency(request, stage, context)
                if not ok:
                    if stage.on_error == "manual_review":
                        self._finish(request, workflow, context, MANUAL_REVIEW, "MANUAL_REVIEW",
                                     [f"dependency '{stage.dependency}' unavailable: {error}"],
                                     stage.name, "dependency failed; routed to manual review", pending)
                        return
                    self.store.commit_transition(
                        request_id, RETRY_PENDING, stage=stage.name, context=context,
                        reason=f"dependency '{stage.dependency}' failed",
                        audit=pending + [(stage.name, "retry_scheduled", {"error": error})],
                    )
                    return
            else:
                result, trace = evaluate_rules([workflow.rules[r] for r in stage.rules],
                                               self._facts(request, context))
                context["trace"] = [t for t in context["trace"] if t["stage"] != stage.name] + [
                    {**t.to_dict(), "stage": stage.name} for t in trace
                ]
                failed = [t.message for t in trace if t.status == "failed"]
                pending.append((stage.name, "rules_evaluated", {"result": result, "failed": failed}))
                if result != "pass":
                    status = REJECTED if result == "reject" else MANUAL_REVIEW
                    decision = "REJECT" if result == "reject" else "MANUAL_REVIEW"
                    self._finish(request, workflow, context, status, decision, failed,
                                 stage.name, f"rules gave {result}", pending)
                    return

            if stage.next == APPROVE:
                self._finish(request, workflow, context, APPROVED, "APPROVE", [],
                             stage.name, "all stages passed", pending)
                return

            stage_name = stage.next
            self.store.commit_transition(request_id, PROCESSING, stage=stage_name, context=context,
                                         reason=f"stage '{stage.name}' completed", audit=pending)
            pending = []

    def _finish(self, request, workflow, context, status, decision, reasons, stage, reason, pending):
        record = {
            "decision": decision,
            "reasons": reasons,
            "trace": context["trace"],
            "facts": self._facts(request, context),
            "workflow_version": workflow.version,
            "config_hash": workflow.config_hash,
        }
        self.store.commit_transition(
            request["id"], status, stage=stage, context=context, reason=reason,
            audit=pending + [(stage, "decision", {"decision": decision, "reasons": reasons})],
            decision=record, workflow_version=workflow.version, config_hash=workflow.config_hash,
        )

    def _call_dependency(self, request, stage, context):
        """Returns (ok, error). Results are saved as soon as they arrive, so a later failure never repeats the call."""
        request_id = request["id"]

        cached = self.store.get_dependency_result(request_id, stage.dependency)
        if cached is not None:
            context["dependency_facts"].update(cached)
            self.store.add_audit(request_id, stage.name, "dependency_reused",
                                 {"dependency": stage.dependency,
                                  "note": "earlier result reused; dependency not called again"})
            return True, None

        client = self.dependencies.get(stage.dependency)
        if client is None:
            return False, f"no client registered for '{stage.dependency}'"

        error = None
        for attempt in range(1, stage.max_attempts + 1):
            self.store.add_audit(request_id, stage.name, "dependency_attempt",
                                 {"dependency": stage.dependency, "attempt": attempt})
            try:
                response = client.check(request_id, request["input"])
            except DependencyError as exc:
                error = str(exc)
                self.store.add_audit(request_id, stage.name, "dependency_failed",
                                     {"attempt": attempt, "error": error})
                if attempt < stage.max_attempts and stage.backoff_seconds:
                    self.sleep(stage.backoff_seconds * attempt)
                continue
            self.store.save_dependency_result(request_id, stage.dependency, response)
            self.store.add_audit(request_id, stage.name, "dependency_succeeded",
                                 {"attempt": attempt, "response": response})
            context["dependency_facts"].update(response)
            return True, None
        return False, error
