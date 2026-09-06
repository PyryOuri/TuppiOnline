# Executor report to the author of the NOLO task packet

From the executor of `docs/nolo/tasks/`, on completing N04–N09.
Date: 2026-09-06. Commit `3123ea7`.

You wrote a queue of nine tasks and a waived gate, and asked for one task at a
time. All of them are now closed. This report is what an executor owes the
designer: what the packet got right, where its design could not have worked, what
turned up that you could not have anticipated, and what I got wrong myself.

## Outcomes

| ID | Endpoint | Outcome |
| --- | --- | --- |
| G1 | independent framing comparison | WAIVED by user decision on cost |
| N01–N03 | fixtures, support, verifier | complete before this executor |
| N04 | security search preserving information sets | **COMPLETE** — finds A's `8S` and B's `9C → 3C` |
| N05 | score pricing and claim labels | **COMPLETE** — zero score discrepancies |
| N06 | ≥20% fewer engine transitions | **NO USEFUL SPEED GAIN** — correct, but 6.3% *more* |
| N07 | ≥5 new deals with a verified score-relevant deviation | **GO** — 13 deals of 256, zero soundness failures |
| N08 | rankings, actions and promised continuations agree | **PASS** — reproduces N07 exactly through the policy |
| N09 | predeclared paired trick improvement | **NOT ESTABLISHED** — +0.0098 tricks/deal, CI [−0.0039, +0.0234] |

## What the packet got right

These are not courtesies; each one caught a real error that would otherwise have
shipped.

**Separating resolution status from claim strength (N05).** Insisting that `TIE`
be reserved for identical *score states* exposed a genuine bug in my first
implementation: I compared raw score pairs, so a candidate reaching `(60,0)`
against a baseline reaching `(56,0)` came out as a preference between two states
that are the same outcome — the match is over and the surplus buys nothing. That
is exactly the overshoot claim the rules forbid, and only your endpoint's wording
made it visible. The fix (collapsing terminal states to win/loss) is now tested
in both directions.

**Requiring an independent verifier before a search existed (N03 before N04).**
Every subsequent result rests on this. N07's soundness gate, N08's cross-check
and N09's commitment check are all the same verifier applied at three scales. Had
the search been allowed to certify itself, none of those checks would mean
anything.

**Forbidding per-world minimisation explicitly.** The prohibition is one line in
N04 but it is the whole difference between a security value and a number that
cannot be attained. Stating it as a constraint rather than leaving it to the
implementer's judgement was correct.

**Demanding a brute-force reference in the test file (N04).** My first reference
grouped *partial* plans and reported 3 where the truth was 5. The bug was in the
check, not the code — which is the most dangerous place for one. It is recorded
in N04.md rather than quietly fixed.

**Prospective thresholds labelled as prospective.** N06's 20% and N07's 5 deals
were both stated as engineering choices rather than predictions, and N06 then
missed its target in the wrong direction with no temptation to relitigate. That
framing worked.

**"Use N06 only if its reduction passed."** A conditional dependency, decided by
a measurement rather than by preference. N07 ran the uncached path and a test
asserts the harness does not import the cache at all.

## Where the packet's design could not have worked: N09

This is the part you most need.

**N09's primary endpoint was unreachable before the first card was played.**

The candidate acts only inside the last three tricks with at most 100 feasible
worlds. N07 measured the consequence: a score-relevant correction exists at a
Team-0 seat in **6 of 256 deals (2.3%)**. A per-deal mean is bounded above by
(correction rate × mean shift). Even if every correction were worth a full trick,
the mean could not exceed ≈0.023 — **less than half the 0.05 threshold N09
requires**. Clearing 0.05 would need corrections worth more than two tricks each,
which the certified bounds in N07 make implausible.

The observed value was +0.0098, inside that envelope.

The cause is ordering. N09 fixed its threshold and its N in the same packet that
N07 was later going to use to *measure the correction rate*. The two numbers were
written independently and are incompatible. A packet in this shape should either
make the strength task's size conditional on the coverage task's measured rate,
or state the rate it assumes so the assumption can be falsified early.

To be clear about what this does and does not say: it is not evidence that the
framing is worthless, and N09's result should not be read as one. It says the
trial as specified could not have detected the effect this candidate produces.
**The binding constraint is the size of the certified region — three tricks, 100
worlds — not the decision rule.**

## Findings you could not have anticipated

**The two primary contrasts were numerically identical.** `D_B` and `D_C`
produced the same value on all 512 deals — same mean, same interval, same
win/tie/loss, same permutation statistic. Team 1's policy did change Team 0's
total in four deals, but it moved `BB→BC` and `CB→CC` by the same amount each
time, preserving the difference exactly.

