# Architecture: Configurable Workflow Decision Platform

## 1. Problem framing

Business workflows (loan approval, claim processing, vendor onboarding) share the same skeleton:
validate input, check rules, call outside systems, decide, and keep a record. What differs is the rules,
the stages, and the thresholds. Those change often, and they are the thing business owners want to edit.

The platform separates the **engine** (the same for every workflow) from the **definitions** (YAML, owned by
the business). The engine is built to be correct about state, retries, idempotency, and audit. The definitions
decide what "correct" means for a particular workflow.

Out of scope: authentication, a UI, distributed execution, and real third-party integrations.

## 2. Components and boundaries

```
             HTTP / CLI
                 |
          +------v------+
          |  api / cli  |   parse input, format output, map errors to status codes
          +------+------+
                 |
          +------v------+        +-------------------+
          |   engine    |------->|  config registry  |  YAML -> validated Workflow objects
          | (orchestr.) |        +-------------------+
          +--+--+--+--+--+
             |  |  |  |
   +---------+  |  |  +-----------+
   v            v  v              v
 rules.py   validation.py   state.py     dependencies.py
 (pure)     (pure)          (pure)       (simulated bureau; any client with check())
             \___________________ |
                                  v
                              store.py  (SQLite; one transaction per change)
```

| Module | Responsibility | Depends on |
|---|---|---|
| `config` | Load, validate, and version workflow YAML. Fail early on bad config. | nothing in the engine |
| `validation` | Check input against the schema in config | nothing |
| `rules` | Evaluate rules and produce a trace. No I/O. | `config` (types only) |
| `state` | Lifecycle states and allowed transitions | nothing |
| `dependencies` | External calls. Failures are raised as `DependencyError`. | nothing |
| `store` | Persistence and the audit log. Owns transactions. | `state` (transition check) |
| `engine` | Orchestrates stages, retries, idempotency, and review. Has no SQL and no HTTP. | all of the above |
| `api`, `cli` | Interfaces. No business logic. | `engine`, via `factory` |

The rule that keeps coupling low: the engine talks to the store through named methods, and the rules and
validation modules are pure functions. You can test rules without a database or HTTP, and you can swap
SQLite for Postgres inside `store.py` without touching the engine.

## 3. Data flow for one request

```
submit(workflow, data, key)
  1. look up workflow (404 if unknown)
  2. payload hash; key = header or hash         -> if key exists: return original (duplicate) or 409 if payload differs
  3. validate input against config schema        -> invalid: store as INVALID, stop
  4. store RECEIVED + history + audit (1 txn)
  5. run:
     for each stage:
       rules stage:    evaluate -> trace; reject -> REJECTED; manual -> MANUAL_REVIEW; pass -> next
       external stage: check saved result? reuse : call with retries
                       success: save result (own txn) -> facts updated -> next
                       exhausted: RETRY_PENDING (or MANUAL_REVIEW if configured)
     all stages pass: APPROVED
     each state change + audit rows + decision: one txn
```

Two more paths:

- **retry**: from RETRY_PENDING, resume at the saved `current_stage`. Any dependency result already saved is reused.
- **review**: a human moves MANUAL_REVIEW to APPROVED or REJECTED. The decision record gets the reviewer's name and note.

## 4. Lifecycle

```
            +-----------+       +------------+
 (create) ->| RECEIVED  |------>| PROCESSING |<---------+
            +-----------+       +--+--+--+---+          |
                                   |  |  |              |
        +--------------------------+  |  +-----------+  |
        v                             v              v  |
  +-----------+               +--------------+  +---------------+
  | APPROVED  |<--+           | MANUAL_REVIEW|  | RETRY_PENDING |--(retry)--+
  +-----------+   |           +------+-------+  +---------------+
  +-----------+   |                  | review            ^
  | REJECTED  |<--+------------------+                   | dependency
  +-----------+                                          | exhausted
  +-----------+                                          |
  | INVALID   |  (created directly from bad input)       
  +-----------+
```

`state.py` lists the allowed moves. `store.commit_transition` refuses any other move, so a bug cannot silently
produce an impossible state.

## 5. Idempotency

- Each request has an idempotency key: the client's `Idempotency-Key` header, or a SHA-256 hash of workflow + payload.
- The key column is UNIQUE. Two concurrent submits with the same key cannot both insert. The loser catches `IntegrityError` and returns the winner.
- Same key, same payload: return the original request and mark `duplicate=true`. The dependency is not called again.
- Same key, different payload: 409 Conflict. A client mistake, not silently overwritten.
- Retries are idempotent at the dependency level too. A successful dependency response is saved before the next step, so a crash later never repeats the call.

**Trade-off:** with no key supplied, two genuinely separate identical applications are treated as one. This is the safer default for a hackathon-scale system. Production would require clients to send keys.

## 6. Failure handling

