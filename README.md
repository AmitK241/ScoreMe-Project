# Configurable Workflow Decision Platform

A small, runnable decision engine. It takes a request, validates it against a schema, checks business rules,
calls an external service (simulated), makes a decision (approve / reject / manual review / retry),
and records everything in an audit trail.

Two workflows ship with it: **application approval** and **vendor approval**. The second one was added
by writing a YAML file, with no Python changes. That is the configurability requirement in practice.

Architecture, trade-offs and scaling notes are in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Quick start (about 2 minutes)

You need Python 3.10 or newer.

```bash
# from the project folder
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest -q                          # 35 tests, should all pass
python run_demo.py                 # runs 7 scenarios, writes examples/decision_examples.md
```

Open `examples/decision_examples.md` to see each decision explained: input, rules that fired, output, audit trail.

## 2. Run the REST API

```bash
uvicorn decision.api:create_app --factory --app-dir src --reload
```

Then open **http://127.0.0.1:8000/docs** for interactive Swagger UI. You can submit requests from the browser.

Or with curl:

```bash
# Submit an application (returns 201)
curl -s -X POST localhost:8000/requests \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-1' \
  -d '{"workflow":"application_approval","data":{"applicant_id":"APP-1001","full_name":"Asha Rao","age":30,"income":60000,"pan":"ABCDE1234F","loan_amount":20000,"employment":"salaried"}}'

# Send the same request again with the same key (returns 200, duplicate=true, no second bureau call)
curl -s -X POST localhost:8000/requests -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-1' \
  -d '{"workflow":"application_approval","data":{"applicant_id":"APP-1001","full_name":"Asha Rao","age":30,"income":60000,"pan":"ABCDE1234F","loan_amount":20000,"employment":"salaried"}}'

curl -s localhost:8000/requests/<request_id>/decision   # the decision with its rule trace
curl -s localhost:8000/requests/<request_id>/audit      # full audit trail
curl -s -X POST localhost:8000/requests/<request_id>/retry           # resume a RETRY_PENDING request
curl -s -X POST localhost:8000/requests/<request_id>/review \
  -H 'Content-Type: application/json' -d '{"decision":"approve","reviewer":"Ravi","note":"verified"}'
curl -s -X POST localhost:8000/workflows/reload          # reload YAML after editing config
```

To simulate a bureau outage, start the server with `SIMULATE_CREDIT_BUREAU_FAILURES=2`. The first two bureau calls fail.

### API endpoints

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| GET | `/health` | liveness | 200 | |
| GET | `/workflows` | list loaded workflows and their rules | 200 | |
| POST | `/workflows/reload` | reload YAML files without restarting | 200 | 400 if a file is broken (old config stays active) |
| POST | `/requests` | submit (optional `Idempotency-Key` header) | 201 new, 200 duplicate | 404 unknown workflow, 409 key reused with different data, 422 invalid input |
| GET | `/requests/{id}` | current state | 200 | 404 |
| GET | `/requests/{id}/decision` | decision, reasons, rule trace, facts | 200 | 404 (no decision yet) |
| GET | `/requests/{id}/audit` | state history and every audit event | 200 | 404 |
| POST | `/requests/{id}/retry` | resume a RETRY_PENDING request | 200 | 409 wrong state |
| POST | `/requests/{id}/review` | human approve / reject for MANUAL_REVIEW | 200 | 409 wrong state, 422 bad decision |

## 3. Use the command line

```bash
python run_cli.py submit --workflow application_approval --file examples/inputs/approved.json
python run_cli.py submit --workflow application_approval --file examples/inputs/manual_review.json
python run_cli.py decision <request_id>
python run_cli.py review <request_id> --decision approve --reviewer "Ravi" --note "verified"
python run_cli.py audit <request_id>
python run_cli.py workflows
python run_cli.py --fail-bureau 2 submit --workflow application_approval --file examples/inputs/approved.json
```

By default the CLI uses `data/decisions.db`. Use `--db some.db` to keep runs separate.

## 4. Example inputs

