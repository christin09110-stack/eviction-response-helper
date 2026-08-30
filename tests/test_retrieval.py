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
# decision on every one of the four measured rows -- including the near-tie,
# which a naive top-1 ranker would answer from the wrong passage and which
# this retriever hands over whole rather than picking a side.

_DEADLINE = Passage(citation="deadline", topic="", text="")
_DEFENSES = Passage(citation="defenses", topic="", text="")
_SERVICE = Passage(citation="service", topic="", text="")


@pytest.mark.parametrize(
    "label, deadline_score, defenses_score, expected_top",
    [
        ("how many days do I have to respond", 0.6259, 0.5376, "deadline"),
        ("what defenses can I raise", 0.3924, 0.5318, "defenses"),
        ("my landlord never fixed the heating", 0.4539, 0.5824, "defenses"),
        ("how long before they kick me out", 0.4571, 0.4573, "defenses"),
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


def test_a_near_tie_returns_both_passages_rather_than_refusing():
    """A tie means the ranking cannot separate two passages -- not that
    neither is relevant. Refusing throws away both; returning both lets
    app.answering cite whichever actually answers the question, and its
    citation check still rejects anything that is not verbatim corpus text.
    """
    result = retrieval._apply_guards([(0.4573, _DEFENSES), (0.4571, _DEADLINE)])
    assert [p.citation for _, p in result] == ["defenses", "deadline"]


def test_the_margin_groups_a_near_tie_and_leaves_a_real_gap_alone():
    # 0.0002 apart: neither passage can be dropped in favour of the other.
    near_tie = [(0.4573, _DEFENSES), (0.4571, _DEADLINE)]
    assert retrieval._tie_cluster_size(near_tie) == 2
    # 0.0883 apart (the measured deadline query): a genuine winner, and the
    # margin must not pretend otherwise.
    real_gap = [(0.6259, _DEADLINE), (0.5376, _DEFENSES)]
    assert retrieval._tie_cluster_size(real_gap) == 1


def test_the_tie_group_is_every_passage_within_the_margin_not_just_the_top_two():
    """all-within-margin, not top-two: nothing distinguishes a third passage
    tied just as closely as the second, and dropping it would be the same
    arbitrary coin flip the margin exists to prevent."""
    three_way = [(0.6481, _SERVICE), (0.6462, _DEADLINE), (0.6400, _DEFENSES)]
    assert retrieval._tie_cluster_size(three_way) == 3


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


def test_retrieve_returns_both_passages_on_an_ambiguous_embedding_match(monkeypatch):
    query = "an ambiguous question"
    session = _FakeSession(_vectors_for(query, _AMBIGUOUS_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    result = retrieve(query, _CORPUS)

    assert {p.citation for p in result} == {"deadline-cite", "defenses-cite"}


def test_a_near_tie_is_never_cut_in_half_by_the_limit(monkeypatch):
    """The limit may not slice through a tie group: taking one of two
    passages the ranker could not separate is exactly the coin flip the
    margin exists to prevent. At the default limit of 3 against this
    three-document corpus this never bites -- it is what stops the coin
    flip coming back if the limit drops or the corpus grows.
    """
    query = "an ambiguous question"
    session = _FakeSession(_vectors_for(query, _AMBIGUOUS_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    result = retrieve(query, _CORPUS, limit=1)

    assert {p.citation for p in result} == {"deadline-cite", "defenses-cite"}


def test_a_clear_winner_still_respects_the_limit(monkeypatch):
    query = "a clear deadline question"
    session = _FakeSession(_vectors_for(query, _CLEAR_DEADLINE_QUERY_VECTOR))
    monkeypatch.setattr(retrieval, "_authorized_session", lambda: session)

    result = retrieve(query, _CORPUS, limit=1)

    assert [p.citation for p in result] == ["deadline-cite"]


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


# --- The plain-English regression, measured against the deployed corpus -----
#
# Vertex text-embedding-005, us-central1, all three corpus documents, measured
# 2026-08-22 against the same service the live checks in the batch report hit.
# Scores are (CCP 1167, CCP 1170, service-methods).
#
# The last three rows below are the bug this test exists for: every one of
# them is a plain-English way of asking the single question this product is
# built to answer, every one scored comfortably above the floor, and every one
# was refused outright because §1167 ("ten court days") and the
# service-methods passage ("when the clock starts") -- two passages that are
# both relevant and belong in the same answer -- landed within a hair of each
# other.

_MEASURED = [
    # query, 1167, 1170, service, citations kept when the limit is squeezed to 1
    ("five day deadline", 0.6194, 0.3901, 0.5874, {"1167"}),
    ("when is my response due", 0.6242, 0.5456, 0.6604, {"service"}),
    ("how many court days to respond to a summons", 0.7859, 0.5792, 0.6995, {"1167"}),
    ("how long do I have to respond", 0.6373, 0.5206, 0.6381, {"1167", "service"}),
    ("what is the deadline to file my answer", 0.6462, 0.6065, 0.6481, {"1167", "service"}),
    ("How many days do I have to respond?", 0.6839, 0.5398, 0.6665, {"1167", "service"}),
    # Genuinely off-topic. Note it clears the 0.40 floor by 0.007, so the
    # floor is NOT what refuses it -- app.answering is, by finding no
    # citation the passages support. See README "Retrieval".
    ("how do I register a trademark", 0.3847, 0.3314, 0.4069, {"service"}),
]

_P1167 = Passage(citation="1167", topic="", text="")
_P1170 = Passage(citation="1170", topic="", text="")
_PSERVICE = Passage(citation="service", topic="", text="")


@pytest.mark.parametrize("query, s1167, s1170, sservice, tied", _MEASURED)
def test_measured_queries_are_no_longer_refused_by_retrieval(
    query, s1167, s1170, sservice, tied
):
    ranked = retrieval._apply_guards(
        [(s1167, _P1167), (s1170, _P1170), (sservice, _PSERVICE)]
    )
    assert ranked != [], f"{query!r} was refused by retrieval"
    # Squeezing the limit to 1 exposes which passages the tie group protects.
    kept = {p.citation for p in retrieval._top_passages(ranked, limit=1)}
    assert kept == tied, query
    # At the production limit every passage reaches the model regardless.
    assert len(retrieval._top_passages(ranked, limit=3)) == 3
