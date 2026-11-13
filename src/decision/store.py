"""SQLite persistence.

Rule: any change that touches more than one row happens inside one transaction (all or nothing).
That is how a state change, its history rows, its audit rows and the decision are saved together.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .errors import NotFound
from .state import check_transition

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    workflow TEXT NOT NULL,
    workflow_version INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    errors_json TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    stage TEXT,
    event TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    request_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    trace_json TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    workflow_version INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependency_results (
    request_id TEXT NOT NULL,
    dependency TEXT NOT NULL,
    response_json TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (request_id, dependency)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _request_from_row(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "workflow": row["workflow"],
        "workflow_version": row["workflow_version"],
        "config_hash": row["config_hash"],
        "status": row["status"],
        "current_stage": row["current_stage"],
        "idempotency_key": row["idempotency_key"],
        "payload_hash": row["payload_hash"],
        "input": json.loads(row["input_json"]),
        "context": json.loads(row["context_json"]),
        "errors": json.loads(row["errors_json"]),
        "retry_count": row["retry_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    @contextmanager
    def _txn(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _one(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _all(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ----- requests -----

    def create_request(self, *, workflow, workflow_version, config_hash, idempotency_key,
                       payload_hash, input_data, status, errors):
        request_id = "req_" + uuid.uuid4().hex[:12]
        now = _now()
        context = {"dependency_facts": {}, "trace": []}
        with self._txn() as c:
            c.execute(
                """INSERT INTO requests (id, workflow, workflow_version, config_hash, status, current_stage,
                   idempotency_key, payload_hash, input_json, context_json, errors_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, workflow, workflow_version, config_hash, status, idempotency_key,
                 payload_hash, json.dumps(input_data), json.dumps(context), json.dumps(errors), now, now),
            )
            c.execute(
                "INSERT INTO state_history (request_id, from_state, to_state, reason, at) VALUES (?, NULL, ?, ?, ?)",
                (request_id, status, "created", now),
            )
            event = "validation_failed" if errors else "received"
            self._insert_audit(c, request_id, None, event, {"errors": errors}, now)
        return request_id

    def get(self, request_id):
        return _request_from_row(self._one("SELECT * FROM requests WHERE id = ?", (request_id,)))

    def find_by_key(self, idempotency_key):
        return _request_from_row(self._one("SELECT * FROM requests WHERE idempotency_key = ?", (idempotency_key,)))

    def list_requests(self):
        return [_request_from_row(r) for r in self._all("SELECT * FROM requests ORDER BY created_at, id")]

    def commit_transition(self, request_id, to_status, *, stage=None, context=None, reason="",
                          audit=(), decision=None, workflow_version=None, config_hash=None):
        """The one place a request's status changes. Everything passed here is saved atomically."""
        now = _now()
        with self._txn() as c:
            row = c.execute("SELECT status FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise NotFound(f"request '{request_id}' not found")
            current = row["status"]
            check_transition(current, to_status)
            if current != to_status:
                c.execute(
                    "INSERT INTO state_history (request_id, from_state, to_state, reason, at) VALUES (?, ?, ?, ?, ?)",
                    (request_id, current, to_status, reason, now),
                )
            c.execute(
                """UPDATE requests SET status = ?,
                       current_stage = COALESCE(?, current_stage),
                       context_json = COALESCE(?, context_json),
                       workflow_version = COALESCE(?, workflow_version),
                       config_hash = COALESCE(?, config_hash),
                       updated_at = ?
                   WHERE id = ?""",
                (to_status, stage, json.dumps(context) if context is not None else None,
                 workflow_version, config_hash, now, request_id),
            )
            for event_stage, event, detail in audit:
                self._insert_audit(c, request_id, event_stage, event, detail, now)
            if decision is not None:
                self._insert_decision(c, request_id, decision, now)

    def increment_retry(self, request_id):
        now = _now()
        with self._txn() as c:
            c.execute("UPDATE requests SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
                      (now, request_id))
            self._insert_audit(c, request_id, None, "retry_requested", {}, now)

    # ----- audit, history and decisions -----

    def _insert_audit(self, c, request_id, stage, event, detail, now):
        c.execute(
            "INSERT INTO audit_events (request_id, stage, event, detail_json, at) VALUES (?, ?, ?, ?, ?)",
            (request_id, stage, event, json.dumps(detail, default=str), now),
        )

    def add_audit(self, request_id, stage, event, detail):
        with self._txn() as c:
            self._insert_audit(c, request_id, stage, event, detail, _now())

    def audit_log(self, request_id):
        history = self._all(
            "SELECT from_state, to_state, reason, at FROM state_history WHERE request_id = ? ORDER BY id",
            (request_id,),
        )
        events = self._all(
            "SELECT stage, event, detail_json, at FROM audit_events WHERE request_id = ? ORDER BY id",
            (request_id,),
        )
        return {
            "state_history": [dict(r) for r in history],
            "events": [{"stage": r["stage"], "event": r["event"], "detail": json.loads(r["detail_json"]),
                        "at": r["at"]} for r in events],
        }

    def _insert_decision(self, c, request_id, d, now):
        c.execute(
            """INSERT OR REPLACE INTO decisions (request_id, decision, reasons_json, trace_json, facts_json,
               workflow_version, config_hash, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, d["decision"], json.dumps(d["reasons"]), json.dumps(d["trace"], default=str),
             json.dumps(d["facts"], default=str), d["workflow_version"], d["config_hash"], now),
        )

    def get_decision(self, request_id):
        row = self._one("SELECT * FROM decisions WHERE request_id = ?", (request_id,))
        if row is None:
            return None
        return {
            "decision": row["decision"],
            "reasons": json.loads(row["reasons_json"]),
            "trace": json.loads(row["trace_json"]),
            "facts": json.loads(row["facts_json"]),
            "workflow_version": row["workflow_version"],
            "config_hash": row["config_hash"],
            "decided_at": row["decided_at"],
        }

    # ----- dependency results -----

    def save_dependency_result(self, request_id, dependency, response):
        with self._txn() as c:
            c.execute(
                "INSERT OR REPLACE INTO dependency_results (request_id, dependency, response_json, saved_at) "
                "VALUES (?, ?, ?, ?)",
                (request_id, dependency, json.dumps(response), _now()),
            )

    def get_dependency_result(self, request_id, dependency):
        row = self._one(
            "SELECT response_json FROM dependency_results WHERE request_id = ? AND dependency = ?",
            (request_id, dependency),
        )
        return json.loads(row["response_json"]) if row else None
