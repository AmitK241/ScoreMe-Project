import json
from pathlib import Path

import pytest

from decision.factory import build_engine

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
INPUTS = ROOT / "examples" / "inputs"


def sample(name):
    """Fresh copy of an example input, so tests never share mutable data."""
    return json.loads((INPUTS / name).read_text())


def no_sleep(_seconds):
    pass


@pytest.fixture
def engine(tmp_path):
    return build_engine(tmp_path / "test.db", CONFIG_DIR, sleep=no_sleep)


@pytest.fixture
def bureau(engine):
    return engine.dependencies["credit_bureau"]


@pytest.fixture
def approved_data():
    return sample("approved.json")


@pytest.fixture
def underage_data():
    return sample("rejected_underage.json")


@pytest.fixture
def manual_data():
    return sample("manual_review.json")


@pytest.fixture
def invalid_data():
    return sample("invalid.json")


@pytest.fixture
def self_employed_data():
    return sample("self_employed_no_docs.json")
