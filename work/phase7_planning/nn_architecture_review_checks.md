# Checking the external architecture review against the repository

`nn_architecture_review.md` was written with no repository access. It makes
several checkable claims and asks for eight specific facts. This records what was
checked on 2026-09-08, what was found, and what it changes.

**Headline: it found two real defects in the briefing and one in the project's
own inherited assumptions, and two of its structural deductions are exactly
right.** Nothing it asserts was found to be wrong.

---

## Claims checked

### 1. "Showing can have more than 14 legal actions" — CONFIRMED, exactly

The briefing reported a *measured* maximum of 14 legal show actions. The review
reasoned from the rules text that a hand containing no rank 3–9 falls to fallback
priority 3, may show **any** of its thirteen cards under **either** declaration,
and therefore has 26 legal actions — and that such a hand exists because the deck
holds 24 cards outside ranks 3–9.

Constructed and run against the engine:

```
cards outside ranks 3-9: 24
acting seat holds no rank 3-9: True
legal show actions: 26          by contract: {'NOLO': 13, 'RAMI': 13}
```

**Exactly as predicted.** The measured 14 was a property of the sample, not a
bound. Any fixed-width showing head sized at 14 would be a latent bug. The
briefing's §2.2 should say the rules bound is 26.

### 2. "25 nonterminal score states, 100 with the dealer" — CONFIRMED, exactly

The review deduced that because every award is a multiple of 4, the reference
continuation has only 25 nonterminal score configurations. Enumerated the closure
of the reachable set under `transition_rising_score` over every point value the
three scoring formulas can produce:

```
deal point values: [4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 56]   all multiples of 4
reachable NONTERMINAL score states from 0-0: 25
  x 4 dealer positions = 100
```

**Exactly as predicted**, again from the rules alone.

### 3. "Took a trick it could have ducked ⇒ holds nothing lower" is behavioural, not entailed — CONFIRMED BY MEASUREMENT, and the briefing was wrong to pass it on

This is the most consequential correction. `docs/valuation/handoff.md` §3.1 lists
this inference under "robust under rationality, not policy", and the briefing
repeated that. The review objected that partnership scoring gives a rational
player reasons to take a trick while holding a lower card, and that the inference
is therefore behavioural.

Measured directly over 1,500 pilot deals — for every trick where the eventual
winner acted *after* some seat was already winning, did the winner hold a lower
card of the led suit?

| Contract | Violations | Share |
| --- | ---: | ---: |
| NOLO | 417 / 2 399 | **17.4%** |
| RAMI | 2 763 / 6 451 | 42.8% |
| overall | 3 180 / 8 850 | 35.9% |

RAMI is unsurprising — taking tricks is the objective there, and the inference was
only ever proposed for NOLO. **But it is violated in 17.4% of the NOLO cases it
was meant for, on the reference policy's own play.** Promoting it to a hard
ownership mask would produce false constraints in roughly one case in six.

The review's specific mechanism is also strategically sound here: NOLO scores
*team* trick totals, so which partner takes a conceded trick cannot change the
score, and the reference's own catalogue reasons from exactly that in
`partner.nolo.dump_liability_when_partner_certainly_wins.v1`. (That particular
rule fires only when the acting seat *cannot* beat the partner, so it is not
itself the counterexample — which is why this was settled by measurement rather
than by reading the catalogue.)

**Action: treat this as a soft feature or a training label, never a hard mask.**
The briefing's §3.4 needs amending, and so does the sentence it inherited from
`handoff.md`.

### 4. The forced-action correction to the 85% agreement figure — CONFIRMED

The review adjusted 85.27% agreement for forced actions to 81.3% on genuine
choices, explicitly flagging that it had to assume the clone's test set shared
the 21.2% forced rate measured on the *new* corpus mixture, and asking for the
real number.

Measured under the Phase 6 generating configuration (its own root seed
`phase6-imitation-v1`, its 20-deal cap, frozen Phase 4 policies), 24,109
decisions:

| | |
| --- | ---: |
| forced (exactly one legal action) | **21.4%** |
| showing share of decisions | 4.9% |
| forced within showing | 0 |
| forced within trick play | 22.5% |
| forced-adjusted agreement at this rate | **81.3%** |

**Its assumption was safe and its figure is right to the decimal.** One caveat
it could not have known: the Phase 6 corpus drew trajectories from a mixed
profile schedule and took *labels* from `partner_aware_v1`, so this is the
generating distribution's forced rate rather than a recount of that exact test
set. The rate is a property of the rules and barely moves between
configurations (21.2% vs 21.4%), so the adjustment stands.

---

## Facts requested, and the answers

### "Exact definition of Part 4 equity" — it already is the recommended construction

The review recommends per-deal frozen-continuation match equity as the primary
endpoint, computed by solving an absorbing Markov chain over the coarse score
space rather than by rolling out complete matches. **That is exactly what
`src/tuppi_valuation/equity.py` already does**, and it is the equity in Part 4's
table. From its own documentation:

> Because every award is a multiple of four, a nonterminal match state is fully
> described by the up team's level `u = score / 4` in 0..12, which team holds it,
> and which team deals next: fifty states. Given a deal-outcome distribution that
> is a single absorbing Markov chain, and its absorption probabilities *are* the
> match win probabilities.