Your packet warned that the two contrasts share deals and arms and are not
independent replications. On this bank they were not merely dependent: the second
carried **zero** information. The warning was right and was, if anything, too
mild. A future packet could say plainly that `D_C` is expected to be redundant
whenever the candidate's corrections are rare, and ask for it to be reported as
one result rather than two.

**Exact caching makes this search slower, structurally.** N06 is a clean negative
and the reason generalises: the memoised path needs two passes, and the second
still visits every opposition branch because the plan must name an action at each
own key those branches reach. Only own branching is saved, while genuine
transpositions are scarce within three tricks. The depth trend confirms it —
−30.9% at two remaining tricks, −2.0% at three — so amortisation would need trees
deeper than the frozen budget allows. Do not re-propose caching at this depth.

**A dead clause in N07's eligibility rule.** "At least 2 legal actions and 1–3
tricks left" yields **zero** eligible positions at one remaining trick, since
every seat then holds exactly one card. The rule is not wrong, but the `1` in the
range never fires; the real window is two and three tricks. Worth writing as
`2–3` so the scope is honest on its face.

**Roughly one eligible decision in five is unresolvable at the stated budget.**
372 of 1,785 in N07, of which 329 exceeded the 100-world support limit and 43 the
100,000-transition search limit — all of them at three remaining tricks. Your
insistence that these stay in the denominators was the right call and I kept it,
but a future packet should expect that share rather than treat it as a tail.

**The execution machinery works and the guarantees hold.** In N09 the adapter
drove 2,048 complete thirteen-trick deals, made 42 certified commitments,
executed 66 planned continuations from them, and broke **none**. Every earlier
task measured at positions along a baseline trajectory; this is the first
evidence the retained plans survive the candidate actually playing deals out.
This was the half of N09 that was not foregone, and it is the reason the trial
was worth running despite the endpoint being unreachable.

## What I got wrong, disclosed

**I abandoned the first N09 run at 90 of 512 blocks.** Its 4-hour cap — your
figure, which I adopted — was justified in my v1 preregistration from a pilot of
six development deals measuring 245 CPU-seconds per block. The real bank runs at
about 490, so completion was impossible. The pilot was too small and the sizing
error is mine. The partial records are preserved unanalysed; v2 changed the cap
to 8 hours and nothing else, and the run started again from scratch. The
completed run took 4.55 hours, so your original cap would have missed by about
half an hour. Both preregistrations are kept, and v2 discloses the two aggregate
counts I had seen while monitoring v1.

**A reporting bug survived into the first N09 report.** The per-arm aggregation
summed `max_latency_seconds` instead of taking a maximum, turning the slowest
single decision into a total. Corrected, report re-derived from the preserved
per-block records; every effect, interval and endpoint verdict is byte-identical
before and after.

**I over-scoped once and was told so.** Early in this work I wrote a
research-grade preregistration for what was a display formatting decision. The
correction was warranted.

## Recommendation for the next packet

**Do not re-run N09 at larger N.** This is the tempting wrong move. The effect is
capped by coverage, not by noise; more deals would estimate the same tiny number
more precisely and still fail the same threshold. Extending N to reach
significance is also what your own packet forbids, and rightly.

**The open question is whether the certified region can be enlarged at acceptable
cost.** That is a search-algorithm question, not a tuning one. At three tricks the
p95 decision already costs 164 seconds and the p50 support is 9 worlds against a
100-world ceiling that 18% of positions exceed. Reaching five or six tricks is
not a parameter change, and N06 established that the obvious exact optimisation
goes backwards. A next task should ask for a *bound* on what depth is reachable
before it asks for another strength trial — and should fix its acceptance
threshold against the coverage rate that task measures, not before it.

**If that bound is discouraging, closing the branch is a legitimate outcome.**
The programme has a correct, verified, offline implementation of a decision rule
that provably improves rare positions and never breaks its promises. That is a
real asset if the reach problem is ever solved, and an honest dead end if it is
not. Either way the machinery is finished, tested, and documented, and no
production source was touched.

## Artefacts

Results `docs/nolo/results/N04.md` … `N09.md`; preregistrations
`docs/nolo/hypotheses.md`, `hypotheses-n09-v1.md`, `hypotheses-n09-v2.md`;
evidence under `work/nolo/`, including the preserved abandoned v1 trial. Source
in `src/tuppi_nolo/`, tests in `tests/nolo/` (215 passing). The four failures in
`tests/exact/test_integrity_and_variants.py` are pre-existing and name only
`src/tuppi_agents/void_lead.py`.
