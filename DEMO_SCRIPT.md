# Demo script — 4:00 maximum

## 0:00–0:35 — The problem, with the source on screen

On screen (slide or overlay, held for the full line):

> "Low-income Americans do not get any or enough legal help for 92% of their
> civil legal problems that substantially affect them."
> Legal Services Corporation, *The Justice Gap*

**Say:** "Ninety-two percent. And legal aid organizations turn away roughly
half of everyone who asks, because they don't have the staff. Meanwhile, if
you're served with an eviction summons in California, you have five *court*
days to respond. Miss it, and the landlord can take a default judgment
without a hearing. This is built for the gap between those two facts."

## 0:35–1:00 — What this is

**Say:** "This doesn't give legal advice, and it never files anything. It
reads your summons, works out your real deadline, and answers your
questions with the exact law it's relying on attached — and when it can't
find support for something, it says so instead of guessing."

## 1:00–2:45 — Live run, unedited

1. Open the console on a phone (or phone-sized viewport). Photograph a
   summons. Show the deadline appear on screen.
2. Ask a question that's in scope — e.g. "how many days do I have to
   respond to the summons" — and show the answer with its citation printed
   directly under it.
3. **The most important shot in the video:** ask something the corpus does
   not cover — e.g. "how do I register a trademark for my business" — and
   show the tool refuse rather than guess. Narrate over it: "It would
   rather say nothing than make something up about your case."
4. Trigger a halt condition (e.g. a summons whose deadline has already
   passed) and show it route to "talk to a person now" with the referral
   already assembled from what the tool knows — case number, court,
   deadline — so nobody has to repeat themselves to an advocate.

## 2:45–3:20 — Proof it runs on Google Cloud

Show, in order: the Cloud Run service dashboard (the deployed revision,
serving traffic), Cloud Logging (the structured `event` lines this project
emits — e.g. `answer.rejected` when a citation fails the invariant), and
Cloud Trace (a `navigator.ask` span showing the grounding check as part of
the request).

## 3:20–4:00 — The limits, stated plainly

**Say:** "California unlawful detainer only. It never files anything on
your behalf — you review and file everything yourself. Every legal
statement carries a citation, and when it can't cite one, it says so and
offers to prepare an intake for a legal aid advocate instead. The
affirmative-defense assessment behind the drafted Answer is deterministic,
rules-based code, not the model — because a hallucinated defense in a real
court filing is the one failure this tool cannot afford."
