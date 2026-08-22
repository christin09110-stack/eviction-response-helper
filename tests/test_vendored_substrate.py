"""Smoke test for the vendored substrate package.

Both sibling projects' equivalents of this test caught real problems (a
missing build-system block, an editable install that silently did not pick
up the substrate package under `uv run`). This is cheap insurance against the
same class of failure here.
"""
import importlib

import pytest

from substrate.config import load_config
from substrate.fakes import FakeFirestore
from substrate.store import Store

_MODULES = [
    "substrate.config",
    "substrate.guards",
    "substrate.fakes",
    "substrate.store",
    "substrate.telemetry",
    "substrate.events",
    "substrate.gemini",
    "substrate.web",
]


@pytest.mark.parametrize("module_name", _MODULES)
def test_every_substrate_module_imports(module_name):
    importlib.import_module(module_name)


def test_load_config_sets_navigator_prefix_and_the_two_distinct_locations():
    config = load_config(prefix="navigator")
    assert config.firestore_prefix == "navigator"
    assert config.vertex_location == "global"
    assert config.location == "us-central1"


def test_store_round_trips_against_fake_firestore():
    config = load_config(prefix="navigator")
    store = Store(config, client=FakeFirestore())
    store.put("cases", "case-1", {"case_number": "24UD001234"})
    assert store.get("cases", "case-1") == {"case_number": "24UD001234"}