Fifty rather than the review's hundred because it is written from one team's
perspective and collapses the dealer to a binary "we deal next". The review's
caveat is also already stated there:

> The deal model is an input. Supplied from a corpus it is empirical, and every
> equity computed from it is conditional on the policy that generated it; the
> match arithmetic on top is exact either way.

Two properties from that module are worth carrying into any design work:

- under equal-strength play equity is confined to **[1/4, 3/4]** — "being one
  deal from victory is a three-to-one position, not a certainty";
- the value is **strongly convex** in the score, so a linear reading of the
  scoreboard badly misprices the endgame.

So Experiment 0's "calibrate the small reference-continuation table" is largely
built. What remains is to confirm the deal model it was fitted from and to carry
its calibration uncertainty, as the review asks.

**Scale check on the proposed threshold.** The review proposes δ = 0.001 equity
per evaluated deal, calling it a funding threshold rather than a measured
property. For context from Part 4: the reference's whole equity contribution on
the declaration decision is +0.00652, and perfect foresight is +0.02126. So
δ is about 15% of the reference's total value on that decision, and about 5% of
the foresight ceiling. That seems a defensible order of magnitude, but it is
worth stating in those terms before it is frozen.

### "Forced-contract intervention semantics" — already as the review requires

The review warns that "force this player to say NOLO" and "force the final
contract to be NOLO" are different interventions, and that the alternative must
be a complete legal action rather than a bare contract label.

The corpus implements the first reading and the complete-action requirement:
the forced arm takes **the policy's own best-ranked legal show action for the
wanted contract**, and a forced NOLO passes showing on so a later seat may still
declare RAMI. `tests/corpus/test_corpus.py` asserts precisely this — that the two
arms' *first declarations* differ while the deal's resulting contract may agree —
and the test comment records why.

One thing the review asks for is **not** yet satisfied: it wants the alternative
branch's card chosen by a fixed declared selector (lowest eligible rank, engine
order tie-break) rather than by the reference's own ranking. Those are different
interventions and the choice should be preregistered.

### "Future-deal independence and cross-deal policy state" — none

Every policy in the population is deterministic and observation-only, decided
from a single formal observation with no state carried between decisions or
deals. `partner_aware_v1` additionally has `match_state_enabled = false`, so it
does not read the score at all. Deals within a stream are independent draws from
`MatchStream`. The 100-state table is valid on this point.

### "What makes reserved policies genuinely different" — a concession

They are not genuinely disjoint. The reserved held-out sets are
`partner_aware_discard_v3` paired with `partner_aware_v1`, and
`public_counting_v1` in all four seats. Every member of the population is a
rule-based policy from the same ladder, sharing the same scoring framework, the
same tie-break, and in most cases the same following play.

**So the corpus's "cross-policy" held-out split measures within-family variation,
not transfer.** The review's Experiment 3 gate needs a genuinely different
opponent family to mean what it says, and the corpus does not currently contain
one. The softened stratum is the only non-deterministic behaviour available, and
it is a perturbation of the reference rather than a different player.

### "Policy identities and continuation metadata for every paired stratum" — present

Every match record carries its stratum, its policy-set index and its split; every
deal carries flags identifying whether its action was forced, epsilon-branched or
softened, plus the branch ply. Policy sets resolve to content-addressed
`agent:sha256:` identities. Paired strata use the reference in all four seats, so
the continuation profile of a pair is the reference — which is the target the
review wants — but it should be verified per stratum rather than assumed.

### Two facts that could not be checked here

- **The PyTorch CUDA 12.6 removal announcement.** No network access in this
  session, so the September 2026 claim is unverified. Its practical advice —
  pin a locally verified build rather than planning around "latest" — matches
  the briefing's own warning and costs nothing to follow.
- **Clone contract-only agreement, deployed disagreement rate, single-deviation
  losses.** These need the preserved Phase 6 checkpoint, which requires `torch`;
  it is not installed in the only environment on this machine. The artifacts are
  preserved under `TuppiRuns/phase6` and the audit tool
  `tools/phase6_verify_artifacts.py` exists, so this is an install away rather
  than a lost measurement.

---

## What this changes in the briefing

Three edits are warranted before the briefing is reused:

1. §2.2 — the showing action bound is **26**, not the measured 14.
2. §3.4 — the "took a trick it could have ducked" inference is **behavioural and
   violated 17.4% of the time in NOLO**. It must not be described as robust under
   rationality, and the same correction applies upstream in
   `docs/valuation/handoff.md` §3.1.
3. §5.3 — the held-out policy reservation should be described as within-family
   variation, not cross-policy transfer.

## What it changes in the plan

The review's central recommendation — a tightly scoped showing intervention
before any belief or value network, with the corpus deferred — conflicts with the
charter's P9–P12 ordering and with generating T1 now. That is a decision for the
corpus owner, not a correction to record here. The relevant new information is:

- the recommended primary endpoint **already exists** in `tuppi_valuation`;
- its Experiment 1 needs conditional hidden-hand completions at a fixed
  observation, which the exact sampler in `tuppi_exact` supplies but the corpus
  generator does not currently expose;
- Experiment 3 needs an opponent family the corpus does not contain.
