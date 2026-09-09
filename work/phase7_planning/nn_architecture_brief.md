# Briefing: neural architecture for Tuppi

You are being asked to do architecture thinking for a learned-policy programme
in a four-player imperfect-information trick-taking card game called Tuppi. You
have no access to the codebase, so this document is written to be
**self-contained**: the complete rules, the exact information a player may see,
the data that exists, everything that has already been tried and failed with its
numbers, the hardware budget, and the specific questions we want your judgement
on.

Everything stated as a measurement was measured. Where a figure is an estimate
or an assumption it says so. Please treat the negative results as the most
valuable part — several are unintuitive and cost real time to establish.

**How to read this.** Parts 1–2 are the game and the information structure; you
need them to say anything useful. Part 3 is what failed and why — §3.3 and §3.4
are the two you should not skip. Part 4 is the quantitative case that a learned
function could help at all. Part 5 is the data you would actually have. Parts
6–7 are the budget and the non-negotiables. Part 8 is the question set.

**One framing note.** This project's convention is to write the gate before the
measurement and to stop when it fires. A proposal that cannot state, in advance,
what result would make it stop is not usable here.

---

# Part 1. The game

## 1.1 Setup

Four players in fixed clockwise seats 0, 1, 2, 3. **Partnerships never change:
Team 0 is seats 0 and 2, Team 1 is seats 1 and 3.** Partners sit opposite.

A standard 52-card deck is dealt completely: each player holds exactly 13 cards.
Ranks low to high: 2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A. Hearts and diamonds
are red; clubs and spades are black.

**There is no trump suit.** This matters more than it sounds — see §1.7.

The dealer is supplied externally. `forehand = (dealer + 1) mod 4`; the dealer
rotates by one seat after each completed, non-terminal deal.

## 1.2 The showing phase (the one non-card-play decision)

Before play, each player in turn may declare one of two contracts:

- **RAMI** — teams try to *win* tricks.
- **NOLO** — teams try to *avoid* tricks.

A *show* is one card from your hand, revealed publicly, plus an explicit
contract declaration. **The shown card stays in your hand** and may be played
normally later; it is not reserved.

Showing starts with the forehand and proceeds clockwise. **Showing ends
immediately at the first RAMI declaration** — that player is the *declarer*
(*ramaaja*), and later seats never act. If all four players declare NOLO, the
contract is NOLO with no declarer.

Which cards may be shown is a mandatory three-level hierarchy. Only ranks **3–9**
are normally eligible. RAMI's normal colour is **red**; NOLO's is **black**.

| Priority | Hand condition | Valid shown cards | `verbal_required` |
|---|---|---|---|
| 1 | you hold an eligible card of the contract's normal colour | only eligible cards of that colour | false |
| 2 | no eligible matching-colour card, but some eligible card | any eligible card, any colour | true |
| 3 | no eligible card of either colour | any card in hand | true |

You may not use a lower priority while a higher one is available.
`verbal_required` is *derived* from (hand, shown card, declaration), not chosen —
it is public, and it therefore leaks information about the whole 13-card hand
(see §1.6).

**Consequence for the action space:** a show action is a (card, contract) pair,
and because eligibility depends on colour *and* contract, the legal set is
usually asymmetric between the two contracts. Measured legal show-action counts
range 2–14 with a mode of 7, but **the rules bound is 26, not 14**: a hand
holding no rank 3–9 falls to priority 3 and may show any of its thirteen cards
under either declaration. Such hands exist — the deck holds 24 cards outside
ranks 3–9 — and the engine does return 26 legal actions for one. Do not size a
fixed showing head at 14.

## 1.3 First leader

- NOLO: the **forehand** leads trick 1.
- RAMI: the seat immediately *before* the declarer in clockwise order leads,
  i.e. `(declarer - 1) mod 4`. So the dealer leads when the forehand declares
  RAMI.

## 1.4 Trick play

The leader plays any card. Each following player **must follow the led suit if
able**; if void, may play anything. Four cards per trick, clockwise from the
leader. **The highest card of the led suit wins** — off-suit cards, aces
included, cannot win. The winner leads the next trick.

All 13 tricks are always played, even when the outcome is already mathematically
determined. Scoring happens only after trick 13.

## 1.5 Scoring — this is where the game's character lives

Let the two teams' trick totals sum to 13, so ties are impossible.

**NOLO** — the team with *fewer* tricks wins. With `w` = winner's tricks:

```
points = 4 × (7 − w)
```

| w | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|--:|--:|--:|--:|--:|--:|--:|
| points | 4 | 8 | 12 | 16 | 20 | 24 | 28 |

