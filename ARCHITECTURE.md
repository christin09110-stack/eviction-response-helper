# Architecture

## Diagram

```mermaid
flowchart TD
    subgraph Client["Mobile console (web/)"]
        UI["index.html / app.js<br/>photo upload, question box,<br/>voice in/out, feedback buttons"]
    end

    subgraph API["app.main (FastAPI, Cloud Run)"]
        CaseEP["POST /api/case"]
        AskEP["POST /api/ask"]
        FeedbackEP["POST /api/feedback"]
    end

    subgraph Session["app.session — orchestrator"]
        StartCase["start_case()"]
        Ask["ask()"]
    end

    Intake["app.intake<br/>extract_summons / needs_retake"]
    Deadlines["app.deadlines<br/>compute_response_deadline"]
    Safety["app.safety<br/>check_halt / build_referral"]
    Retrieval["app.retrieval<br/>load_corpus / retrieve"]
    Answering["app.answering<br/>answer_question<br/>(citation invariant)"]
    Preferences["app.preferences<br/>preferred_style / record_feedback"]
    Forms["app.forms<br/>assess_defenses / draft_ud105<br/>(tested, not yet wired to the API)"]

    Gemini["substrate.gemini.GeminiModel<br/>Vertex AI gemini-3.5-flash"]
    Store["substrate.store.Store<br/>Firestore: cases, audit, preferences"]
    Corpus["corpus/*.md, ud-105-fields.json"]
    Telemetry["substrate.telemetry<br/>OpenTelemetry -> Cloud Trace / Cloud Logging"]

    UI -->|"photo"| CaseEP --> StartCase
    UI -->|"question"| AskEP --> Ask
    UI -->|"landed?"| FeedbackEP --> Preferences

    StartCase --> Intake --> Gemini
    StartCase --> Deadlines
    StartCase --> Safety
    StartCase -->|"audit + case"| Store

    Ask --> Preferences
    Ask --> Retrieval --> Corpus
    Ask --> Answering --> Gemini
    Ask -->|"audit"| Store

    Forms -.->|"reads, not yet called by API"| Corpus

    Session -.-> Telemetry
```

## Components

**`web/`** — A framework-free, mobile-first HTML/CSS/JS console. It uploads a
summons photo, sends questions, plays answers back with the Web Speech API
(falling back to the always-visible typed text when speech isn't available
or supported), and reports whether an explanation landed. It carries no
business logic — every decision it displays came back from the API as
already-computed text or data.

**`app.main`** — The FastAPI application. Wires three endpoints
(`POST /api/case`, `POST /api/ask`, `POST /api/feedback`) and the static
console (`GET /`) onto `substrate.web.create_app`'s base app (which also
supplies `/healthz` and `/events`, unused by this project's own request
path). Builds one `Store` and constructs a `GeminiModel` per request rather
than at import time. Telemetry setup is gated on `USE_FAKE_STORE` so the
module can be imported in a test process with no GCP credentials at all.

**`app.session`** — The orchestrator. `start_case` runs a summons photo
through extraction, retake-or-not, deadline computation, and halt-or-not, in
that order, writing each step to the per-user audit trail as it goes.
`ask` looks up the user's preferred explanation style *before* generating
(so the preference actually reaches the model, not just the reply label),
retrieves relevant passages, and returns a grounded-or-refused answer. Both
functions guard every point where a model's reply — even one that looks
well-formed — could be missing a field or carrying a value the rest of the
pipeline doesn't recognize; see [Halt-and-route conditions](#halt-and-route-conditions)
and the retake path below.

**`app.intake`** — Turns a photograph into `SummonsFields` via one vision
call. Never guesses: an unparseable reply, a non-numeric confidence, or an
unrecognized service-method string all degrade to `None` / zero-confidence
fields rather than raising or fabricating a value. `needs_retake` decides
whether what came back is usable enough to proceed.

**`app.deadlines`** — Pure date arithmetic implementing Cal. Code Civ. Proc.
§ 1167: five *court* days (weekends and holidays excluded) from the day
service was legally complete, which service method shifts (personal:
immediate; substituted: +10 days; mail: +5 days). Deliberately has no
dependency on the model, the store, or the network — it is a pure function
of `(served_on, method, holidays) -> date`, and is covered by a battery of
tests across every branch and edge (mutation-checked, per the batch
constraints this build operated under).

