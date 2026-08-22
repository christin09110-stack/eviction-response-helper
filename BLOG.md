# Building an eviction-response navigator that would rather refuse than guess

*Written for the purposes of entering the All Things Agentic Hackathon
(Collaborative Partner track).*

## The problem

The Legal Services Corporation's *The Justice Gap* (2022) put a number on
something legal aid organizations already knew: low-income Americans get no
or inadequate help for **92%** of the civil legal problems that substantially
affect them. Legal aid organizations turn away roughly half of everyone who
asks them for help, because they don't have the staff to take the case.

In California, that gap collides with a hard clock. A tenant served with an
unlawful detainer summons has **five court days** to file a written
response (Cal. Code Civ. Proc. § 1167) — miss it, and the landlord can take
a default judgment with no hearing. This project exists for the space
between those two facts: someone with a hard deadline and, for roughly half
of them, nowhere to turn before it arrives.

## What it does

A tenant photographs their summons. A vision call reads the case number,
court, plaintiff, service date, and service method, and asks for a retake
rather than guessing on a low-confidence read — a wrong service date here is
a missed deadline. The tool computes the real response window: five *court*
days (weekends and judicial holidays excluded) from the date service was
legally complete, which isn't always the day someone was handed papers —
substituted service adds ten days before the clock even starts, service by
mail adds five calendar days on top.

A tenant can then ask a question and get an answer with a citation attached,
drawn from a small curated corpus of California statutory text. If the
system can't cite something, it says so and offers to assemble a legal-aid
intake instead of answering anyway. A fixed set of halt conditions — the
deadline has already passed, a countersuit, a reported habitability injury,
a criminal matter — stop the automated flow entirely and route to a human,
with the intake pre-assembled from everything the tool already knows, so a
tenant under time pressure doesn't have to repeat their case number and
deadline to an advocate from scratch.

**Scope: California unlawful detainer only. It never files anything on a
tenant's behalf** — every document it prepares is stamped for a human to
review and file themselves. This is a legal-information tool, not a lawyer;
it does not create an attorney-client relationship and does not tell anyone
what they should do, only what the law says.

## What was genuinely hard

**The citation invariant caught a real bug against the live model — not a
test, production.** After the first deploy, a plainly in-corpus question
("how many days do I have to respond") came back as a refusal even though
retrieval found the right passage. Cloud Logging showed
`fabricated_citation`. Reproducing the exact prompt directly against Vertex
showed the real model had copied the citation back *with* the `[...]`
bracket delimiter the prompt used to visually separate passages — a real,
correct citation, wrapped in punctuation the exact-match check correctly
refused to treat as identical to the clean string in the corpus. The fix was
to remove the bracket delimiter from the prompt (a labelled `Citation: .../
Text: ...` format instead), not to loosen the check. That distinction
mattered: the invariant was doing exactly its job — being stricter than the
model — and the honest fix was to stop giving the model a reason to add
punctuation, not to teach the check to tolerate punctuation it can't
verify is harmless in general. Re-verified against three fresh live Vertex
calls before redeploying.

**A preference that isn't wired into generation isn't a preference.** The
per-user explanation-style memory (plain / analogy / step-by-step) was
originally wired so the session orchestrator looked the user's preferred
style up and returned it as a label on the reply — but never actually passed
it into the model call that generates the answer. A tenant could record five
"this landed" votes for step-by-step explanations and keep getting identical
plain-language answers forever, because nothing downstream ever read the
preference before generating. Fixed by threading `style` into the prompt
itself and moving the lookup to happen *before* generation, not after.

**"Assume the model returns a well-shaped reply" was the single most common
bug in this build.** The recurring defect across every task was code
trusting that a JSON reply from the model would have the field, type, or
enum value it expected. One instance: a summons photo can produce a
*high-confidence*, well-formed-looking extraction where the service method
names something the internal enum doesn't recognize — silently dropped to
`None` by the intake step, which the existing retake check didn't catch. The
deadline computation would then raise on an unrecognized service method and
the whole request would 500 instead of asking for a retake. Fixed with an
explicit guard in the session orchestrator and two regression tests, but the
pattern recurred enough across the build that it's the clearest lesson here:
every point where a model's answer crosses into deterministic logic needs an
explicit "what if this isn't what I expect" branch, because a well-formed
JSON reply and a *correct* one are not the same guarantee.

**A local sandbox and a Cloud Run container are not the same environment.**
The reference implementation called `setup_telemetry` unconditionally on
import, which builds a `CloudTraceSpanExporter` that resolves Application
Default Credentials at *construction* time — unlike the Firestore client and
the Gemini client, which resolve credentials lazily on first use. That made
importing the app itself, and therefore every API test, fail outright on
any machine without real GCP credentials. Gated behind the same environment
seam already used to swap in the fake Firestore store for tests.

## The architecture, briefly

A FastAPI service exposes three endpoints — photo in, question in, feedback
in — onto a shared vendored base app. A session orchestrator runs each
photo through extraction, retake-or-not, deadline computation, and
halt-or-not in that fixed order, writing every step to a per-user Firestore
audit trail as it goes. Retrieval scores a question against a small
front-matter-tagged markdown corpus by token overlap — deliberately simple
and inspectable, because there's no embedding index to audit and the exact
set of citations a question *can* surface is the exact set of files in the
corpus directory. Answering sends the model only the retrieved passage text,
never the full corpus, and accepts a reply only if every citation in it is
an exact, verbatim match against a citation already present in what was
retrieved — a rules-based, deterministic affirmative-defense assessor
(never the model) decides which UD-105 defenses apply, because a
hallucinated affirmative defense in a filed court document is the worst
failure this product could have.

## What it does not do

The corpus is small and hand-picked — response timing, service-method
effects, and four affirmative defenses on form UD-105, not the full range of
unlawful detainer law. Anything outside it is refused by design rather than
guessed at. This is California unlawful detainer only — no other
jurisdiction, no other eviction process, no other area of law. And the
drafted UD-105 Answer engine, while fully implemented and tested, isn't yet
wired into the deployed web console: producing the drafted PDF today
requires calling the drafting function directly rather than clicking a
button in the browser. That's a scoping gap in the UI, not a correctness gap
in the logic behind it — the affirmative-defense engine is real, tested, and
deterministic; the button for it is the next increment.

109 tests back this, all against fakes, with a live headless-browser axe-core
scan finding zero WCAG 2.1 AA violations across every UI state, in both
light and dark palettes. It's deployed and live on Cloud Run.