**RAMI** — if the declaring team takes ≥ 7 tricks it wins
`4 × (declaring_tricks − 6)`, i.e. 4 … 28 points.

If the declaring team takes ≤ 6 tricks, the *opponents* win by **stolen rami**
(*ramin ryöstö*) at **double rate**, with `o = 13 − declaring_tricks`:

```
points = 8 × (o − 6)
```

| declaring tricks | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|--:|--:|--:|--:|--:|--:|--:|
| stolen-RAMI points to opponents | 8 | 16 | 24 | 32 | 40 | 48 | 56 |

**The asymmetry is the central strategic fact of the game.** A made RAMI on the
6/7 boundary pays 4; a failed one on the same boundary pays the opponents 8. This
is why declaring RAMI is a genuine gamble and why the break-even success
probability is well above 50% (measured empirically at ≈ 62%).

## 1.6 The rising-score match

A valid match score is `0–0`, `positive–0`, or `0–positive`. **Both teams can
never be positive at once.** The team with a positive score is *up*.

After each scored deal:

| State | Deal winner | Result |
|---|---|---|
| 0–0 | either | winner takes the points and becomes *up* |
| one team up | the up team | points are **added** to its score |
| one team up | the down team | the up team's score is **erased to 0–0**; the down team receives **nothing** |

The match ends when the up team's score is **≥ 52**. Overshoot is allowed.

So a 56-point stolen rami by the down team is worth **zero points** — it only
resets. This makes the value of a deal outcome strongly **state-dependent**, and
it is the reason a value function cannot be a function of the deal alone. A
separate measurement found that the same hand is worth about **2.6× more** at
either extreme of the scoreboard than at 0–0, but that the *relative* weighting
of hand features does not change with the score (no coefficient difference
reached |z| = 2).

Also measured, and counterintuitive: **overshoot past 52 is worth nothing**, and
margin is priced below an up-score of ~24 and collapses above it. At 48–0 every
winning margin is identical.

## 1.7 Two structural properties worth exploiting

**No trumps.** A card can only ever win a trick led in its own suit. Therefore
every trick belongs to exactly one suit, and under a fixed card-selection rule
the winner of a suit-led trick is the holder of the highest card among those
still able to follow — which does *not* depend on the order the seats play in.
This makes **exact single-suit combinatorics tractable without a game tree**:
there is existing code that enumerates every exact layout of a suit's
outstanding cards with its true probability, giving an exact per-suit Bayesian
posterior conditioned on public observations. That is an unusually strong
reference signal to have available.

**Showing leaks whole-hand information.** The public tuple
`(seat, shown_card, declared_contract, verbal_required)` is a *hard* statement
about cards the shower does **not** hold, because `verbal_required` is derived
from the complete 13-card hand through the mandatory hierarchy. Existing exact
inference uses this and it is strictly stronger than the obvious deductions
(cards played, cards shown, failure to follow suit, remaining capacity).

---

# Part 2. What a player may see

## 2.1 The observation, exactly

A policy receives **only** this immutable object, and nothing else — no engine
state, no other seat's hand, no deal identifier derived from hidden state:

