import json
from dataclasses import dataclass

from app.retrieval import Passage
from substrate.telemetry import log_event, span

REFUSAL = (
    "I could not find that in the California unlawful detainer materials I have. "
    "I would rather say nothing than guess about your case. A legal aid advocate "
    "can answer this, and I can prepare your intake for them."
)

ANSWER_INSTRUCTION = """\
Answer the question using ONLY the passages below. This is a California unlawful
detainer matter.

{passages}

Question: {question}

Return ONLY a JSON object with exactly these keys:
  "text"      - a plain-language answer at roughly a sixth-grade reading level.
                {style_guidance}
  "citations" - a list of citation strings, copied exactly from the "Citation:"
                line of each passage above -- no brackets, quotes, or other
                punctuation added around them

Rules:
- Say what the law says. Never tell the person what they should do.
- Every legal statement must be supported by a passage above.
- If the passages do not answer the question, return an empty citations list.
- Do not wrap the JSON in markdown fences.
"""

# This is the substance of the "adapts to the user's unique way of thinking"
# clause (app.preferences): the style has to change what is actually sent to
# the model, not just ride along in the reply as a label nobody reads. A
# preference that is stored and reported back but never reaches the
# generation call is not a preference that changes output -- it is a claim
# that one exists. app.session.ask looks this up via
# app.preferences.preferred_style and passes it in below.
STYLE_GUIDANCE = {
    "plain": "Explain it in short, direct sentences.",
    "analogy": "Explain it using one simple, concrete everyday analogy.",
    "stepwise": "Explain it as a short numbered list of steps.",
}
DEFAULT_STYLE = "plain"


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[str]
    grounded: bool


def _ungrounded(reason: str) -> Answer:
    log_event("answer.rejected", severity="WARNING", reason=reason)
    return Answer(text=REFUSAL, citations=[], grounded=False)


def answer_question(model, question: str, passages: list[Passage], style: str = DEFAULT_STYLE) -> Answer:
    if not passages:
        return _ungrounded("no_passages")

    # An unrecognised style falls back to plain rather than raising: this is
    # a presentation preference, not a correctness input, and letting a bad
    # value here crash the whole answer would trade a display nicety for
    # availability -- the wrong end of that trade for a refusal-first system.
    guidance = STYLE_GUIDANCE.get(style, STYLE_GUIDANCE[DEFAULT_STYLE])

    # No delimiter characters (brackets, quotes) around p.citation here: a
    # real Vertex call against gemini-3.5-flash was observed copying the
    # citation back WITH a wrapping "[...]" when the prompt used
    # "[{citation}] {text}" -- a verified-correct citation then failed the
    # exact-membership check below and the answer was wrongly discarded as
    # fabricated_citation. Fixed at the prompt, not by loosening the
    # membership check itself, which is the citation invariant and must stay
    # exact-match-only.
    block = "\n\n".join(f"Citation: {p.citation}\nText: {p.text}" for p in passages)
    with span("navigator.answer"):
        reply = model.generate(
            ANSWER_INSTRUCTION.format(passages=block, question=question, style_guidance=guidance)
        )

    try:
        payload = json.loads(reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except json.JSONDecodeError:
        return _ungrounded("unparseable")

    if not isinstance(payload, dict):
        # Syntactically valid JSON that isn't an object -- a bare string, a
        # number, an array, null -- has no fields to read. payload.get(...)
        # below would raise AttributeError on any of these; treat them all
        # the same as any other malformed reply rather than crashing.
        return _ungrounded("unparseable")

    citations = payload.get("citations")
    if not isinstance(citations, list) or not citations:
        # A missing/empty citations list is the model saying "no support".
        # A citations value that isn't a list at all -- e.g. the model
        # returned the single citation as a bare string -- must not be
        # accepted either: str is iterable, so a naive `set(citations)`
        # would silently decompose it into individual characters instead
        # of the citation it names.
        return _ungrounded("no_citation")
    if not all(isinstance(c, str) for c in citations):
        return _ungrounded("no_citation")

    text = payload.get("text")
    if not isinstance(text, str):
        return _ungrounded("unparseable")

    # Exact membership only. A citation that matches a corpus document only
    # by prefix (or any other fuzzy relation) refers to text this navigator
    # cannot verify verbatim, and must be rejected exactly like a fabricated
    # citation -- never partial-credited.
    allowed = {p.citation for p in passages}
    if not set(citations) <= allowed:
        return _ungrounded("fabricated_citation")

    return Answer(text=text, citations=list(citations), grounded=True)
