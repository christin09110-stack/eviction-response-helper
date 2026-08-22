import pytest

import app.retrieval as retrieval
from app.retrieval import Passage, load_corpus, retrieve


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FailingResponse:
    def raise_for_status(self):
        raise RuntimeError("simulated 500 from Vertex")

    def json(self):  # pragma: no cover - never reached, raise_for_status fires first
        return {}


class _FakeSession:
    """Scripted stand-in for the AuthorizedSession retrieve() would otherwise
    build from real ADC. Returns the exact raw Vertex :predict response
    shape -- {"predictions": [{"embeddings": {"values": [...]}}, ...]} --
    keyed by the instance content sent in, so a test only has to say what
    vector a given text should embed to.
    """

    def __init__(self, vectors_by_text: dict[str, list[float]]):
        self._vectors_by_text = vectors_by_text
        self.calls: list[dict] = []

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        predictions = [
            {"embeddings": {"values": self._vectors_by_text[instance["content"]]}}
            for instance in json["instances"]
        ]
        return _FakeResponse({"predictions": predictions})


class _RaisingSession:
    def post(self, url, json, timeout):
        raise ConnectionError("simulated network failure")


@pytest.fixture(autouse=True)
def _clear_passage_embedding_cache():
    """Passage embeddings are cached process-wide by design (see
    app.retrieval._PASSAGE_EMBEDDING_CACHE), so a vector one test scripts for
    a given Passage must not leak into the next test's assertions.
    """
    retrieval._PASSAGE_EMBEDDING_CACHE.clear()
    yield
    retrieval._PASSAGE_EMBEDDING_CACHE.clear()


def test_loads_every_corpus_document_with_its_citation():
    passages = load_corpus()
    assert len(passages) >= 3
    assert all(isinstance(p, Passage) and p.citation for p in passages)


def test_parses_citation_out_of_front_matter():
    passages = load_corpus()
    citations = {p.citation for p in passages}
    assert "Cal. Code Civ. Proc. § 1167" in citations


def test_front_matter_is_stripped_from_the_body():
    passages = load_corpus()
    assert all("citation:" not in p.text for p in passages)


def test_retrieves_the_deadline_passage_for_a_deadline_question():
    top = retrieve("how many days do I have to respond to the summons", load_corpus())
    assert top[0].citation == "Cal. Code Civ. Proc. § 1167"


def test_retrieves_the_defenses_passage_for_a_defense_question():
    top = retrieve("what defenses can I raise in my answer", load_corpus())
    assert top[0].citation == "Cal. Code Civ. Proc. § 1170"


def test_returns_empty_when_nothing_matches():
    assert retrieve("how do I register a trademark", load_corpus()) == []


def test_respects_the_limit():
    assert len(retrieve("response answer service days", load_corpus(), limit=2)) <= 2


# --- Guard-threshold reproduction -------------------------------------------
#
# These are the literal Vertex text-embedding-005 cosine similarities
# measured against this corpus before this build started (see
# ARCHITECTURE.md "Retrieval" and the batch report). There is no ADC in this
# sandbox, so this cannot re-call Vertex; what it can and does verify is that
# the guard arithmetic (SIMILARITY_FLOOR, AMBIGUITY_MARGIN) makes the correct
# accept/refuse decision on every one of the four measured rows, including
# the near-tie that a naive top-1 embedding ranker would get wrong.

_DEADLINE = Passage(citation="deadline", topic="", text="")
_DEFENSES = Passage(citation="defenses", topic="", text="")


@pytest.mark.parametrize(
    "label, deadline_score, defenses_score, expected_top",
    [
        ("how many days do I have to respond", 0.6259, 0.5376, "deadline"),
        ("what defenses can I raise", 0.3924, 0.5318, "defenses"),
        ("my landlord never fixed the heating", 0.4539, 0.5824, "defenses"),
        ("how long before they kick me out", 0.4571, 0.4573, None),
    ],
)
def test_guards_reproduce_the_measured_four_query_table(
    label, deadline_score, defenses_score, expected_top
):
    scored = [(deadline_score, _DEADLINE), (defenses_score, _DEFENSES)]
    result = retrieval._apply_guards(scored)
    if expected_top is None:
        assert result == [], f"{label!r} should be refused as ambiguous, got {result}"
    else:
        assert result[0][1].citation == expected_top, label


def test_ambiguity_margin_is_wide_enough_to_catch_the_near_tie_but_not_a_real_gap():
    # The near-tie itself (0.0002 apart) must be caught...
    assert retrieval._apply_guards([(0.4573, _DEFENSES), (0.4571, _DEADLINE)]) == []
    # ...but the smallest genuine gap in the measured table (0.0883, the
    # deadline query) must NOT be caught.
    assert retrieval._apply_guards([(0.6259, _DEADLINE), (0.5376, _DEFENSES)]) != []


def test_similarity_floor_refuses_a_score_below_it_even_with_no_second_candidate():
    assert retrieval._apply_guards([(0.33, _DEADLINE)]) == []


