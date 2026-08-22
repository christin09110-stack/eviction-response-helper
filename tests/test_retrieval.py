from app.retrieval import Passage, load_corpus, retrieve


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
