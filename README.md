# Eviction Response Helper

A mobile-first tool that helps a tenant respond to a California eviction
(unlawful detainer) summons: it reads the summons, works out the real
response deadline, answers questions with a citation attached, and prepares
an Answer for the tenant to review and file themselves.

**Scope: California unlawful detainer only.** Nothing in this project speaks
to any other state, any other kind of eviction filing, or any other area of
law.

**It never files anything.** Every screen that produces paperwork says so.
The tool prepares a document; a human reviews it and files it, or takes it to
an advocate.

**Every legal statement carries a citation. When it can't cite one, it says
so and prepares a legal-aid intake instead of guessing.** This is enforced in
code, not just in the prompt: see [the citation invariant](#the-citation-invariant)
below.

This is a legal-information tool, not a lawyer. It does not create an
attorney-client relationship and does not tell anyone what they should do —
only what the law says.

## The problem

> "Low-income Americans do not get any or enough legal help for 92% of their
> civil legal problems that substantially affect them."
> — Legal Services Corporation, *The Justice Gap* (2022)

Legal aid organizations turn away roughly half of everyone who asks them for
help, because they don't have the staff to take the case. In California, a
tenant served with an unlawful detainer summons has **five court days** to
file a written response (Cal. Code Civ. Proc. § 1167) — miss it, and the
landlord can take a default judgment without a hearing. This tool exists for
the gap between those two facts: someone who has a hard deadline and nowhere
to turn before it arrives.

## Live deployment

Deployed on Google Cloud Run:
**https://legal-navigator-95953931159.us-central1.run.app**

## Spin-up, step by step

Tested from a clean checkout on Linux/macOS with `uv` installed
(`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone <this repo>
cd legal-navigator

# 1. Install the project AND its dev/test dependencies.
#    `uv run` alone can silently skip the editable install of this
#    package, which then fails with `ModuleNotFoundError: No module
#    named 'substrate'` even though nothing is wrong with the code —
#    always run this first.
uv pip install -e ".[dev]"

# 2. Run the test suite (no cloud credentials needed — everything is
#    exercised against substrate.fakes.FakeModel / FakeFirestore).
uv run pytest -q
# -> 132 passed

# 3. Run the app locally against fakes (no GCP project needed to browse
#    the console; /api/case and /api/ask will error without real Vertex
#    credentials, since they call the live model. /api/draft calls no
#    model and works against the fake store, but needs a case already
#    on file for that user_id -- i.e. a successful /api/case call first).
USE_FAKE_STORE=1 uv run uvicorn app.main:app --host 127.0.0.1 --port 8080
# open http://127.0.0.1:8080/

# 4. Deploy to Cloud Run (requires a GCP project with Firestore, Secret
#    Manager, and Vertex AI access already provisioned, and an
#    authenticated `gcloud`).
./deploy.sh <service-name>
```

There is no separate `docker build` step for local development — the
Dockerfile is only exercised by `gcloud run deploy --source .` inside
`deploy.sh`, which builds and deploys in one step via Cloud Build.

## What it does

1. **Photograph the summons.** A vision call (`app.intake.extract_summons`)
   reads the case number, court, plaintiff, service date, and service
   method. A low-confidence read or a missing service date asks for a
   retake rather than guessing — a wrong date here is a missed deadline.
2. **Compute the real deadline.** `app.deadlines.compute_response_deadline`
   counts five *court* days (Saturdays, Sundays, and judicial holidays
   excluded) from the date service was legally complete — which is not
   always the day someone was handed papers: substituted service completes
   ten days after mailing, service by mail alone adds five calendar days.
3. **Ask a question, get a cited answer.** `app.retrieval` ranks the small
   curated corpus of California statutory text by cosine similarity over
   Vertex `text-embedding-005`, gated by two guards chosen from a real
   measurement against this corpus: an absolute similarity floor, and an
   ambiguity margin that refuses rather than guesses when the top two
   passages score within 0.02 of each other (a real near-tie the measurement
   found was 0.0002 apart — see [Retrieval](#retrieval)). If embeddings are
   unavailable (no credentials, network failure) it falls back to the
   original stopword-filtered token-overlap scorer. `app.answering` then
   asks the model to answer *using only* the retrieved passages and rejects
   the answer outright if its citation isn't an exact, verbatim match
   against the corpus (see below).
4. **Four halt conditions route to a human, not a guess.** Past deadline, a
   countersuit, an injury, or a criminal matter each stop the automated flow
   and assemble a legal-aid intake (`app.safety.build_referral`) from
   whatever the tool already knows, so a tenant doesn't have to repeat
   themselves to an advocate under time pressure.
5. **A drafted UD-105 Answer.** Affirmative defenses (habitability,
   retaliation, defective notice, rent accepted after notice) are selected
   by a deterministic, rules-based function
   (`app.forms.assess_defenses`) — never by the model — because a
   hallucinated affirmative defense in a filed court document is the worst
   failure this product could have. `app.forms.draft_ud105` renders the
   selected defenses onto a PDF stamped "PREPARED DRAFT — NOT FILED."
   Reachable from the console's step 3 ("Prepare your Answer (UD-105)") via
   `POST /api/draft`: it looks up the tenant's case from the store, runs
   the handful of facts the tenant answers on that screen through
   `assess_defenses`, and streams the rendered PDF straight back as an
   in-memory download — nothing is written to disk, so there is nothing for
   Cloud Run's ephemeral filesystem to lose between requests. Covered by 10
   tests in `tests/test_forms.py` plus 9 in `tests/test_api.py` (missing
   case, missing name, PDF magic bytes, download headers, and defense
   selection driven by the submitted facts).
6. **A style preference that actually changes the answer.** A tenant's
   feedback ("did that make sense?") is recorded per-user
   (`app.preferences`) and the next answer is generated in whichever of
   plain / analogy / step-by-step language landed best for them — the
   preference is threaded into the actual model prompt
   (`app.answering.STYLE_GUIDANCE`), not just reported back as a label.

## Retrieval

`app.retrieval.retrieve` ranks the corpus by cosine similarity over Vertex
`text-embedding-005` (768 dims, `us-central1`, called against the `:predict`
endpoint), not word overlap. That earned a real measurement against this
corpus before the guards below were sized:

| query | deadline passage | defenses passage | correct passage | naive top-1 |
|---|---|---|---|---|
| "how many days do I have to respond" | 0.6259 | 0.5376 | deadline | correct |
| "what defenses can I raise" | 0.3924 | 0.5318 | defenses | correct |
| "my landlord never fixed the heating" | 0.4539 | 0.5824 | defenses | correct |
| "how long before they kick me out" | 0.4571 | 0.4573 | — | **wrong, by 0.0002** |

Three of four improve over the old keyword scorer — the heating question in
particular has almost no word overlap with the habitability passage and the
keyword scorer returned nothing for it, wrongly refusing a question
embeddings answer correctly. The fourth is a genuine near-tie: a naive top-1
embedding ranker would answer it confidently and *wrong*, which for a tool
telling someone facing eviction what the law says is worse than the old
scorer's refusal.

So retrieval keeps two guards on top of the ranking, both sized from the
table above, not picked in the abstract:

- **An absolute similarity floor (0.40).** Below it, `retrieve()` returns
  nothing — the same outcome as the old scorer finding zero word overlap, so
  the existing refusal-and-route-to-legal-aid path fires unchanged. Sized to
  the midpoint between the one measured off-topic score (an unrelated
  control sentence scored 0.3303 against the deadline passage) and the
  lowest measured on-topic top score (0.4573).
- **An ambiguity margin (0.02).** If the top two passages score within this
  of each other, `retrieve()` also returns nothing rather than guess. It has
  to catch the 0.0002 gap above while leaving the smallest genuine gap in the
  table (0.0883, the deadline question) untouched; 0.02 clears both with
  room to spare on either side.

**This is not a strict improvement, and the guard means ambiguous questions
are refused by design.** A tenant asking something that lands squarely
between two passages will get the same "I would rather say nothing than
guess" refusal the corpus-miss case gets, even though the corpus does, in a
sense, contain relevant material. That tradeoff is deliberate: the product's
invariant is never asserting a legal statement it cannot cite, and a
coin-flip between two real statutes is not something this tool is willing to
guess at either.

If the embedding backend is unavailable — no ADC, a network failure, a
non-2xx or malformed response — `retrieve()` falls back to the original
stopword-filtered token-overlap scorer (`_retrieve_by_keyword`) rather than
raising. That fallback is also what keeps this project's test suite running
unmocked: there is no ADC in this build's local/CI environment, so every
pre-existing test exercises the fallback for real, and the embedding path
itself is covered by tests that mock the raw Vertex `:predict` response
shape (`{"predictions": [{"embeddings": {"values": [...]}}]}`).

## The citation invariant

`app.answering.answer_question` will not return a legal statement unless
every citation attached to it is an **exact, verbatim** match against a
citation string already present in the retrieved corpus passages. Not a
prefix match, not a fuzzy match, not "close enough" — exact set membership.
If the model returns no citation, an empty citation list, a citation that
isn't a string, or a citation that doesn't match anything retrieved, the
whole answer is discarded and replaced with a fixed refusal that offers to
prepare a legal-aid intake instead. One fabricated citation invalidates the
entire answer, even if the rest of it cited correctly. This behavior is
covered by a battery of adversarial tests in `tests/test_answering.py`
(fabricated citations, prefix-only matches, citations mixed with real ones,
non-string citation items, malformed model replies, syntactically-valid
non-object JSON) and was chosen because a hallucinated citation in an
eviction case is not a cosmetic bug.

## Technologies

- **Backend:** Python 3.13, FastAPI, Pydantic
- **Model:** Google Gemini (`gemini-3.5-flash` via Vertex AI, `substrate.gemini.GeminiModel`)
- **Retrieval:** Vertex AI `text-embedding-005` (`us-central1`, `:predict`),
  cosine similarity with an absolute floor and an ambiguity margin, falling
  back to token-overlap scoring when embeddings are unavailable — see
  [Retrieval](#retrieval)
- **Storage:** Google Cloud Firestore (audit trail, case state, per-user
  explanation-style preference)
- **Observability:** OpenTelemetry, exported to Google Cloud Trace and Cloud
  Logging
- **PDF generation:** ReportLab
- **Frontend:** Plain HTML/CSS/JS (no framework, no build step) — Material
  design grammar, mobile-first, Web Speech API for voice input/output with a
  typed fallback
- **Hosting:** Google Cloud Run
- **Testing:** pytest, `substrate.fakes.FakeModel` / `FakeFirestore` (no
  network or credentials required for the test suite), axe-core (WCAG audit).
  The embedding path is covered by tests that mock the raw Vertex `:predict`
  response shape directly rather than a higher-level SDK object.

`substrate/` is a vendored, shared package (Firestore store, Gemini model
adapter, telemetry, a Pub/Sub-fronting FastAPI factory) built for and reused
across three related hackathon projects; it is treated as fixed
infrastructure here and was not modified.

## Data sources

The legal corpus (`corpus/`) is a small, hand-curated set of plain-language
summaries of California statutes directly governing unlawful detainer
response timing and defenses:

- `corpus/ccp-1167.md` — Cal. Code Civ. Proc. § 1167 (time to respond)
- `corpus/ccp-1170.md` — Cal. Code Civ. Proc. § 1170 (answer and available
  defenses)
- `corpus/service-methods.md` — Cal. Code Civ. Proc. §§ 1011, 1012, 415.20
  (how the method of service affects the deadline)
- `corpus/ud-105-fields.json` — the field layout of Judicial Council form
  UD-105 (Answer — Unlawful Detainer), used to drive the drafted PDF

Each `.md` file's front matter carries a `citation` string, and that exact
string is the only thing the citation invariant will accept as support for a
legal statement — nothing is paraphrased or normalized between the corpus
and the check.

## Findings and learnings

- **The citation invariant caught a real bug against the live model, not
  just in tests.** After the first deploy, an in-corpus question
  ("how many days do I have to respond") came back as a refusal in
  production even though retrieval found the right passage. Cloud Logging
  showed `fabricated_citation`. Reproducing the exact prompt directly
  against Vertex showed the real model (`gemini-3.5-flash`) had copied the
  citation back *with* the `[...]` bracket delimiter the prompt used to set
  passages apart — a real citation, wrapped in punctuation the invariant
  correctly refused to treat as identical. Fixed by removing the bracket
  delimiter from the prompt (a labelled `Citation: ... / Text: ...` format
  instead) rather than loosening the exact-match check, then re-verified
  against three fresh live Vertex calls before redeploying. This is the
  clearest evidence in this project that the invariant does what it's for:
  it is stricter than the model, and that strictness is a feature, not a
  bug to prompt around by weakening the check.
- **A preference that isn't wired to generation isn't a preference.** The
  per-user explanation-style memory (`app.preferences`) was originally
  wired so the session orchestrator looked up a user's preferred style and
  returned it as a label in the reply — but never passed it into the model
  call that actually generates the answer. A user could record five
  "stepwise" feedbacks and receive identical plain-language answers forever.
  Fixed by threading `style` into `answer_question`'s prompt and having
  `app.session.ask` look the preference up *before* generating, not after.
- **"Assume the model returns a well-shaped reply" was the single most
  common defect class in this build.** Across the four tasks completed in
  this batch, the recurring bug was code trusting that a JSON reply from
  the model would have the field, the type, or the enum value it expected.
  One instance: a summons photo can produce a *high-confidence*,
  *well-formed-looking* extraction where the service method names something
  the `ServiceMethod` enum doesn't recognize (dropped to `None` by
  `app.intake`) — which the existing retake check didn't catch, so the
  deadline computation would raise an uncaught `ValueError` and the whole
  request would 500 instead of asking for a retake. Fixed in
  `app.session.start_case` with an explicit guard and two regression tests.
- **A local sandbox and Cloud Run's container are not the same environment,
  and telemetry setup assumed they were.** The reference implementation of
  `app.main` called `setup_telemetry` unconditionally, which builds a
  `CloudTraceSpanExporter` that resolves Application Default Credentials at
  *construction* time (unlike `firestore.Client` and `genai.Client`, which
  resolve credentials lazily on first use). That made importing `app.main`
  — and therefore every API test — fail outright on any machine without
  real GCP credentials configured. Gated behind the same `USE_FAKE_STORE`
  environment seam already used for the Firestore client, using an
  in-memory span exporter for tests.
- **WCAG compliance was checked, not assumed.** The mobile console was
  scanned with an actual axe-core run (Playwright-driven, both the default
  and every revealed UI state — deadline shown, halt shown, answer shown —
  and both the light and dark color palettes): zero violations. Every
  interactive control measured at least 48×48px.
- **An unconditional `google.auth.default()` call would have made every test
  in the suite slow, not just uncredentialed.** With no ADC configured
  (there is none in this sandbox), the call doesn't fail fast — it falls
  through to a GCE metadata-server probe that retries against an
  unreachable server before giving up, measured at roughly 12 seconds. Every
  test that calls `app.retrieval.retrieve()` would have paid that cost.
  `app.retrieval._adc_likely_available()` checks
  `GOOGLE_APPLICATION_CREDENTIALS`, the gcloud well-known ADC file, and
  `K_SERVICE` (always set on Cloud Run) first, with no network call, so the
  full test suite still runs in well under a second, and the real ADC path
  is exercised for real, unaffected, in production.

## Known limitations

- **The corpus is small and hand-picked.** It covers response timing,
  service method effects, and the four affirmative defenses on form UD-105
  — not the full range of unlawful detainer law. Anything outside it is
  refused, by design, rather than guessed at.
- **This is California unlawful detainer only.** No other jurisdiction, no
  other eviction process, no other area of law.

## Not legal advice

This tool states what the applicable statutes say and helps prepare
documents for a person to review and file themselves. It does not create an
attorney-client relationship, does not evaluate the merits of anyone's case,
and does not tell anyone what they should do. Anyone facing an eviction
should also contact a local legal aid organization or attorney.