def test_similarity_floor_admits_the_lowest_measured_on_topic_top_score():
    # 0.4573 is the lowest top score across the four measured queries and
    # must clear the floor on its own (the kick-out row is refused by the
    # margin guard, not the floor).
    assert retrieval._apply_guards([(0.4573, _DEFENSES)]) != []


# --- Embedding-backed retrieve() --------------------------------------------
#
# app.retrieval._authorized_session() is the seam retrieve() uses to reach
# Vertex; monkeypatching it is the only way to drive the embedding path from
# outside the module, matching how retrieve()'s own signature stays fixed.

_DEADLINE_PASSAGE = Passage(citation="deadline-cite", topic="deadline topic", text="deadline text")
_DEFENSES_PASSAGE = Passage(citation="defenses-cite", topic="defenses topic", text="defenses text")
_CORPUS = [_DEADLINE_PASSAGE, _DEFENSES_PASSAGE]

# Orthogonal 3D passage embeddings, and queries placed to exercise each guard
# on purpose -- these are not attempts to reproduce the measured decimals
# (that is what test_guards_reproduce_the_measured_four_query_table does);
# they only need to be clearly on one side of a threshold or the other.
_DEADLINE_VECTOR = [1.0, 0.0, 0.0]
_DEFENSES_VECTOR = [0.0, 1.0, 0.0]
_CLEAR_DEADLINE_QUERY_VECTOR = [0.95, 0.10, 0.0]
_AMBIGUOUS_QUERY_VECTOR = [0.5, 0.5, 0.5]
_OFF_TOPIC_QUERY_VECTOR = [0.0, 0.0, 1.0]


def _vectors_for(query: str, query_vector: list[float]) -> dict[str, list[float]]:
    return {
        "deadline topic deadline text": _DEADLINE_VECTOR,
        "defenses topic defenses text": _DEFENSES_VECTOR,
        query: query_vector,
    }


def test_retrieve_uses_embeddings_when_the_session_is_available(monkeypatch):
    query = "a clear deadline question"
    session = _FakeSession(_vectors_for(query, _CLEAR_DEADLINE_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    result = retrieve(query, _CORPUS)

    assert result[0].citation == "deadline-cite"


def test_retrieve_refuses_an_ambiguous_embedding_match_instead_of_guessing(monkeypatch):
    query = "an ambiguous question"
    session = _FakeSession(_vectors_for(query, _AMBIGUOUS_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    assert retrieve(query, _CORPUS) == []


def test_retrieve_refuses_a_below_floor_embedding_match_instead_of_guessing(monkeypatch):
    query = "a totally unrelated question"
    session = _FakeSession(_vectors_for(query, _OFF_TOPIC_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    assert retrieve(query, _CORPUS) == []


def test_retrieve_falls_back_to_keyword_scoring_when_the_session_raises(monkeypatch):
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: _RaisingSession())

    top = retrieve("how many days do I have to respond to the summons", load_corpus())

    assert top[0].citation == "Cal. Code Civ. Proc. § 1167"


def test_retrieve_falls_back_to_keyword_scoring_on_a_failing_response(monkeypatch):
    class _FailingSession:
        def post(self, url, json, timeout):
            return _FailingResponse()

    monkeypatch.setattr(retrieval, "_authorized_session", lambda: _FailingSession())

    top = retrieve("what defenses can I raise in my answer", load_corpus())

    assert top[0].citation == "Cal. Code Civ. Proc. § 1170"


def test_retrieve_caches_passage_embeddings_across_calls(monkeypatch):
    query_a = "first clear deadline question"
    query_b = "second clear deadline question"
    session = _FakeSession(
        {
            "deadline topic deadline text": _DEADLINE_VECTOR,
            "defenses topic defenses text": _DEFENSES_VECTOR,
            query_a: _CLEAR_DEADLINE_QUERY_VECTOR,
            query_b: _CLEAR_DEADLINE_QUERY_VECTOR,
        }
    )
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    retrieve(query_a, _CORPUS)
    retrieve(query_b, _CORPUS)

    # One batch call embedded both passages; each retrieve() call embeds
    # only its own query -- three calls total, not four.
    passage_batch_calls = [
        c for c in session.calls if len(c["json"]["instances"]) == len(_CORPUS)
    ]
    assert len(passage_batch_calls) == 1
    assert len(session.calls) == 3


def test_predict_embeddings_parses_the_real_vertex_predict_response_shape():
    """Pinned to the literal shape google-genai's own Vertex embed-content
    parser reads (predictions[].embeddings.values), not a shape recalled
    from memory -- see app.retrieval._predict_embeddings.
    """
    session = _FakeSession({"hello": [0.1, 0.2, 0.3]})
    config = retrieval.load_config(prefix="navigator")

    result = retrieval._predict_embeddings(["hello"], config, session=session)

    assert result == [[0.1, 0.2, 0.3]]
    sent = session.calls[0]["json"]
    assert sent == {"instances": [{"content": "hello"}]}
