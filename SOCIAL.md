# Social posts — legal-navigator

## X (under 280 characters)

92% of civil legal problems facing low-income Americans get no or inadequate
help (LSC, The Justice Gap). I built a tool that reads an eviction summons,
computes the real CA deadline, and answers with a citation — or refuses
rather than guess. #AllThingsAgenticHackathon

(char count: ~262)

## LinkedIn

92%. That's the share of civil legal problems substantially affecting
low-income Americans that get no or inadequate legal help, per the Legal
Services Corporation's "The Justice Gap." Legal aid organizations turn away
roughly half of everyone who asks, because they don't have the staff.

In California, that gap collides with a hard clock: a tenant served with an
eviction summons has five *court* days to respond, or the landlord can take
a default judgment with no hearing.

For the All Things Agentic Hackathon, I built a tool for the space between
those two facts. Photograph the summons, and it reads the case details,
computes the real deadline (accounting for how the method of service shifts
it — substituted service adds ten days before the clock even starts), and
answers questions with an exact citation attached. If it can't cite
something from its statute corpus, it refuses rather than guess, and offers
to assemble a legal-aid intake instead — pre-filled with everything it
already knows, so a tenant under pressure doesn't have to repeat their case
number to an advocate from scratch.

The citation check caught a real bug against the live model in production,
not just in tests: the model was echoing a citation back wrapped in
formatting punctuation, and the exact-match check correctly refused to
accept it as identical. The honest fix was to stop giving the model a reason
to add punctuation — not to loosen the check.

It never files anything. A human reviews and files every document. 109
tests, deployed live on Google Cloud Run, zero WCAG 2.1 AA violations on a
real axe-core scan.

Built and written up for the All Things Agentic Hackathon.
#AllThingsAgenticHackathon
