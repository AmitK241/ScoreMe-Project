# Decision Platform - Backend API

FastAPI-powered decision engine backend providing REST API endpoints for workflow execution, business rule evaluation, idempotency, human manual review, and comprehensive audit trails.

## Running the Backend

### If you are inside the `backend/` folder:
```bash
# Recommended launcher:
python start_backend.py

# Or directly:
python main.py

# Or via uvicorn:
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### If you are in the project root (`hackathon-decision-system/`):
```bash
# Recommended launcher:
python start_backend.py

# Or via uvicorn:
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive API documentation (Swagger UI) is available at:
**http://127.0.0.1:8000/docs**

---

## Available Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health status |
| `GET` | `/stats` | System-wide statistics and request metrics |
| `GET` | `/workflows` | List all loaded workflows and summary |
| `GET` | `/workflows/{name}` | Workflow details (rules, stages, input schema) |
| `POST` | `/workflows/reload` | Hot-reload YAML configuration without restarting |
| `GET` | `/examples` | Pre-built test payloads for each workflow |
| `POST` | `/requests` | Submit evaluation request (supports `Idempotency-Key` header) |
| `GET` | `/requests` | List past requests (filter by `workflow`, newest first) |
| `GET` | `/requests/{id}` | Inspect request state and metadata |
| `GET` | `/requests/{id}/decision` | Inspect decision output, rule trace, and computed facts |
| `GET` | `/requests/{id}/audit` | Complete event audit log and state history |
| `POST` | `/requests/{id}/retry` | Resume a request in `RETRY_PENDING` state |
| `POST` | `/requests/{id}/review` | Human reviewer decision (`approve` or `reject` with note) |
