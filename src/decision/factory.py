"""Builds a fully wired engine. The API, the CLI, the demo and the tests all use this one function."""

import time

from .config import WorkflowRegistry
from .dependencies import DEFAULT_SCORES, CreditBureauSimulator
from .engine import Engine
from .store import Store


def build_engine(db_path, config_dir, fail_bureau=0, sleep=None):
    store = Store(db_path)
    registry = WorkflowRegistry(config_dir)
    dependencies = {
        "credit_bureau": CreditBureauSimulator(fail_next=fail_bureau, scores=DEFAULT_SCORES),
    }
    return Engine(store, registry, dependencies, sleep=sleep or time.sleep)