**`app.safety`** — `check_halt` evaluates a fixed, ordered set of
conditions against the case and today's date; `build_referral` assembles
everything already known about the case into an intake packet, so a tenant
who is routed to a human doesn't have to repeat themselves under time
pressure. See [Halt-and-route conditions](#halt-and-route-conditions).

**`app.retrieval`** — Loads the curated corpus (`corpus/*.md`, front matter
parsed for `citation` and `topic`) and scores passages against a question by
stopword-filtered token overlap. Deliberately simple and inspectable: there
is no embedding index to audit, and the exact set of citations a question
*can* surface is the exact set of `.md` files in `corpus/`.

**`app.answering`** — Where the citation invariant lives (below). Takes a
question and the retrieved passages, asks the model to answer using *only*
that material, and accepts the reply only if every citation in it is an
exact, verbatim match against a citation already present in the retrieved
passages. The user's preferred explanation style (plain / analogy /
stepwise) is folded into the same prompt via `STYLE_GUIDANCE`.

**`app.preferences`** — A per-user, per-style running score in Firestore.
`record_feedback` increments or decrements a style's score; `preferred_style`
returns whichever style has the highest positive score, defaulting to
`"plain"` for a new user or a style that has never had a net-positive
outcome. This is read by `app.session.ask` before every generation call, not
just reported afterward.

**`app.forms`** — A deterministic, rules-based affirmative-defense assessor
(`assess_defenses`) and a PDF renderer (`draft_ud105`) for Judicial Council
form UD-105. Defense selection is intentionally **not** model-generated: a
hallucinated affirmative defense in a filed Answer is the worst failure this
product could have, so it is a pure function of user-reported facts,
independently testable and auditable. Fully implemented and tested; not yet
called from `app.main` (see the README's Known Limitations).

**`substrate/`** — Vendored, shared infrastructure (not modified in this
project): `Store` (a Firestore wrapper with PII redaction and a
transactional audit-trail append), `GeminiModel` (the Vertex adapter, with
image MIME sniffing and empty-response guards), `telemetry` (OpenTelemetry
setup plus structured JSON logging), `web.create_app` (a Pub/Sub-push-safe
FastAPI factory), and `fakes` (in-memory stand-ins used by every test in
this project — no test in the suite touches a network or a real credential).

## The citation invariant

`app.answering.answer_question(model, question, passages, style)`:

1. Refuses immediately if no passages were retrieved for the question — an
   unanswerable question is never sent to the model to answer from nothing.
2. Sends the model *only* the retrieved passage text and citations, never
   the full corpus, and instructs it to answer using only that material.
3. Parses the reply defensively: unparseable JSON, JSON that parses to
   something other than an object, a missing or non-list `citations` field,
   a non-string item inside it, or a non-string `text` field are all treated
   identically — the answer is discarded and replaced with a fixed refusal.
4. Checks `set(citations) <= {p.citation for p in passages}` — **exact set
   membership, not fuzzy matching.** A citation that is a strict prefix of a
   real one, or wrapped in extra punctuation, is rejected exactly like a
   fabricated one. One fabricated or unverifiable citation among several
   real ones discards the whole answer, not just the bad citation.
5. Only if every check passes does the grounded answer (with its citations)
   reach the user; otherwise a fixed, non-model-generated refusal text is
   returned, which offers to prepare a legal-aid intake.

This is exercised by an intentionally adversarial test file
(`tests/test_answering.py`, 16 tests) covering fabricated citations,
prefix-only matches, a citations value that is a bare string (which Python
would otherwise happily iterate character-by-character), non-string items
mixed into an otherwise-valid list, and syntactically-valid JSON that isn't
an object at all (a bare number, string, array, or `null`).

## Halt-and-route conditions

`app.safety.check_halt(case, today)` evaluates, in this fixed priority
order (a missed deadline always outranks everything else):

| Condition | Reason | Referral urgency |
|---|---|---|
| The computed deadline has already passed | `past_deadline` | `critical` |
| The tenant wants to counter-sue | `countersuit` | `high` |
| A habitability injury is reported | `injury` | `high` |
| The matter involves a criminal allegation | `criminal` | `high` |

Any one of these stops the automated flow entirely. `build_referral` then
assembles an intake packet from everything already known about the case
(case number, court, plaintiff, deadline, and any facts gathered) so a human
advocate can pick it up without the tenant re-explaining their situation
under time pressure. `app.session.start_case` also treats two *intake*
failure modes — an unusably low-confidence photo read, and a well-formed
reply naming a service method the system doesn't recognize — as a **retake**
request rather than a halt: those are asking the tenant to try again, not
routing them to a person.
