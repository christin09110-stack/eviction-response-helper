from app.preferences import STYLES, preferred_style, record_feedback
from substrate.config import load_config
from substrate.fakes import FakeFirestore
from substrate.store import Store


def _store() -> Store:
    return Store(load_config(prefix="navigator"), client=FakeFirestore())


def test_styles_are_the_three_supported_modes():
    assert STYLES == ("plain", "analogy", "stepwise")


def test_default_style_for_an_unknown_user():
    assert preferred_style(_store(), "new-user") == "plain"


def test_a_style_that_landed_becomes_preferred():
    store = _store()
    record_feedback(store, "u1", "analogy", landed=True)
    assert preferred_style(store, "u1") == "analogy"


def test_a_style_that_did_not_land_loses_to_one_that_did():
    store = _store()
    record_feedback(store, "u1", "plain", landed=False)
    record_feedback(store, "u1", "stepwise", landed=True)
    assert preferred_style(store, "u1") == "stepwise"


def test_preference_accumulates_across_sessions():
    store = _store()
    record_feedback(store, "u1", "analogy", landed=True)
    record_feedback(store, "u1", "analogy", landed=True)
    record_feedback(store, "u1", "stepwise", landed=True)
    assert preferred_style(store, "u1") == "analogy"


def test_preferences_are_per_user():
    store = _store()
    record_feedback(store, "u1", "analogy", landed=True)
    record_feedback(store, "u2", "stepwise", landed=True)
    assert preferred_style(store, "u1") == "analogy"
    assert preferred_style(store, "u2") == "stepwise"


def test_unknown_style_is_rejected():
    store = _store()
    try:
        record_feedback(store, "u1", "interpretive-dance", landed=True)
    except ValueError as exc:
        assert "unknown style" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown style")
