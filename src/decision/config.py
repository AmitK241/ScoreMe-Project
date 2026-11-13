"""Loads workflow definitions from YAML and validates them once, so the engine can trust them.

Adding a workflow = adding a YAML file to the config folder. Nothing in Python changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, UnknownWorkflow

APPROVE = "APPROVE"                     # terminal target: all stages passed
RULE_TYPES = {"mandatory", "threshold"}
OPERATORS = {"exists", "eq", "neq", "gte", "gt", "lte", "lt", "in", "not_in"}
ON_FAIL = {"reject", "manual_review"}
STAGE_TYPES = {"rules", "external"}
ON_ERROR = {"retry", "manual_review"}
FIELD_TYPES = {"string", "integer", "number", "boolean"}


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: Any = None


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    field: str
    op: str
    value: Any = None
    on_fail: str = "reject"
    when: Condition | None = None
    description: str = ""


@dataclass(frozen=True)
class Stage:
    name: str
    type: str
    next: str
    rules: tuple = ()
    dependency: str | None = None
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    on_error: str = "retry"


@dataclass(frozen=True)
class Workflow:
    name: str
    version: int
    description: str
    input_schema: dict
    rules: dict
    stages: dict
    config_hash: str

    @property
    def first_stage(self) -> str:
        return next(iter(self.stages))


def _check_operator(op, value, where):
    if op not in OPERATORS:
        raise ConfigError(f"{where}: unknown operator '{op}'")
    if op in ("in", "not_in") and not isinstance(value, list):
        raise ConfigError(f"{where}: operator '{op}' needs a list value")


def parse_workflow(data, source="<workflow>"):
    def fail(message):
        raise ConfigError(f"{source}: {message}")

    if not isinstance(data, dict) or not data.get("workflow"):
        fail("missing 'workflow' name")

    schema = data.get("input_schema") or {}
    for field_name, spec in schema.items():
        if spec.get("type") not in FIELD_TYPES:
            fail(f"input field '{field_name}' needs a type of {sorted(FIELD_TYPES)}")

    rules = {}
    for rule_id, raw in (data.get("rules") or {}).items():
        where = f"rule '{rule_id}'"
        rule_type = raw.get("type")
        if rule_type not in RULE_TYPES:
            fail(f"{where}: type must be one of {sorted(RULE_TYPES)}")
        if not raw.get("field"):
            fail(f"{where}: needs a 'field'")
        op = raw.get("op")
        if rule_type == "mandatory" and op != "exists":
            fail(f"{where}: mandatory rules must use op 'exists'")
        _check_operator(op, raw.get("value"), where)
        on_fail = raw.get("on_fail", "reject")
        if on_fail not in ON_FAIL:
            fail(f"{where}: on_fail must be one of {sorted(ON_FAIL)}")
        when = None
        if raw.get("when"):
            cond = raw["when"]
            _check_operator(cond.get("op"), cond.get("value"), f"{where} (when)")
            when = Condition(cond["field"], cond["op"], cond.get("value"))
        rules[rule_id] = Rule(
            id=rule_id,
            type=rule_type,
            field=raw["field"],
            op=op,
            value=raw.get("value"),
            on_fail=on_fail,
            when=when,
            description=raw.get("description", ""),
        )

    stages = {}
    for raw in data.get("stages") or []:
        stage_name = raw.get("name")
        if not stage_name:
            fail("every stage needs a 'name'")
        where = f"stage '{stage_name}'"
        if stage_name in stages:
            fail(f"{where}: duplicate stage name")
        stage_type = raw.get("type")
        if stage_type not in STAGE_TYPES:
            fail(f"{where}: type must be one of {sorted(STAGE_TYPES)}")
        next_stage = raw.get("next")
        if not next_stage:
            fail(f"{where}: needs 'next' (a stage name, or APPROVE)")
        on_error = raw.get("on_error", "retry")
        if on_error not in ON_ERROR:
            fail(f"{where}: on_error must be one of {sorted(ON_ERROR)}")
        stage_rules = tuple(raw.get("rules") or ())
        if stage_type == "rules":
            if not stage_rules:
                fail(f"{where}: a rules stage needs at least one rule")
            unknown = [r for r in stage_rules if r not in rules]
            if unknown:
                fail(f"{where}: unknown rule(s) {unknown}")
        dependency = raw.get("dependency")
        if stage_type == "external" and not dependency:
            fail(f"{where}: an external stage needs a 'dependency'")
        stages[stage_name] = Stage(
            name=stage_name,
            type=stage_type,
            next=next_stage,
            rules=stage_rules,
            dependency=dependency,
            max_attempts=int(raw.get("max_attempts", 1)),
            backoff_seconds=float(raw.get("backoff_seconds", 0)),
            on_error=on_error,
        )

    if not stages:
        fail("workflow has no stages")
    for stage in stages.values():
        if stage.next != APPROVE and stage.next not in stages:
            fail(f"stage '{stage.name}' points to unknown next stage '{stage.next}'")

    config_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return Workflow(
        name=data["workflow"],
        version=int(data.get("version", 1)),
        description=data.get("description", ""),
        input_schema=schema,
        rules=rules,
        stages=stages,
        config_hash=config_hash,
    )


def load_workflows(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise ConfigError(f"config directory not found: {directory}")
    workflows = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path.name}: invalid YAML ({exc})") from exc
        workflow = parse_workflow(data, source=path.name)
        if workflow.name in workflows:
            raise ConfigError(f"{path.name}: duplicate workflow name '{workflow.name}'")
        workflows[workflow.name] = workflow
    if not workflows:
        raise ConfigError(f"no workflow .yaml files in {directory}")
    return workflows


class WorkflowRegistry:
    def __init__(self, directory):
        self.directory = Path(directory)
        self._workflows = load_workflows(self.directory)

    def reload(self):
        # Load everything first, then swap. A broken file leaves the previous config active.
        self._workflows = load_workflows(self.directory)
        return sorted(self._workflows)

    def get(self, name):
        try:
            return self._workflows[name]
        except KeyError:
            raise UnknownWorkflow(f"unknown workflow '{name}'") from None

    def summary(self):
        return [
            {
                "name": w.name,
                "version": w.version,
                "config_hash": w.config_hash,
                "description": w.description,
                "stages": list(w.stages),
                "rules": sorted(w.rules),
            }
            for w in self._workflows.values()
        ]
