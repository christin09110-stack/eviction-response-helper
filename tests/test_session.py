import json
from datetime import date

from app.session import ask, start_case
from substrate.config import load_config
from substrate.fakes import FakeFirestore, FakeModel
from substrate.store import Store

TODAY = date(2026, 8, 5)


def _store() -> Store:
    return Store(load_config(prefix="navigator"), client=FakeFirestore())


def _summons(**overrides) -> str:
    payload = {
        "case_number": "24UD001234",
        "court_branch": "Alameda",
        "plaintiff_name": "Ridgeline LLC",
        "served_on": "2026-08-03",
        "service_method": "personal",
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_start_case_computes_and_stores_the_deadline():
    store = _store()
    reply = start_case(FakeModel([_summons()]), store, "u1", b"png", TODAY)
    assert reply.kind == "case_started"
    assert reply.data["deadline"] == "2026-08-10"
    assert store.get("cases", "u1")["case_number"] == "24UD001234"


def test_start_case_asks_for_a_retake_on_a_bad_photo():
    reply = start_case(FakeModel([_summons(confidence=0.2)]), _store(), "u1", b"png", TODAY)
    assert reply.kind == "retake"
    assert "brighter light" in reply.text


def test_start_case_halts_when_the_deadline_already_passed():
    reply = start_case(
        FakeModel([_summons(served_on="2026-07-01")]), _store(), "u1", b"png", TODAY
    )
    assert reply.kind == "halt"
    assert reply.data["referral"]["urgency"] == "critical"


def test_ask_returns_a_grounded_answer():
    store = _store()
    start_case(FakeModel([_summons()]), store, "u1", b"png", TODAY)
    model = FakeModel([json.dumps({
        "text": "You have five days to file a response.",
        "citations": ["Cal. Code Civ. Proc. § 1167"],
    })])
    reply = ask(model, store, "u1", "how long do I have to respond")
    assert reply.kind == "answer"
    assert reply.data["citations"] == ["Cal. Code Civ. Proc. § 1167"]


def test_ask_refuses_rather_than_guessing_when_ungrounded():
    store = _store()
    start_case(FakeModel([_summons()]), store, "u1", b"png", TODAY)
    model = FakeModel([json.dumps({"text": "Just move out.", "citations": []})])
    reply = ask(model, store, "u1", "what should I do")
    assert reply.kind == "answer"
    assert reply.data["grounded"] is False
    assert "Just move out." not in reply.text


def test_every_turn_is_written_to_the_audit_trail():
    store = _store()
    start_case(FakeModel([_summons()]), store, "u1", b"png", TODAY)
    steps = [entry["step"] for entry in store.audit_trail("u1")]
    assert "extract" in steps and "deadline" in steps


# --- Guarding against a model that returns well-formed-looking but
# unusable fields (Ruling 2: extract_summons / answer_question failure
# shapes must not crash the orchestrator). ---


def test_start_case_asks_for_a_retake_when_service_method_is_unrecognised():
    """service_method can come back as an unrecognised string with a HIGH
    confidence and a valid served_on date -- app.intake._parse_method drops
    it to None rather than guessing, and needs_retake does not check this
    field. Without a guard here, compute_response_deadline(served_on, None)
    raises ValueError("unknown service method: None") and start_case crashes
    instead of returning a Reply."""
    reply = start_case(
        FakeModel([_summons(service_method="carrier pigeon")]), _store(), "u1", b"png", TODAY
    )
    assert reply.kind == "retake"


def test_start_case_asks_for_a_retake_on_a_completely_unparseable_reply():
    """extract_summons degrades a malformed model reply to an all-None,
    zero-confidence SummonsFields rather than raising. start_case must turn
    that into a retake, not crash on a None deadline computation."""
    reply = start_case(FakeModel(["not json at all"]), _store(), "u1", b"png", TODAY)
    assert reply.kind == "retake"
