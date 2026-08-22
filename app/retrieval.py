import re
from dataclasses import dataclass
from pathlib import Path

STOPWORDS = frozenset(
    {"how", "many", "days", "do", "i", "have", "to", "the", "a", "an", "my", "what",
     "can", "in", "is", "are", "of", "for", "and", "or", "on", "it", "me", "you"}
)


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


def retrieve(query: str, passages: list[Passage], limit: int = 3) -> list[Passage]:
    query_tokens = _tokens(query)
    scored = []
    for passage in passages:
        overlap = len(query_tokens & _tokens(f"{passage.topic} {passage.text}"))
        if overlap:
            scored.append((overlap, passage))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [passage for _, passage in scored[:limit]]
