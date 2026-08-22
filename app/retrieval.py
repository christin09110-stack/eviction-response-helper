import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from substrate.config import Config, load_config

STOPWORDS = frozenset(
    {"how", "many", "days", "do", "i", "have", "to", "the", "a", "an", "my", "what",
     "can", "in", "is", "are", "of", "for", "and", "or", "on", "it", "me", "you"}
)

# Vertex text-embedding-005, 768 dims, called against the :predict endpoint
# (not the newer embedContent surface -- text-embedding-005 is not one of the
# models the SDK routes there). Chosen over gemini-embedding-001 (3072 dims)
# because this corpus is four short documents: the bigger model is heavier to
# store and compare for no measured retrieval benefit at this scale.
EMBEDDING_MODEL = "text-embedding-005"

# Two guards on top of cosine-similarity ranking, both derived from a real
# measurement against this corpus (Vertex text-embedding-005, us-central1;
# see ARCHITECTURE.md "Retrieval" for the full table this was chosen from):
#
#   query                                       deadline   defenses  verdict
#   "how many days do I have to respond"          0.6259     0.5376   correct
#   "what defenses can I raise"                   0.3924     0.5318   correct
#   "my landlord never fixed the heating"         0.4539     0.5824   correct
#   "how long before they kick me out"            0.4571     0.4573   WRONG (0.0002 apart)
#
# SIMILARITY_FLOOR: below this, treat as no match at all. Set to 0.40, the
# midpoint of the gap between the one measured off-topic score (an unrelated
# control sentence scored 0.3303 against the deadline passage) and the lowest
# measured on-topic top score (0.4573, the kick-out query above) -- clear of
# both by roughly the same margin (~0.07), so it does not have to sit hard
# against either boundary.
SIMILARITY_FLOOR = 0.40

# AMBIGUITY_MARGIN: if the top two passages score within this of each other,
# refuse rather than guess. Must catch the 0.0002 gap in the kick-out row
# above and must NOT catch the smallest genuine gap in the table, 0.0883
# (deadline query: 0.6259 vs 0.5376). 0.02 sits two orders of magnitude above
# the near-tie and well under half of the smallest real gap, so it has room
# on both sides rather than being tuned to the exact numbers above.
AMBIGUITY_MARGIN = 0.02

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_ADC_WELL_KNOWN_FILE = os.path.expanduser(
    "~/.config/gcloud/application_default_credentials.json"
)

# Passage embeddings are cached for the process lifetime, keyed by the
# (frozen, hashable) Passage itself: the corpus is four documents that do not
# change between requests, so re-embedding them on every question would be
# pure waste. Query embeddings are not cached -- every question is different.
_PASSAGE_EMBEDDING_CACHE: dict["Passage", list[float]] = {}


@dataclass(frozen=True)
class Passage:
    citation: str
    topic: str
    text: str


def _front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    _, block, body = raw.split("---", 2)
    meta = {}
    for line in block.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta, body.strip()


def load_corpus(root: str = "corpus") -> list[Passage]:
    passages = []
    for path in sorted(Path(root).glob("*.md")):
        meta, body = _front_matter(path.read_text())
        passages.append(
            Passage(citation=meta.get("citation", ""), topic=meta.get("topic", ""), text=body)
        )
    return passages


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", text.lower()) if word not in STOPWORDS}


def _retrieve_by_keyword(query: str, passages: list[Passage], limit: int) -> list[Passage]:
    """Original word-overlap scorer. Kept as the fallback for when the
    embedding backend is unavailable (no ADC, network unreachable, a
    malformed response) -- see retrieve()."""
    query_tokens = _tokens(query)
    scored = []
    for passage in passages:
        overlap = len(query_tokens & _tokens(f"{passage.topic} {passage.text}"))
        if overlap:
            scored.append((overlap, passage))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [passage for _, passage in scored[:limit]]


def _adc_likely_available() -> bool:
    """Cheap, network-free check for whether Application Default Credentials
    are plausibly resolvable, so retrieve() can skip the real credential
    lookup entirely when they clearly are not.

    Without this, google.auth.default() falls through to a GCE metadata-
    server probe that -- measured in this sandbox -- takes about 12 seconds
    to fail (three retries against an unreachable metadata server) rather
    than failing fast, and every one of this suite's pre-existing tests
    calls retrieve() unmocked. This check trades a theoretical miss (ADC
    configured some way this function does not recognise) for keeping the
    suite fast; the real-ADC path is still exercised for real on Cloud Run,
    which always sets K_SERVICE, so production is unaffected.
    """
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    if os.path.exists(_ADC_WELL_KNOWN_FILE):
        return True
    if os.getenv("K_SERVICE"):
        return True
    return False