| File | What it shows | Expected result |
|---|---|---|
| `examples/inputs/approved.json` | everything valid, score 720 | APPROVED |
| `examples/inputs/invalid.json` | missing fields, wrong type, bad enum, unknown field | INVALID (422 over HTTP) |
| `examples/inputs/rejected_underage.json` | age 17 | REJECTED, bureau never called |
| `examples/inputs/manual_review.json` | applicant `APP-2002`, bureau returns 600 | MANUAL_REVIEW |
| `examples/inputs/self_employed_no_docs.json` | conditional rule fires, documents missing | MANUAL_REVIEW |

## 5. How to change the behaviour (no code)

Everything decision-related lives in `config/*.yaml`.

**Change a threshold.** In `config/application_approval.yaml`, change `value: 650` under `credit_score_minimum` to `750`. Then `POST /workflows/reload`, or restart. New requests use the new rule. Old decisions keep the config hash they were made under, so they can still be explained.

**Add a rule.** Add an entry under `rules:` with `type`, `field`, `op`, `value`, `on_fail`, and an optional `when:` condition. Then reference it by name in a stage's `rules:` list.

**Add a stage.** Add an entry under `stages:`. A stage is either `type: rules` (evaluate rules) or `type: external` (call a dependency with retries). Set `next:` to the next stage name, or `APPROVE` to finish.

**Add a workflow.** Copy a YAML file, change the `workflow:` name and the schema and rules, and drop it in `config/`. `vendor_approval.yaml` was built this way.

Supported rule operators: `exists`, `eq`, `neq`, `gte`, `gt`, `lte`, `lt`, `in`, `not_in`. Rule types: `mandatory` (must exist) and `threshold` (compare a field). `on_fail` is `reject` or `manual_review`. A rule with `when:` is skipped unless its condition holds.

Invalid YAML fails at startup with a clear message. A broken reload leaves the previous config active.

## 6. Project layout

```
config/                      workflow definitions (YAML): schema, rules, stages
  application_approval.yaml
  vendor_approval.yaml
src/decision/
  config.py                  load and validate YAML, registry with reload
  validation.py              input schema checks
  rules.py                   rule evaluation and the trace
  state.py                   request lifecycle and allowed transitions
  dependencies.py            simulated credit bureau with scripted failures
  store.py                   SQLite; each change is one transaction
  engine.py                  orchestration: idempotency, stages, retries, review
  factory.py                 wires everything together
  api.py                     REST API (FastAPI)
  cli.py                     command-line interface
tests/                       35 tests (engine, rules/config, API)
examples/inputs/             sample requests
examples/decision_examples.md  generated explanations (run run_demo.py to refresh)
run_demo.py                  scripted scenarios
run_cli.py                   CLI entry point
ARCHITECTURE.md              design document
```

## 7. Requirements checklist

| Requirement | Where it is met |
|---|---|
| Input intake and schema validation | `validation.py`, schema in YAML; errors returned as 422 |
| Mandatory, threshold, conditional, multi-step rules | `rules.py` (`mandatory`, `threshold`, `when:`), stages in `engine.py` |
| Success, reject, retry, manual review | `state.py` outcomes; `engine._run` |
| Lifecycle tracking and full change history | `state_history` table, `GET /requests/{id}/audit` |
| Explainable decisions with rule trace | `decisions` table: reasons, per-rule trace, facts, config hash |
| Dependency failure, retries, backoff | `engine._call_dependency`; `max_attempts`, `backoff_seconds` in YAML |
| Partial save failures | one transaction per change in `store.commit_transition`; test `test_partial_save_*` |
| Duplicate requests and idempotency | `Idempotency-Key` header or payload hash; `test_*duplicate*`, `test_same_key_*` |
| Configurability without code rewrites | YAML files; `vendor_approval.yaml`; test `test_rule_change_*` |
| Requirement changes tolerated | config hash per request, `config_changed` audit event, reload endpoint |
| Simulated external dependency | `dependencies.py`, failure injection via env var or CLI flag |
| Scaling considerations | see ARCHITECTURE.md section 9 |

## 8. Known limits (stated honestly)

- SQLite and a single process. Two processes running the same request at once are not protected. Production would use Postgres with row locks, or a queue.
- Manual review and retry happen on request. There is no background worker. A stalled request can be resumed with `/retry`.
- The credit bureau is simulated. Its responses are fixed for a few applicant IDs and 720 for everyone else.
- Authentication and authorization are out of scope.
