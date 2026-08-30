import json

from app.answering import STYLE_GUIDANCE, Answer, answer_question
from app.retrieval import Passage
from substrate.fakes import FakeModel

PASSAGES = [
    Passage(
        citation="Cal. Code Civ. Proc. § 1167",
        topic="time to respond",
        text="A defendant must file a written response within 10 days, excluding weekends and judicial holidays, after service.",
    )
]


def _reply(text: str, citations: list[str]) -> str:
    return json.dumps({"text": text, "citations": citations})


def test_returns_a_grounded_answer_with_its_citation():
    model = FakeModel([_reply("You have 10 court days to respond.", ["Cal. Code Civ. Proc. § 1167"])])
    answer = answer_question(model, "how long do I have?", PASSAGES)
    assert isinstance(answer, Answer)
    assert answer.grounded is True
    assert answer.citations == ["Cal. Code Civ. Proc. § 1167"]


def test_prompt_contains_the_retrieved_passage_text():
    model = FakeModel([_reply("Five days.", ["Cal. Code Civ. Proc. § 1167"])])
    answer_question(model, "how long?", PASSAGES)
    assert "within 10 days" in model.calls[0]["prompt"]


def test_answer_is_ungrounded_when_no_passages_were_retrieved():
    model = FakeModel([_reply("You have thirty days.", ["Cal. Code Civ. Proc. § 9999"])])
    answer = answer_question(model, "unrelated question", [])
    assert answer.grounded is False
    assert answer.citations == []
    assert "could not find" in answer.text.lower()


def test_INVARIANT_citation_not_present_in_corpus_is_rejected(monkeypatch):
    """CORE INVARIANT — do not weaken. A fabricated citation must never survive."""
    model = FakeModel([_reply("You have thirty days.", ["Cal. Code Civ. Proc. § 9999"])])
    answer = answer_question(model, "how long?", PASSAGES)
    assert answer.grounded is False
    assert "Cal. Code Civ. Proc. § 9999" not in answer.citations
    assert "You have thirty days." not in answer.text


def test_INVARIANT_answer_with_no_citation_is_rejected():
    """CORE INVARIANT — do not weaken. An uncited legal statement must not ship."""
    model = FakeModel([_reply("You should just move out.", [])])
    answer = answer_question(model, "what should I do?", PASSAGES)
    assert answer.grounded is False
    assert "You should just move out." not in answer.text


def test_malformed_model_reply_is_ungrounded_not_a_crash():
    answer = answer_question(FakeModel(["ten days probably"]), "how long?", PASSAGES)
    assert answer.grounded is False


def test_valid_json_that_is_not_an_object_is_ungrounded_not_a_crash():
    """The model can return syntactically valid JSON with no fields to read —
    a bare array, string, or number. This must not crash on payload.get(...)."""
    for reply in ['["not", "an", "object"]', '"just a string"', "42", "null"]:
        answer = answer_question(FakeModel([reply]), "how long?", PASSAGES)
        assert answer.grounded is False
        assert "could not find" in answer.text.lower()


def test_citations_as_a_bare_string_is_rejected_not_silently_exploded_into_chars():
    """If citations comes back as a string instead of a list, it must not be
    treated as an iterable of characters (str is iterable in Python) — that
    would let a validly-shaped citation slip through as a set of single
    characters, or silently misreport what was cited."""
    reply = json.dumps({"text": "Five days.", "citations": "Cal. Code Civ. Proc. § 1167"})
    answer = answer_question(FakeModel([reply]), "how long?", PASSAGES)
    assert answer.grounded is False
    assert answer.citations == []


def test_citation_matching_corpus_only_by_prefix_is_rejected():
    """A citation that is a strict prefix of a real corpus citation refers to
    a document this navigator cannot verify verbatim, so it must be treated
    exactly like a fabricated citation."""
    reply = _reply("You have 10 court days.", ["Cal. Code Civ. Proc. § 116"])
    answer = answer_question(FakeModel([reply]), "how long?", PASSAGES)
    assert answer.grounded is False
    assert answer.citations == []


def test_non_string_items_in_citations_list_are_rejected():
    reply = json.dumps({"text": "Five days.", "citations": [123]})
    answer = answer_question(FakeModel([reply]), "how long?", PASSAGES)
    assert answer.grounded is False


def test_one_fabricated_citation_among_real_ones_rejects_the_whole_answer():
    """A citations list mixing a real citation with a fabricated one must be
    rejected in full -- every citation must be verifiable, not just some."""
    reply = _reply(
        "You have 10 court days.",
        ["Cal. Code Civ. Proc. § 1167", "Cal. Code Civ. Proc. § 9999"],
    )
    answer = answer_question(FakeModel([reply]), "how long?", PASSAGES)
    assert answer.grounded is False
    assert answer.citations == []


# --- Explanation-style preference must change the actual prompt sent to the
# model, not just ride along as a label. (This is what Task 7's brief calls
# "a real preference that changes real output, not a claim" -- the wiring
# has to reach the generation call, not stop at reporting the preference.) ---


def test_default_style_is_plain_and_says_so_in_the_prompt():
    model = FakeModel([_reply("Five days.", ["Cal. Code Civ. Proc. § 1167"])])
    answer_question(model, "how long?", PASSAGES)
    assert STYLE_GUIDANCE["plain"] in model.calls[0]["prompt"]


def test_analogy_style_changes_the_prompt_sent_to_the_model():
    model = FakeModel([_reply("Five days.", ["Cal. Code Civ. Proc. § 1167"])])
    answer_question(model, "how long?", PASSAGES, style="analogy")
    assert STYLE_GUIDANCE["analogy"] in model.calls[0]["prompt"]
    assert STYLE_GUIDANCE["analogy"] != STYLE_GUIDANCE["plain"]


def test_stepwise_style_changes_the_prompt_sent_to_the_model():
    model = FakeModel([_reply("Five days.", ["Cal. Code Civ. Proc. § 1167"])])
    answer_question(model, "how long?", PASSAGES, style="stepwise")
    assert STYLE_GUIDANCE["stepwise"] in model.calls[0]["prompt"]


def test_unknown_style_falls_back_to_plain_rather_than_raising():
    model = FakeModel([_reply("Five days.", ["Cal. Code Civ. Proc. § 1167"])])
    answer_question(model, "how long?", PASSAGES, style="interpretive-dance")
    assert STYLE_GUIDANCE["plain"] in model.calls[0]["prompt"]


def test_style_does_not_weaken_the_citation_invariant():
    """CORE INVARIANT — do not weaken. Style must never bypass grounding."""
    reply = json.dumps({"text": "You should just move out.", "citations": []})
    answer = answer_question(FakeModel([reply]), "what should I do?", PASSAGES, style="analogy")
    assert answer.grounded is False
    assert "You should just move out." not in answer.text
