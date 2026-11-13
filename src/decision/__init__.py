"""Configurable workflow decision platform.

Modules:
  config        load and validate workflow YAML
  validation    input schema checks
  rules         rule evaluation with trace
  state         request lifecycle
  dependencies  external services (simulated here)
  store         SQLite persistence and audit log
  engine        orchestration: idempotency, stages, retries, review
  factory       wires everything together
  api           REST API (FastAPI)
  cli           command-line interface
"""