| Field | Content |
|---|---|
| `observing_seat`, `team`, `partner_seat` | seat identity and partnership |
| `dealer`, `forehand` | role seats |
| `phase` | SHOWING / TRICK_PLAY / DEAL_COMPLETE / MATCH_COMPLETE |
| `current_actor` | whose turn |
| `own_hand` | the acting seat's own cards |
| `show_actions` | the ordered public shows so far: seat, card, contract, `verbal_required` |
| `publicly_shown_cards` | shown cards (still in their owners' hands) |
| `contract`, `declarer`, `first_leader` | resolved contract context, or null |
| `completed_tricks` | every completed trick: leader, the four (seat, card) plays in order, winner |
| `current_trick` | the partial trick so far |
| `team_tricks` | public running trick totals per team |
| `match_score` | the rising score |
| `legal_actions` | the engine's own legal action tuple, in a stable versioned order |
| `deal_terminal`, `match_terminal` | flags |

There is no hidden information in the observation and no noise: the public
history is complete and exact. All hidden information is precisely "which of the
39 unseen cards is in which of the three other hands", constrained by public
deductions.

## 2.2 The action space

- **Play action** = one card → at most 52 distinct.
- **Show action** = (card, contract) → at most 104 distinct.
- Total vocabulary ≤ 156 action tokens. In practice you score only the legal
  tuple.

**Measured decision statistics** (800 deals, 43,674 decisions):

| | |
|---|---:|
| decisions per deal | **54.6** |
| showing decisions | 4.7% |
| trick-play decisions | 95.3% |
| **decisions with exactly one legal action (forced)** | **21.2%** |
| forced, among trick-play decisions | 22.3% |
| forced, among showing decisions | 0.0% |
| **real choices per deal** | **43.0** |

Legal-action-count distribution over all decisions:

| count | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| share | 21.2% | 19.6% | 15.4% | 9.9% | 6.6% | 5.2% | 4.7% | 4.4% | 3.5% | 2.9% | 2.5% | 2.2% | 1.9% |

So the decision space is small and heavily skewed toward very few options. A
fifth of all decisions carry no information at all.

**And half of the rest are inert.** Measured by playing *every* legal action out
under the frozen reference on the same hidden deal, over 396 trick-play
decisions that had a genuine choice:

| | |
|---|---:|
| mean legal actions | 5.27 |
| mean **distinct outcomes** | **1.79** |
| decisions where every legal action gives the identical result | **50.3%** |

Distribution of distinct outcomes: 1 → 50.3%, 2 → 29.8%, 3 → 12.4%, 4 → 6.3%,
5+ → 1.3%.

Combining the two: **about 61% of all decisions cannot change the deal's
outcome** (21.2% forced, plus 50.3% of the remaining 78.8%). Roughly 21 of the
54.6 decisions in a deal have any leverage at all.

Three structural causes, all consequences of §1.4 and §1.5: with no trumps a card
can only win a trick led in its own suit, so most cards are interchangeable in
most positions; two cards of one suit in one hand are strictly equivalent when
the ranks between them are also the actor's own; and all 13 tricks are always
played, so many late decisions are already determined. In NOLO, team-total
scoring adds a fourth — which partner takes an already-conceded trick cannot
change the score.

**This is the single most important fact for objective design.** An
action-agreement metric counts a disagreement on an inert decision exactly as
heavily as one on a decision worth 28 points. It also means the clone's 85.27%
agreement is compatible with anything from near-perfect play to catastrophe: if
all of its 15% disagreements fell on decisions with leverage, it was wrong on
**38%** of the decisions that mattered.

## 2.3 Scale of an episode

| | |
|---|---:|
| decisions per deal | 54.6 |
| deals per match, mean / median / p90 / p99 / max | **24.7 / 22 / 73 / 156 / 245** |
| decisions per match (mean) | ~1,350 |

Match length is **heavy-tailed** because of the reset rule. This has a hard
consequence for credit assignment: **terminal match win/loss credits one bit to
~1,350 decisions.** Every endpoint decision below follows from that.

---

# Part 3. What has been tried, and what it cost

This project has run five sequential programmes. **Four produced negative
results.** They are the reason we are asking for architecture thinking rather
than just scaling something.

## 3.1 The baseline population (hand-written, transparent)

A ladder of five deterministic, observation-only rule-based policies of
increasing capability, each a strict superset of the one below. The strongest
useful one is called `partner_aware_v1`: contract-aware trick play, hard public
inference (proven voids, certain winners, hard counts), and explicit partnership
rules.

Two later hand-written improvements were measured, paired on identical deals,
and are now the reference:

| Change | Measured |
|---|---:|
| NOLO lead: lead the **shortest suit**, lowest card within it (instead of lowest card in hand) | **−0.69 tricks, +13.9 pp deal-win rate** |
| RAMI lead: lead the suit worth the most tricks if **played out** (instead of HCP + 0.5×length) | **+0.36 tricks, +8.2 pp** |
| NOLO discard priced by exact ducking combinatorics (instead of a rank-only liability table) | **−0.338 tricks/deal**, 95% CI [−0.392, −0.284], z = −12.5 |

(Fewer tricks is better under NOLO.) All three are *dominant* — still ahead when
the opponents adopt them too.

**Important caveat: zero of the 38 catalogued strategy rules are
expert-validated or simulation-validated.** About a third are ported from an
unverified legacy implementation and about a third are generic trick-taking
intuition. This bot is a reproducible yardstick, not a strong player. Nobody has
compared it to a competent human.

## 3.2 Classical search — four families, all lost to the rule-based bot

Every search agent was evaluated over 32 *complementary* complete-match pairs
(same deals, teams swapped) against the rule-based reference.

| Approach | Result vs the rule-based bot |
|---|---|
| Perfect-Information Monte Carlo over exactly-uniform feasible worlds | p(win) = **0.156**, 0W/10T/22L, sign-flip p = 0.0001 |
| Root-player information-set UCT | **lost all 32 pairs** |
| Multi-observer re-determinizing ISMCTS | p(win) = **0.125**, 1W/6T/25L |
| Behaviour-cloned neural policy | p(win) = **0.0156**, 0W/1T/31L |

Two diagnosed mechanisms, both relevant to you:

1. **Strategy fusion.** PIMC evaluates each sampled world as a fully-observed
   world and averages afterwards, so it happily combines mutually incompatible
   world-specific plans.
2. **Rollout policy mismatch.** PIMC's rollouts modelled a partner that was not
   there: with a rule-based partner the assumed continuation matched perfectly
   (32/32 control positions), but with a PIMC partner it diverged in 29/32
   positions within the first action or two.

A belief-weighting programme was also run and **failed its own gate**: a matched
behavioural likelihood over a finite weighted particle set was too concentrated
to be usable — mean effective sample size **6.47 out of 32** particles, and
held-out negative log-likelihood was *worse* than a hard-uniform baseline (1.747
matched vs **1.050** hard-uniform). The signal existed in tiny exact spaces
(0.314 nats improvement over exact uniform on six positions) but the
finite-particle approximation destroyed it.

## 3.3 The behaviour-cloning attempt, in detail — please read this one closely

This is the direct precursor to what you are being asked about.

**Setup.** Supervised imitation of the deterministic rule-based reference. One
shared seat-relative network. Inputs: only the acting seat's formal observation
plus its legal action tuple. Physical seats rotated into self / left opponent /
partner / right opponent roles.

**Architecture** (`seat_relative_actor_gru_deepsets_v2`, **41,900 parameters**):

- shared card embeddings
- DeepSets-style permutation-invariant pool over the own hand
- a small GRU over the public showing/trick history — each history element
  carrying card, relative seat, event kind, declared contract, within-trick
  position, public trick winner
- a pooled representation of the current trick
- a 32-value public context vector: contract, declarer/leader roles, public
  trick totals, match score, phase, current trick length, dealer/forehand roles,
  public void flags
- a legal-action scorer that **embeds only actions present in the legal tuple**,
  so an illegal action cannot receive probability

**Data.** 20,769 / 7,576 / 7,061 train / validation / held-out examples from
disjoint streams. 15 epochs, batch 256, lr 0.001, CPU.

**Results.**

| Metric | Result |
|---|---:|
| held-out action agreement, overall | **85.27%** |
| showing agreement | 84.70% |
| trick-play agreement | 85.30% |
| RAMI agreement | 88.28% |
| NOLO agreement | 76.26% |
| declarer agreement | 83.74% |
| defender agreement | 89.80% |
| **strength, 32 complementary complete-match pairs** | **0 W / 1 T / 31 L, p(win) = 0.0156** |

**This is the single most important data point in this document.** 85% action
agreement with the target policy produced a player that loses ~97% of matches to
that same target. Whatever the explanation — compounding error over ~1,350
decisions per match, the 15% of errors being concentrated exactly where
decisions matter, distribution shift once the clone drives the trajectory, or
something else — an architecture proposal that does not have a story for it is
not responsive.

The programme's own conclusion was: **continue only if a genuinely new resource
is available**, and do not run another rescue subphase or unbounded parameter
sweep.

## 3.4 The trap that killed the belief-modelling idea in its naive form

This is the most important *methodological* finding in the project, and it
constrains any learned belief model.

Assume opponents duck their lowest card. Then a played card is an exact order
statistic and looks highly informative: the expected length of the player's
holding ranges from 3.84 (they led the 2) down to 1.40 (they led the queen),
against an unconditional 3.36. **Drop that policy assumption** and read the
observation only as `min ≤ c`, and the **signal retained is 1–5%** for exactly
the high-card observations that looked most informative.

> That table was measuring the bot's determinism, not the game.

Reinforcing this: the reference bot leads its **lowest card 100% of the time**
and its shortest suit only 34.1% of the time (before the lead fix; after it, the
NOLO lead *is* the shortest suit 100% of the time, mean length 1.77 — a perfect
public signal, since both partners run the same rule). Real players do not lead
predictably lowest; the project owner has confirmed this.

**What survives without a policy assumption:**

- **Certain:** a discard proves a void (~30% of follower plays generate one);
  cards seen are cards gone.
- **Weaker than it looks, and NOT a hard deduction:** it was previously recorded
  here that a seat which took a trick it *could have ducked* holds nothing below
  the current high card, "robust under rationality". **Measured over 1 500 deals,
  that is violated in 17.4% of the NOLO cases it was meant for** (and 42.8% in
  RAMI, where taking tricks is the objective). NOLO scores *team* trick totals,
  so which partner takes an already-conceded trick cannot change the score, and a
  rational player has reasons to shed a high card into it while holding lower
  ones. Usable as a soft feature or a training label; **never as a hard ownership
  mask.** The related fact that does hold: 45% of NOLO follower choices are in
  the branch where every held card would currently win.
- **Policy noise, discard it:** which low card someone ducks with; which rank a
  leader chooses.

Consequence: a belief model trained on a corpus generated by a deterministic
policy learns to **invert that policy**, not to read the game, and will not
transfer. Any held-out evaluation must be **cross-policy** — train on one
population, evaluate on a disjoint one — or the metric is measuring policy
inversion.

## 3.5 Other measured dead ends, so you do not re-derive them

- **Second hand low** and **third hand high**, imported from bridge into RAMI
  following, both *lose*: −0.102 tricks (z = −1.8) and −0.107 (z = −3.9); both
  together −0.207 (z = −3.3). Two reasons: second-hand-low is a defensive maxim
  that presumes a *visible dummy*, which Tuppi does not have; and the bot already
  implemented the expert form of third-hand-high ("cheapest of equals"), so the
  "improvement" was a regression to the beginner's version. **A bridge maxim is a
  compressed summary of a specific information structure and a specific scoring
  rule — check which you are importing.**
- **"Void your cheapest suit"** (short *and* free of high cards, rather than
  short) is worth nothing: −0.007 tricks, z = −0.2. Length is the entire story.
- **Answering a partner's shortness signal** by leading their signalled short
  suit measures +0.094 tricks (z = +1.2) — not significant, and it costs your own
  void, worth −0.69.
- **Being on lead is not a liability in NOLO**: leader wins 25.5%, followers
  22.2 / 24.8 / 27.5%. Flat. (RAMI is a different game: the leader wins 71.6%.)
- **Cheap entry modelling hurts** (+0.188 vs +0.360 for the rule it replaced).
- **The match-score-aware rule set is worth exactly zero equity.**
- A rule scored with an **opening-deal prior** but applied mid-deal is worth
  nothing (−0.032 tricks, z = −0.4); recomputing the same law from the *current*
  position turned it into +0.36 tricks. **The idea was never the variable; the
  probability law was.**

## 3.6 The A/B loop has a ceiling — and this is the argument for learning

The two shipped improvements both came from the same loop: find a heuristic gap,
write a competing rule, measure it paired on identical deals. It works, and two
of three refinements tried this way measured zero or negative.

> It can only find the best member of a family someone thought of in advance, and
> it gives no bound on what lies outside that family.

---

# Part 4. The measured headroom — the best-posed learning question

On the RAMI declaration decision (the one non-card-play decision), a study over
4,000 deals with a proper split-sample established:

| Policy | Equity per deal | Share of ceiling |
|---|--:|--:|
| always pass | +0.00000 | 0% |
| always declare | −0.00093 | −4% |
| the rule-based bot | +0.00652 | **30.6%** |
| best hand-descriptor rule (`HCP − 0.5 × low_cards ≥ 10`) | +0.00718 | **33.8%** |
| **perfect foresight** | **+0.02126** | **100%** |

The full eight-descriptor regression explains **R² = 0.106** of the variance in
the gain. The study's own conclusion:

> Whether declaring RAMI is right is mostly determined by things a point count
> cannot see — how the suits actually lie.

Break-even is at 12 high-card points, and the sign changes cleanly at 12 and
never changes back. Low cards (ranks 2–4) argue against declaring more reliably
than high cards argue for it: coefficient −0.00356 (z = −4.43) versus
+0.00392 (z = +2.88) for HCP. A card of rank 2–4 is worth roughly **−0.9 HCP**
against declaring. Aces and kings add nothing once total points are known.

**So: a 3.3× headroom, with the entire hand-descriptor family measured to cap out
at about a third of it, and 89% of the variance unexplained by descriptors.**
That is the quantitative case for a learned function over the raw 13-card hand
plus public history.

One important caveat: the bot **under-declares** (21.4% against an optimum near
34%) but loses very little by it, because the gain curve is flat either side of
the threshold. A separate experiment on a different endpoint (signed deal points
per decision rather than equity per deal) found lowering the declaration
threshold worth **+0.307 points per decision**, 95% cluster-bootstrap CI
[0.108, 0.516]. The two studies agree on direction and disagree on significance
because they use different estimands. **Which endpoint is authoritative is an
open question.**

---

# Part 5. The corpus that now exists

A generation pipeline was built and validated. This is the "genuinely new
resource" the cloning programme said to wait for.

## 5.1 What is stored

**Storage principle: store only what replay cannot recompute.** An observation
is a pure function of `(explicit deal, action prefix, seat)` and the engine is
deterministic, so a deal is stored as its four hands (13 bytes: two bits of
owning seat per card index) plus its ordered actions plus its outcome. Every
observation, feature vector and legal action set is *derived* by replaying
through the engine's formal observation projection.

| | |
|---|---:|
| stored bytes per deal | **68** (104-byte fixed row, zstd) |
| Phase 6's approach (one serialised observation per example) | ~110,000 bytes per deal |
| replay throughput | **16,481 decisions/s per core** † |

† All throughput figures in this document were measured on the *development*
machine (Apple M3 Max, CPython 3.14). The target host is a 2015 Skylake part and
is assumed to deliver **0.35–0.50×** per core on this workload, which is
branchy, allocation-heavy, pointer-chasing Python. That assumption has not yet
been checked on the actual box. Halve the numbers when reasoning about the
target host and treat the result as an estimate.

So training tensors are a cache, not the corpus, and re-encoding under a new
representation costs CPU rather than storage. This is a real degree of freedom
for you: **the input representation is not locked in.**

## 5.2 Verified pilot, and the planned corpus

Pilot (already run and gated): 141,601 deals, 5,728 matches, 9.2 MB, in 254.6 s
on 12 cores. Digests verified, one shard rebuilt byte-identically in a fresh
process, 200 deals replayed through the authoritative engine and reproduced their
recorded outcomes exactly.

Planned first tier: **10M deals ≈ 546M decisions ≈ 680 MB**, about 37 hours on
the target machine.

## 5.3 The generating population, and why it is deliberately mixed

Because of §3.4, the mixture is a correctness requirement rather than a
nice-to-have. Drawn per stream, with realised **deal** shares from the pilot:

| Stratum | asked | realised (deals) | What it is |
|---|--:|--:|---|
| reference self-play | 30% | 32.6% | the reference policy in all four seats |
| population crossplay | 20% | 19.0% | mixed policies across seats, from a population of 10 tables |
| **softened reference** | 15% | 16.7% | uniform among the policy's top-3 actions with probability 1/4 — breaks determinism |
| **epsilon branch** | 15% | 15.3% | one uniformly random legal action at a sampled ply, on-policy thereafter |
| **forced-contract pairs** | 10% | 8.4% | same deal played twice, forehand forced to RAMI vs forced to NOLO |
| **forced-play pairs** | 5% | 4.0% | same deal twice, policy's choice vs its runner-up at a sampled ply |
| score-stratified | 5% | 4.2% | self-play from non-zero starting scores |

Held-out streams draw from **reserved policy sets** not used in training, and
splits are by stream, never by row.

**Be careful how much that buys.** Every member of the population is a
rule-based policy from the same ladder, sharing the same scoring framework and
tie-break, and in most cases the same following play. So the reservation gives
**within-family variation, not genuine cross-policy transfer** — the softened
stratum is a perturbation of the reference, not a different player. A real
transfer test needs an opponent family the corpus does not currently contain.

## 5.4 Labels available per decision

All of these are either stored or derivable:

| Label | Notes |
|---|---|
| the reference policy's action | the imitation target. Its ceiling is known — §3.3 |
| **signed deal points for the acting partnership** | the primary target. Dense: one per ~55 decisions |
| team tricks; whether this side took this trick | secondary endpoints |
| match-score delta across the deal; match-terminal flag | for match-context work |
| **true location of every unseen card** | free — the deal is in the record. Belief-model supervision |
| proven voids; "took a trick it could have ducked" | the two observation classes that survive policy uncertainty (§3.4) |
| **paired counterfactual advantage** | forced-branch strata; see §5.5 |
| exact perfect-information optimal values, ≤ 5 tricks remaining | **not yet built.** Cost known: ~6.7 ms/deal. A full 13-trick double-dummy solve is out of reach in pure Python |
| perfect-foresight / oracle branch value | **not yet built.** This is the 100% column of Part 4 |

## 5.5 The counterfactual signal, measured

This matters for your scale calculations.

**Target distribution** (signed deal points, 141,601 deals): mean +0.171,
**sd 13.02**, range ±56. |points| mean 11.41, median 8. Team-0 tricks are
bell-shaped around 6.51.

**Forced-contract pairs** (5,928 complete pairs):

| | |
|---|---:|
| mean delta, RAMI-forced minus NOLO-forced, acting team's signed points | **−3.265** |
| sd | 15.62 |
| pairs where the choice changed the outcome | **85.3%** |
| mean \|delta\| among those | 14.33 |

**Forced-play pairs** (2,138 complete pairs):

| | |
|---|---:|
| mean delta, best minus runner-up | −0.127 |
| sd | 5.31 |
| pairs where the choice changed the outcome | **25.7%** |
| mean \|delta\| among those | 8.55 |

Two things to note. First, contract advantages are a strong, dense signal —
85% informative, and the mean is ~16 standard errors from zero at pilot scale.
Second, **card-play advantages are sparse**: 74% of runner-up substitutions
transpose to the identical outcome, so you need roughly 4 pairs per informative
example. At 10M deals the corpus yields roughly **418,000 contract pairs** and
**151,000 play pairs, of which ~39,000 carry nonzero signal.**

## 5.6 Statistical constraints that are not negotiable

- **Cluster on the deal.** One deal contributes ~55 correlated decisions and four
  non-independent seats sharing exactly 13 tricks. Any interval computed as if
  decisions were independent is too narrow.
- **Always compare arms on identical deals.** The same shipped policy measured
  +0.164 (z = +2.4) on one seed and +0.360 (z = +5.1) on another at 500 deals
  each — that gap is seed variation alone.
- **Contract selection bias is in *who declares*, not in the hands.** Mean HCP
  per seat is exactly 10.00 in every arm and must be (40 points over 4 seats), so
  that diagnostic cannot detect selection at all. A *natural* RAMI declarer
  averages 15.77 HCP. Use forced-contract conditions for unbiased contract
  analysis.
- **Match-level endpoints cannot resolve what matters.** Effects visible at
  z ≈ −9 to +5 on per-deal tricks with a few hundred deals are **invisible** at 32
  match pairs. The Phase 5 negative results establish that those agents did not
  win 32 matches; they do **not** establish that they play worse per decision.
  Re-running those comparisons on a per-deal endpoint is cheap and might reopen
  the whole programme.

---

# Part 6. Compute budget

**Two machines are available.** They have opposite strengths, and which one you
assume changes the answer to question 7 by roughly a factor of seven.

| | **Fedora box** (primary) | **MacBook Pro** (backup) |
|---|---|---|
| CPU | Intel i7-6700K, Skylake 2015 | Apple M3 Max |
| cores | **4 physical / 4 threads** | **14 (10 performance + 4 efficiency)** |
| memory | 48 GB | 36 GB unified |
| GPU | **NVIDIA GTX 1070**, 8 GB dedicated, Pascal / sm_61 | integrated, Metal / MPS only — **no CUDA** |
| wall clock | unlimited | it is somebody's laptop |

**Generation throughput is measured, not assumed, on the Mac**: the pilot ran at
**556 deals/s on 12 worker processes** (46 per worker, so scaling is near-linear
to 12). The Fedora figure is an assumption derived from it — see the † note in
§5.1 — and works out to roughly 74 deals/s at 4 workers.

| | Fedora (assumed) | Mac (measured) |
|---|---:|---:|
| deals/s | ~74 | **556** |
| 10M deals | ~37 h | **~5 h** |

So **the Mac is about 7× the better generation machine and the only CUDA device
is on the slower one.** For a fully supervised programme that is a convenient
split: generate on the Mac, train on the 1070. For anything with an environment
in the training loop it is an awkward one, and worth your explicit attention.

One documented caveat on the Mac, which is why "14 cores" is not the whole
story: the earlier cloning run recorded that **MPS was built into PyTorch but
unavailable**, so that training and inference ran on CPU. Whether that still
holds has not been re-checked. Treat Metal acceleration as unverified rather
than available, and the Mac as a fast **CPU** machine.

No wall-clock limit on the Fedora box.

Relevant constraints:

- **Pascal has no usable fp16**: GP104's half-precision throughput is a small
  fraction of its fp32 throughput, so mixed precision will not help. Plan fp32,
  ~6.5 TFLOPS, 8 GB.
- Recent PyTorch wheels have been dropping Pascal; `sm_61` support must be
  verified before planning around the card.
- **Cores are the real constraint, and they are on the wrong machine.** Data
  generation is pure-Python and CPU-bound; the GPU is idle during it. The machine
  with 14 cores has no CUDA, and the machine with CUDA has 4 cores.
- Replay at 16,481 decisions/s/core (dev machine; assume ~6,000–8,000 on the
  target host) means a couple of loader processes saturate this GPU for any model
  in the 1–20M parameter range. **The input pipeline is not the bottleneck; the
  CPU-side environment is.**
- For reference on the model scale that was tried: 41,900 parameters trained on
  CPU in minutes. A 1–20M parameter model is comfortable on this card. Anything
  requiring large-scale self-play with neural inference in the loop is
  constrained by cores plus the Python engine step, which costs **~0.06 ms per
  decision on the Mac and an assumed ~0.12–0.17 ms on the Fedora box** — before
  any network inference. Playing a full match end to end costs ~1,350 such steps.
  That budget, not the GPU, decides whether any form of self-play is affordable,
  and it is ~7× larger on the machine that cannot run CUDA. If your answer to
  question 7 is "yes, with batched inference", say where the network runs.

---

# Part 7. Hard constraints on any proposal

1. **The observation boundary is inviolable.** A deployed policy may see only
   §2.1. Hidden state may be used for *training-time* supervision (belief targets,
   a centralized critic, oracle labels) but must not be reachable at inference.
   The whole evidence chain of this project rests on this, and it is enforced by
   automated source scans and sentinel tests.
2. **Illegal actions must be impossible, not merely improbable.** The existing
   scorer embeds only actions in the engine's legal tuple. No fallback repair.
3. **Everything must be deterministic and content-addressed.** Same inputs,
   same seed, same bytes. No module-global RNG, no reliance on `hash()`, no
   dependence on worker completion order.
4. **Any candidate is evaluated against the rule-based reference**, initially on
   a per-deal endpoint, and the reference is a *frozen* identity.
5. **Do not propose another unbounded hyperparameter sweep.** The project has an
   explicit rule against it, and against rescue subphases after a gate fires.

---

# Part 8. What we want from you

Please reason about **architecture and programme design**, not code. The
candidate paths we have sketched, for you to challenge, reorder or replace:

- **N1 — belief network.** Public observation → distribution over the location
  of each unseen card. Supervised, labels free and exact, and it attacks the
  mechanism every search family failed on. Must satisfy §3.4's cross-policy
  requirement. An exact per-suit posterior exists as a reference (§1.7).
- **N2 — value network.** Observation → expected signed deal points. Trained on
  terminal returns, with exact endgame values as an auxiliary target. First use:
  replace the hand-written rollout inside the existing search, which is the
  second diagnosed failure mechanism.
- **N3 — policy network on measured advantages** rather than on the bot's
  action. The only supervised path whose optimum is not the generating policy.
- **N4 — showing network.** Full 13-card hand plus public showing history →
  declare-or-pass equity gain. Directly targets Part 4's measured 3.3× headroom
  against a measured descriptor ceiling.

**The questions we most want your judgement on:**

1. **Why did 85% action agreement produce a 1.6% match win rate**, and what does
   that imply about the objective? Is the fix a different target (advantages,
   values), a different training regime (DAgger-style on-policy correction,
   trajectory-level objectives), a different evaluation, or something else?
2. **What is the right decomposition?** One network with heads for
   belief/value/policy, or separate models? Given that showing is 4.7% of
   decisions but carries the measured headroom, does it deserve its own model?
3. **Representation.** The input is a small, exact, fully-observed public history
   plus a 13-card hand, with a ≤ 13-way action choice and 21% of decisions
   forced. Is the DeepSets + GRU + legal-action-scorer shape right, or is there a
   better fit — set transformer over cards, per-suit factorisation exploiting the
   no-trump structure (§1.7), explicit card-location beliefs as input features?
4. **How should the belief model and the decision model relate**, given that a
   finite particle set already failed (ESS 6.47/32) and that exact per-suit
   posteriors are available but a joint cross-suit posterior is not?
5. **Sparse advantage labels.** Card-play counterfactuals are 26% informative.
   Is that a reason to weight the corpus toward contract decisions, to change the
   branch design (more than two arms, deeper branches, resampled continuations),
   or to learn values instead of advantages?
6. **What is the smallest experiment that would falsify the whole approach**, and
   what should its preregistered kill criterion be? This project's convention is
   to write the gate before the measurement, and to stop when it fires.
7. **Is any form of RL / self-play realistic on either machine**, or should the
   programme stay fully supervised on a fixed corpus? The split in §6 is awkward:
   14 CPU cores without CUDA, or 4 cores with an 8 GB Pascal card. If RL, say
   which machine it runs on, where inference happens, and what batching makes it
   affordable against a ~0.06–0.17 ms engine step and ~1,350 steps per match.

Where your answer depends on a fact not in this document, please say which fact
and we will measure it.