| Failure | What happens |
|---|---|
| Invalid input | Stored as INVALID with errors. Never processed. 422 over HTTP. |
| Business rule fails with `reject` | REJECTED with reasons. No dependency call if it happens before the external stage. |
| Rule fails with `manual_review` | MANUAL_REVIEW. A person decides. |
| Dependency call fails | Retried up to `max_attempts` with linear backoff. Each attempt is audited. |
| Dependency still failing after retries | RETRY_PENDING. `POST /retry` resumes later. Or MANUAL_REVIEW, if `on_error: manual_review`. |
| Save fails partway through a decision | The whole state change rolls back. The request stays at its last committed stage. Retry resumes there. The bureau is not called again because its result was already saved. |
| Process crashes mid-run | The request sits in PROCESSING with its last committed stage. `POST /retry` also accepts a stalled PROCESSING request. |
| Duplicate submit | Returns the original. No second processing. |
| Config file broken on reload | Reload fails. The previous config stays active. |

## 7. Auditability

Three kinds of record, each answering a different question:

| Table | Question it answers | Written |
|---|---|---|
| `state_history` | How did status change, and when? | on every status change |
| `audit_events` | What happened at each step, including every dependency attempt and rule result? | on every step |
| `decisions` | Why was this decided? Reasons, full rule trace, facts used, config hash. | once per decision |

Every rule trace entry has the rule name, its status (passed, failed, skipped), the actual value, the expected
value, and a readable message. A reviewer can check any decision without reading code.

Audit events are append-only, and nothing in the code updates or deletes them.

## 8. Configurability and requirement change

Each workflow is a YAML file with four parts: the input schema, the rules, the stages, and the stage order.

- **Changing a threshold or rule** takes an edit and a reload. No code is touched.
- **Adding a workflow** takes a new file. `vendor_approval.yaml` shows this: it uses the same engine and no new code.
- **Tolerating change in flight.** Each request records the config hash it was started with. If the config changes
  before a request resumes, the engine writes a `config_changed` audit event and continues with the new config.
  The decision records which config produced it.
- **Validation at load.** Unknown rules, unknown next-stages, bad operators, and missing dependency names are
  rejected at startup, not discovered mid-request.

**Trade-off:** the expression language is deliberately small (compare one field, with an optional condition).
That keeps it safe to store in config and easy to read, but it cannot express arbitrary logic. Anything more
complex belongs in a new rule type, written as code.

**Trade-off:** the rule evaluation runs on facts that already exist. Derived values, such as `loan_ratio`, are
computed in `rules.derive_facts`. That is code, not config. It is kept short and documented.

## 9. Scaling considerations

The current design is correct for one process. Here is how to grow it:

| Concern | Now | Next step |
|---|---|---|
| Storage | SQLite file | Postgres. `store.py` is the only file that changes. Use `SELECT ... FOR UPDATE` in `commit_transition`. |
| Concurrency | One process; SQLite lock | Row locks per request, so requests run in parallel but each one only in one worker. |
| Throughput | Synchronous request processing | Run stages in a queue worker (for example, a job per request). The HTTP call returns `RECEIVED` and the client polls. |
| Slow dependencies | Blocking call with backoff | Circuit breaker per dependency, and a bounded timeout. |
| Audit volume | Rows in the same database | Move audit to an append-only store or a log pipeline. Keep `decisions` in the main database. |
| Rule evaluation cost | Pure Python, microseconds | Not the bottleneck. Cache parsed workflows (already done in the registry). |
| Config rollout | Reload endpoint | Versioned config with a staged rollout, so new requests use v2 while old ones finish on v1. |
| Duplicate protection across instances | UNIQUE key in SQLite | Same UNIQUE constraint in Postgres. Works unchanged. |

## 10. Testing strategy

| Area | Tests |
|---|---|
| Happy path | `test_happy_path_is_approved_with_rule_trace` |
| Invalid input | `test_invalid_input_*` (engine and API) |
| Business rejection before dependency | `test_underage_applicant_*` |
| Manual review and human decision | `test_manual_review_then_reviewer_approves`, API review tests |
| Duplicate requests | `test_same_idempotency_key_*`, `test_identical_payload_*`, `test_same_key_with_different_payload_*` |
| Dependency failure and retry | `test_dependency_failure_*`, `test_request_stays_retryable_*` |
| Partial save failure | `test_partial_save_failure_*`, `test_failure_right_after_bureau_call_*` |
| Rule change | `test_rule_change_alters_decision_without_code_change` |
| Conditional branching | `test_conditional_rule_*`, `test_self_employed_*` |
| Config validation | `test_*_is_rejected`, `test_reload_keeps_previous_config_*` |
| Rule logic | `test_rules_and_config.py` |

## 11. Assumptions

- A request is identified by its payload when no key is given.
- Input comes as JSON objects with a flat set of fields.
- Each stage either evaluates rules or calls one dependency.
- A decision is final unless a human reviews it (manual review) or it is retried (dependency failure).
- The database is trusted. There is no encryption at rest and no access control. A real deployment would add both.
- PAN, income, and similar fields are sample data only.

## 12. What I would do with more time

- A background worker, so retries happen on a schedule instead of only on request.
- A rules test harness: run a YAML rule file against a CSV of sample applicants and show the change in decisions before a rollout.
- Per-dependency timeouts and a circuit breaker.
- Postgres, plus a migration tool.