def _authorized_session():
    """A google-auth-authorized requests.Session for calling Vertex's
    :predict REST endpoint directly, or None if credentials cannot be
    resolved. Never raises -- every caller treats None as "embeddings
    unavailable, fall back to the keyword scorer".
    """
    if not _adc_likely_available():
        return None
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
        return AuthorizedSession(credentials)
    except Exception:  # noqa: BLE001 - any auth failure means "no embeddings"
        return None


def _predict_embeddings(
    texts: list[str], config: Config, session=None
) -> list[list[float]] | None:
    """Call Vertex's text-embedding-005 :predict endpoint for a batch of
    texts. Returns None on any failure -- no session, network error,
    non-2xx, unparseable body -- so the caller falls back to the keyword
    scorer rather than raising into retrieve().

    The real response body is `{"predictions": [{"embeddings": {"values":
    [...]}}, ...]}`, one prediction per input text in order; that is the
    shape parsed below, and the shape tests mock.
    """
    if session is None:
        session = _authorized_session()
    if session is None:
        return None
    url = (
        f"https://{config.location}-aiplatform.googleapis.com/v1/projects/"
        f"{config.project_id}/locations/{config.location}/publishers/google/"
        f"models/{EMBEDDING_MODEL}:predict"
    )
    try:
        response = session.post(
            url,
            json={"instances": [{"content": text} for text in texts]},
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        return [item["embeddings"]["values"] for item in body["predictions"]]
    except Exception:  # noqa: BLE001 - any transport/shape failure means "no embeddings"
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _passage_embeddings(
    passages: list[Passage], config: Config, session=None
) -> dict[Passage, list[float]] | None:
    """Embeddings for `passages`, filling _PASSAGE_EMBEDDING_CACHE for any
    not already cached. Returns None if any needed passage could not be
    embedded, rather than mixing cached and missing vectors.
    """
    missing = [p for p in passages if p not in _PASSAGE_EMBEDDING_CACHE]
    if missing:
        vectors = _predict_embeddings(
            [f"{p.topic} {p.text}" for p in missing], config, session=session
        )
        if vectors is None or len(vectors) != len(missing):
            return None
        for passage, vector in zip(missing, vectors):
            _PASSAGE_EMBEDDING_CACHE[passage] = vector
    return {p: _PASSAGE_EMBEDDING_CACHE[p] for p in passages}


def _apply_guards(scored: list[tuple[float, Passage]]) -> list[tuple[float, Passage]]:
    """Refuse (return []) rather than guess, per the two guards documented
    above SIMILARITY_FLOOR and AMBIGUITY_MARGIN.
    """
    if not scored:
        return []
    scored = sorted(scored, key=lambda pair: pair[0], reverse=True)
    if scored[0][0] < SIMILARITY_FLOOR:
        return []
    if len(scored) >= 2 and (scored[0][0] - scored[1][0]) < AMBIGUITY_MARGIN:
        return []
    return scored


def _embedding_rank(
    query: str, passages: list[Passage], config: Config, session=None
) -> list[tuple[float, Passage]] | None:
    """Cosine-similarity ranking of `passages` against `query`, guarded, or
    None if the embedding backend is unavailable (caller falls back).
    """
    if not passages:
        return []
    passage_vectors = _passage_embeddings(passages, config, session=session)
    if passage_vectors is None:
        return None
    query_vectors = _predict_embeddings([query], config, session=session)
    if not query_vectors:
        return None
    query_vector = query_vectors[0]
    scored = [(_cosine_similarity(query_vector, passage_vectors[p]), p) for p in passages]
    return _apply_guards(scored)


def retrieve(query: str, passages: list[Passage], limit: int = 3) -> list[Passage]:
    config = load_config(prefix="navigator")
    ranked = _embedding_rank(query, passages, config)
    if ranked is None:
        return _retrieve_by_keyword(query, passages, limit)
    return [passage for _, passage in ranked[:limit]]
