# Phase 7 charter: the Tuppi decision corpus

Status: **draft plan, nothing generated, nothing implemented.** This is the
preregistration-style plan for a large local corpus of machine-played Tuppi, and
for the engine work that makes generating it affordable. It follows the project's
conventions: bulk artifacts live outside Git under
`/Users/pyryouri/Developer/TuppiRuns/`, the sealed promotion bank stays closed,
no policy ever reads hidden state, and every number below is either measured (and
says where) or explicitly marked an assumption.

Target host for generation: Fedora Linux, Intel i7, NVIDIA GTX 1070.

Read `docs/valuation/handoff.md` first if you have not. This plan is written to
serve the open problems it ranks, and several of its findings contradict the
obvious version of this project.

## Decisions taken, 2026-09-08

Three of the six open questions were settled by the corpus owner before any
implementation. They are recorded here because each one is fixed at generation
time and expensive to revisit.

| # | Decision | Consequence |
| --- | --- | --- |
| **D1** | **Balanced purpose.** The corpus serves the learned models and the counterfactual strategy research equally. | The §5.2 mixture stands as written. |
| **D2** | **Forced-branch both thresholds.** Showing decisions are generated under both the current and the candidate RAMI threshold as forced branches. | ~10% more generation cost; the corpus is threshold-agnostic and can settle B2 from its own rows. §6.5 B2 becomes a measurement to run *on* the corpus, not a blocker before it. |
| **D3** | **E1a.** The fast path is a `trusted` transition mode inside the authoritative engine, gated by E1b's differential harness. | No second state machine. The engine gains a path that skips its own invariants, so the differential gate and the in-run revalidation sample are load-bearing, not optional. |
| **D4** | **The reference policy is `partner_aware_lead_v2`**, and both it and `partner_aware_discard_v3` are committed and given content-addressed identities. | B1 unblocked. `discard_v3` is committed and registered but is *not* the reference: it enters the corpus through the population stratum, so the corpus can later settle whether it should be promoted. See §6.5 B1. |
| **D5** | **10M deals, and the regeneration recipe is a first-class artifact.** T4 (100M) is dropped rather than deferred. | §7.2's T1-T3 stand; T4 is removed. The recipe - manifest, seeds, code identity, and a one-command rebuild - is specified as a deliverable in its own right (§4.2). |
| **D6** | **Two hosts**: the Fedora box (Intel i7-6700K, **4 cores / 8 threads**, **31.3 GB**, Fedora 44, CPython 3.14.7, GTX 1070, no wall-clock limit) is primary; an **M3 Max MacBook Pro (14 cores, 36 GB, no CUDA) is available as a backup**. Measured on 2026-09-08 by `work/phase7_planning/calibrate.py`; hyper-threading is **on** and memory is 31.3 GB, both differing from what was reported when D6 was taken. | §7.1 now gives both. The Mac is a measured ~7x faster generator and the only CUDA device is on the slower box, so the natural split is **generate on the Mac, train on the 1070** - which also drops T1 from ~37 h to ~5 h and makes P5 an optimisation rather than a gate. |

| **D7** | **The external review's argument is adopted.** The first programme is a tightly scoped **showing intervention** measured against an executable continuation - not a belief network, not a value network, and not a larger imitation corpus. **T1 is deferred.** | This supersedes the §8 ordering of P6 and P9-P12 and the §2 ordering of N1-N4. See `work/phase7_planning/nn_architecture_review.md` for the argument, `..._review_checks.md` for what was verified, and `docs/showing/` for the programme that replaces them. The corpus layer, the trusted mode and the identities all stand; what changes is that the corpus is now generated **to order for a specific experiment** rather than in bulk first. |

Still open: reference-policy *content* boundaries where `discard_v3` overlaps
`lead_v2` (§6.5 B1), and whether hyper-threading should be enabled (§7.1).

## Superseded by D7

§2's N1-N4 ordering and §8's P6/P9-P12 are **no longer the plan**. They are kept
because the reasoning that produced them is still the reasoning the review had to
argue against, and because the corpus tiers remain the right shape *if* the
showing programme passes its gate. Three specific points the review carried:

1. **Part 4's 3.3x figure is a perfect-foresight bound, not a learnable
   ceiling.** An oracle that sees the hidden layout can pick profitable
   overrides that no observation-only learner should ever pick. The
   observation-compatible headroom could be far smaller, or zero, and §1.7 did
   not distinguish them. Measuring that difference is now the first experiment.
2. **A belief network does not repair strategy fusion**, and a value network
   trained under reference continuation estimates *reference-continuation*
   value - which is not what it would be asked to predict once both partners act
   differently. Neither belongs first.
3. **The primary endpoint is per-deal frozen-continuation match equity**, which
   already exists as `src/tuppi_valuation/equity.py`. Signed deal points are a
   surrogate: at 48-0 a larger winning margin is worth nothing, so pricing it is
   explicitly wrong.

---

## 1. What was measured before writing this

§1.1-1.5 were measured on 2026-09-08 on the development Mac (Apple M3 Max,
CPython 3.14.2, one core, `partner_aware_v1` in all four seats, `MatchStream`
deals, matches from 0-0 to natural termination). The scripts are in
`work/phase7_planning/`. §1.6-1.7 are prior results from the repository.

### 1.1 Generation is dominated by defensive revalidation, not by the bot

| Component (cProfile, cumulative) | Share of runtime |
| --- | ---: |
| `tuppi_engine.match._validate_match_state` | **81%** |
| `tuppi_agents.protocol.choose_action` (the actual policy) | **6.4%** |
| everything else (transitions, event building, observation projection) | ~13% |

`_validate_match_state` runs about **three times per action**: once inside
`apply_match_action`, once in `MatchState.__post_init__` when the successor is
constructed, and once inside `match_observation_for`. Each run revalidates the
*entire* match history, including every completed deal's event log.

### 1.2 That revalidation is quadratic in match length

Per-action cost inside one match, authoritative engine:

| Deal number | 1 | 6 | 12 | 17 | 22 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ms per action | 1.55 | 1.75 | 1.90 | 2.05 | 2.14 |

A 38% per-action slowdown over 22 deals, growing with history length. Match
length is heavy-tailed (§1.4), so the tail is where the cost concentrates.

### 1.3 Eliding revalidation is a measured 12.4x, with byte-identical play

Neutralising `_validate_match_state` and `_validate_deal_state` and replaying six
complete matches:

| Path | Throughput | Play |
| --- | ---: | --- |
| authoritative engine | 278 actions/s | reference |
| revalidation elided | **3 466 actions/s** | **identical** |

"Identical" means all 11 615 recorded checkpoints matched exactly: every
`(stream, actor, serialised action)` triple in order, plus each match's final
score and deal count. Confirmed at scale over 200 matches: 3 450 actions/s, i.e.
**63 deals/s per core**.

This is not a new technique here. Phase 5D-C already introduced
`tuppi_search.fast_trick.FastTrickState`, "a search-local immutable trick-play
state and formal observation projection that omit engine event-log construction
and repeated full-state validation", with the authoritative engine kept as the
differential reference. Phase 7 needs the same thing one level up, covering
showing as well as trick play.

**Shipped result (E1a, `tuppi_engine.trusted`).** The implemented mode keeps
deal-boundary validation, so it buys slightly less than the measurement device
above, and it was measured with the *reference* policy rather than
`partner_aware_v1`:

| Path | actions/s | deals/s | Play |
| --- | ---: | ---: | --- |
| authoritative, `partner_aware_lead_v2` | 233 | 4.3 | reference |
| trusted, `partner_aware_lead_v2` | **2 588** | **47.3** | **identical** over 13 179 checkpoints |

Two corrections to the numbers above follow from that second row and are carried
through §7:

- the **reference policy is more expensive than `partner_aware_v1`** - 47.3
  against 63 deals/s per core, about 0.75x - because its lead rules evaluate
  exact suit maths. Throughput must be sized from 47.3, not 63;
- the shipped speedup is **11.1x, not 12.4x**. The difference is the retained
  deal-boundary validation, which is the safety property, not overhead to
  remove.

**Where the time goes once revalidation is gone** (cProfile of the trusted path,
reference policy):

| Component | Share of trusted runtime |
| --- | ---: |
| the policy itself (`choose_action`) | **62%** |
| of which `public_inference.build` | 27% |
| deal-boundary revalidation still performed | **~35%** |

That reorders §6: **E2 is worth ~35% of the trusted path, not merely tidiness**,
because `_validate_match_state` rebuilds the whole match history at each deal
boundary and the history grows. E3 is worth ~27%.

### 1.4 The unit of account is the deal, not the match

200 matches, `partner_aware_v1` self-play from 0-0, natural termination:

| deals per match | mean | median | p90 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| | 33.1 | 22 | 73 | 156 | 245 |

Actions per deal is by contrast almost constant at **54.7** (4-13 show actions
plus 52 cards). Two consequences:

- **Size, cost, and sampling are denominated in deals.** Match count varies by
  more than an order of magnitude.
- **Terminal match win/loss is a very weak signal.** A mean 33-deal match credits
  one bit to ~1 810 actions. Phase 6 used terminal match win/loss as its
  authoritative objective over 20 769 training examples - roughly eleven matches'
  worth of outcome information. `docs/valuation/handoff.md` §1.6 reaches the same
  conclusion from the other direction: effects showing z = -9 to +5 on per-deal
  tricks with a few hundred deals are **invisible** at 32 match pairs, so Phase
  5's negative results establish that those agents did not win 32 matches, not
  that they play worse per decision.

The primary utility in Phase 7 is therefore **signed deal points for the acting
partnership**, with per-deal tricks and equity as secondary endpoints. That is
also what the RAMI/NOLO threshold experiment and the valuation work both chose.

### 1.5 Exact endgame labels are cheap

From `docs/exact/solver.md`, measured on the same machine: `solve_late_game`
costs 0.03/0.05/0.18/0.86/5.6 ms at 1/2/3/4/5 tricks remaining. Solving once at
each trick boundary with five or fewer tricks left costs about **6.7 ms per
deal**, against roughly 16 ms per deal for fast-path generation - a ~40%
surcharge for an exact value at every one of those nodes. A full 13-trick
double-dummy solve remains out of scope in pure Python.

### 1.6 The current best agent, accurately

The Phase 4 registry's top rung is `partner_aware_v1`, and every principled
method built on top of it has lost to it: PIMC `p(win) = 0.156`,
root-information UCT lost all 32 pairs, multi-observer ISMCTS `p(win) = 0.125`,
Phase 6's behaviour clone `p(win) = 0.0156`. Rung 5 `match_aware_v1` is *not* an
improvement - action-identical at 0-0, measurably worse from 48-0, and its
score-aware adaptation is worth **exactly zero equity** (`handoff.md` §3.5).

But the working tree has moved past that, in **uncommitted** work:

| Policy | Change | Measured | Registered? |
| --- | --- | ---: | --- |
| `partner_aware_lead_v2` (`src/tuppi_agents/void_lead.py`) | NOLO: lead the shortest suit, lowest within it | **-0.69 tricks, +13.9 pp** | no - reports `partner_aware_lead_v2:<base agent_id>` |
| same | RAMI: lead the suit worth the most tricks played out | **+0.36 tricks, +8.2 pp** | no |
| `partner_aware_discard_v3` (`src/tuppi_agents/nolo_discard.py`) | NOLO discards priced by the exact ducking law | **-0.338 tricks/deal**, `[-0.392, -0.284]`, z = -12.51 | no, and not shipped |

Both lead changes are *dominant* (still ahead when the opponents adopt them:
+12.2 pp and +5.0 pp), as is the discard rule (-0.296 tricks). `lead_v2` is
already the live AI and the analysis reference. Neither is a registered Phase 4
profile, deliberately: registering one would retroactively change the frozen
baseline that every earlier result is quoted against.

**So the "top AI" is currently a stack of three uncommitted policies with no
committed agent identity.** That is the single largest operational risk in this
plan, and §8's first work package addresses it: a corpus generated by a policy
that cannot be named cannot be cited, compared against, or regenerated.

### 1.7 There is measured headroom, and measured evidence that hand descriptors cannot reach it

From `docs/valuation/rami_declaration.md`, on the one non-card-play decision in
the game, held-out half of 4 000 deals:

| Policy | Equity per deal | Share of ceiling |
| --- | ---: | ---: |
| always pass | +0.00000 | 0% |
| `partner_aware_v1` | +0.00652 | **30.6%** |
| best hand-descriptor rule (`HCP - 0.5 x low >= 10`) | +0.00718 | **33.8%** |
| perfect foresight | +0.02126 | 100% |

The full eight-descriptor regression explains **R² = 0.106** of the variance in
the gain. The document's own conclusion: "Whether declaring RAMI is right is
mostly determined by things a point count cannot see - how the suits actually
lie."

That is the strongest argument in this repository for a learned function, and it
is quantitative: a 3.3x headroom, with the entire hand-descriptor family
measured to cap out at roughly a third of it. `handoff.md` §1 makes the
methodological version of the same point - "the A/B template has a ceiling ... it
can only find the best member of a family someone thought of in advance", with
two of three refinements measuring zero or negative.

### 1.8 What the T0 pilot established, including four defects

The pilot ran on the development Mac, 5 000 streams over 20 shards, 12 workers:

| | Measured |
| --- | ---: |
| deals | 141 601 (5 728 matches, 24.7 per match) |
| wall time | 254.6 s -> **556 deals/s on 12 workers** (46 per worker) |
| on disk | 9.2 MB -> **68 bytes per deal**, so 10M deals is ~680 MB |
| RAMI share | 0.781 (Phase 5F independently reported 0.784) |
| replay | **16 481 decisions/s per core** |
| gate | 20 shards agreed; one rebuilt to its exact digest in a fresh process; 200 deals replayed through the authoritative engine and agreed |

Realised deal shares now track the requested stream weights to within about two
points (30 -> 32.6, 20 -> 19.0, 15 -> 16.7, 15 -> 15.3, 10 -> 8.4, 5 -> 4.0,
5 -> 4.2).

**The pilot's value was the four defects it found**, none of which any amount of
reading would have caught:

1. **Hand order is behaviourally material.** Packed hands are sets per seat, and
   the dealt order changed the selected action in 3 of 12 measured deals - it
   reaches `legal_actions`, and some tie-breaks resolve on the lowest legal
   index. Storing packed hands would have made the corpus **silently
   unreplayable**. Generation now canonicalises the deal before playing it.
2. **The deal cap was a loop condition**, so the last dealt deal was discarded
   unplayed - and at a cap of one, which the paired strata used, nothing was
   played at all.
3. **The epsilon branch drew its target deal from the safety cap** (64) against a
   median match length of 22, so it never fired in 51% of its streams: half that
   stratum was silently ordinary on-policy play.
4. **The forced-branch strata were 25% of matches but 1.2% of deals**, because a
   pair is one deal while every other stratum contributes ~22. The corpus's most
   valuable label was 1% of it. A paired stream now contributes twelve
   independent pairs, which brings the deal share into line and yields ~840 000
   forced-contract pairs at T1 scale - T3's target as a by-product.

A fifth was caught by the engine rather than the pilot: half the first
stratified score schedule was **unconstructible**, because only one team may hold
a positive rising score. `create_match` rejected it, which it could only do
because the trusted mode deliberately does not elide entry validation.

The general lesson is the one the mixture table now encodes: **the mixture is
drawn per stream, but the corpus's value is per deal**, and a stratum whose unit
differs from the others will silently misweight itself.

---

## 2. The critical objection, and the reframing

The proposal as stated is "a very large database of games played by the top AI,
one use of which is a neural network". Taken literally that is Phase 6 with a
bigger `N`, and it has a ceiling more data cannot raise:

1. **Imitation cannot exceed its target.** A corpus of the reference policy's own
   chosen actions defines a supervised problem whose optimum *is* that policy.
   Phase 6's closeout says continue "only if a genuinely new resource is
   available". More rows of the same policy's decisions is the same resource at
   higher resolution.
2. **A deterministic policy generates almost no state diversity.** Four identical
   deterministic agents plus an explicit deal plus a starting score determine the
   whole match. `N` deals give exactly `N` trajectories, all on-policy, in a
   narrow tube - no counterfactuals, no exploration, no coverage of positions a
   stronger player reaches.
3. **Worse, a corpus from a deterministic policy poisons inference.**
   `handoff.md` §3.1 is the most important methodological finding in the project:
   assuming opponents duck their lowest makes a played card look highly
   informative, but drop the policy assumption and read it as `min <= c` and the
   **signal retained is 1-5%** for exactly the high-card observations that looked
   most informative. "That table was measuring the bot's determinism." §3.2 adds
   the mechanism: `partner_aware_v1` leads its lowest card **100%** of the time,
   and the project owner has confirmed real players do not.
4. **The generating policy is in flux and partly unvalidated.** Three
   improvements are uncommitted (§1.6), the showing threshold is contested (§6.5),
   and zero of the 38 catalogued strategy rules carry `expert_validated` or
   `simulation_validated` provenance.

What *is* a genuinely new resource, and is available offline at scale:

| Resource | Why it beats action labels | Source |
| --- | --- | --- |
| **Measured counterfactual advantages** | Paired forced-branch outcomes give the value *difference* between two actions from one state. A model trained on these can exceed the generating policy, because the target is an outcome, not a choice. | The threshold experiment's and the valuation work's design, generalised. |
| **Perfect-foresight / oracle branch labels** | "Which contract was actually better on this deal" defines the 100% column of §1.7 and makes the residual an explicit regression target. | Play out both branches; already done at 4 000-deal scale. |
| **Exact endgame values** | Perfect-information optimal values, stronger than any bot, at every node with <=5 tricks left. | `tuppi_exact.solver`, ~6.7 ms/deal. |
| **Exact single-suit posteriors** | `tuppi_valuation.suits.layouts()` enumerates every layout of a suit's outstanding cards with its true probability - an exact reference to check a learned belief model against. | Ranked first among open problems in `handoff.md` §1.1. |
| **Ground-truth hidden hands** | Supervised targets for a belief model - *subject to §5.1*, which is not optional. | Free; the deal is in the record. |
| **Terminal deal points** | A dense scalar return every ~55 decisions instead of one bit every ~1 810. | Free; the deal result. |

**Reframing: build a decision corpus with outcomes and counterfactuals, not a
game log.** Store games as the minimal replayable substrate; make decisions,
outcomes, hidden truth, and exact labels the first-class rows. The bot's chosen
action becomes one column among several labels - useful as a baseline and a warm
start, and no longer the objective.

The neural-network programme that follows, in dependency order:

- **N1 - belief network.** Public observation -> distribution over the location of
  each unseen card. Attacks the mechanism every Phase 5 search failed on. Labels
  are free and exact, and `suits.layouts()` provides an independent per-suit
  reference. **Only valid under §5.1.**
- **N2 - value network.** Observation -> expected signed deal points, trained on
  terminal returns, with exact endgame values as an auxiliary target and an
  independent accuracy test. First use: replace the `partner_aware_v1` rollout
  inside existing search, which is the second named Phase 5 failure mechanism.
- **N3 - policy network on advantages.** Trained on measured counterfactual
  deltas, not on the bot's action. The only supervised path here whose optimum is
  not the generating policy.
- **N4 - showing network.** Directly targets the §1.7 residual: full 13-card hand
  plus public showing history -> declare-or-pass equity gain. The measured
  headroom is 3.3x and the descriptor family is measured to cap at ~34%, so this
  is the cheapest well-posed test of "can a learned function see what a point
  count cannot".
- **N0 - behaviour clone.** Kept, demoted to a cheap sanity baseline and warm
  start. Its expected result at 100x the data is a better clone.

---

## 3. What the corpus stores

### 3.1 The compactness principle

An observation is a pure function of `(explicit deal, action prefix, seat)`. The
engine is deterministic, and `tests/agents/test_conformance.py` already proves a
selected action does not depend on `match_ref`, output paths, or observation
construction count. Therefore **store nothing replay can recompute.**

That decision is worth three orders of magnitude:

| Format | Bytes per deal | 10M deals |
| --- | ---: | ---: |
| Phase 6 style: one serialised observation per example, JSONL | ~110 000 | ~1.1 TB |
| Phase 7: packed deal + action sequence + outcomes | ~70 | **~0.7 GB** |

The Phase 6 corpus is 72 MB for 35 406 examples, i.e. ~2 KB each, which is where
the first row comes from.

The corpus is consequently a *cache of a pure function*. Any shard must be
regenerable byte-for-byte from `(root seed, stream range, code identity)`, so
disk is not a commitment and a superseded shard can simply be rebuilt.

### 3.2 Entities

Eight tables. `deal` and `belief_target` contain hidden state and are
research-private; the rest are public-derivable.

**`generation_run`** - one row per run, content-addressed like every other
identity here: `run_id`, `schema_version`, `root_seed`, `ruleset_id`,
`engine_identity`, `source_manifest` (sha256 per source file, as
`docs/nolo/tasks/source_manifest.json` already does), `fast_path_id` plus its
differential-gate evidence digest, seat policy schedule, score schedule, dealer
schedule, stratum mixture weights, exploration parameters, exact-label budget,
stream ranges, host/OS/CPython versions, timestamps, shard catalogue digest.

**`match`** - `match_id`, `run_id`, `stream_id`, `stream_index`, `initial_score`,
`initial_dealer`, `deals_played`, `final_score`, `winner_team`, `termination`
(natural / safety-cap), `pair_id` (set when this is one leg of a complementary
pair), `split` (train / validation / heldout, assigned **by stream**, never by
row - the Phase 6 discipline), `policy_population_id`.

**`deal`** *(research-private)* - `deal_id` (the existing content digest over the
four ordered hands), `match_id`, `deal_number`, `dealer`, `forehand`,
`starting_score`, `hands_packed` (13 bytes, two bits of owning seat per card),
`actions_packed` (~40 bytes, 6 bits per card play, 7 bits per show action),
`contract`, `declarer`, `verbal_required`, `contract_condition`
(natural / forced-RAMI / forced-NOLO), `first_leader`, `team_tricks`,
`deal_points`, `score_after`, `reset`, `terminal`, `trick_winners` (13 x 2 bits,
redundant but free and a useful replay checksum).

**`decision`** - derived, materialised only for subsets actually trained on or
analysed (§3.4). One row per action: `deal_id`, `ply`, `seat`, `phase`,
`tricks_remaining`, `legal_action_count`, `chosen_action`, `policy_id` (which
policy occupied that seat, at the granularity of §1.6's stack),
`provenance` (`on_policy` / `forced_branch` / `epsilon_random` /
`policy_mixture`), and the label block:

| Label | Meaning |
| --- | --- |
| `label_action` | what the reference policy would play here - for N0 only |
| `return_deal_points` | signed final deal points for the acting partnership - the primary target |
| `return_tricks` | team tricks in this deal; and whether this side took this trick |
| `return_equity` | equity-table valuation of `score_after`, for match-context work |
| `return_match_delta` | change in match score across the deal, plus match-terminal flag |
| `exact_value` | perfect-information optimal signed points when `tricks_remaining <= 5` |
| `exact_action_values` | per-legal-action exact values at the same node |
| `advantage_pair_id` | link into `counterfactual_pair` when this node was branched |
| `source_deal_cluster_id` | the bootstrap cluster (`handoff.md` §3.3) |

**`counterfactual_pair`** - `pair_id`, `deal_id`, `ply`, `seat`,
`forced_action_a`, `forced_action_b`, `continuation_policy_id`, `utility_a`,
`utility_b`, `delta`, `source_deal_cluster_id`, `arm_layout`. The last column
records which of the four `bb`/`cb`/`bc`/`cc` arms this leg is, because the
valuation work established that a *dominance* endpoint (both sides change) is a
separate and necessary reading from the primary one.

**`oracle_label`** - per deal and decision point: the perfect-foresight best
branch and its value. This is the 100% column of §1.7 and is what makes the
"share of ceiling" metric computable for any candidate.

**`belief_target`** *(research-private, train-only)* - `deal_id`, `ply`, `seat`,
and for each card unseen by that seat the true owning seat, plus the two
observation classes §5.1 says survive policy uncertainty: proven voids, and
"took a trick it could have ducked".

**`exact_label`** - `position_digest`, `deal_id`, `ply`, `solver_identity`,
`budget`, `tricks_remaining`, `optimal_value`, per-action values, node count,
solve time. Keyed by position digest so it dedupes across deals that transpose
into the same endgame.

### 3.3 What the corpus deliberately does *not* store

Legal action sets, observations, feature vectors, encoder tensors,
rule-citation diagnostics, public event logs, inferred void flags. Each is a pure
function of `deal` plus prefix, and storing any of them makes the corpus depend
on the code version that wrote it rather than the one that reads it.

### 3.4 Derived, versioned materialisations

Training tensors are a *cache*, not the corpus: `derived/<encoder_id>/…` holding
memory-mapped `uint8`/`int8` arrays plus an index, with `encoder_id` naming the
encoder version (today `seat_relative_observation_encoder_v2`). Regenerating a
materialisation must be one command; deleting one must lose nothing.

Replay throughput makes this viable: one deal replays in ~16 ms on the fast path
and yields ~55 examples, i.e. ~3 400 examples/s per core, so eight loader
processes sustain roughly 27 000 examples/s - far more than a GTX 1070 needs at
this model scale.

---

## 4. Infrastructure

**Recommendation: Parquet shards on a plain local filesystem, queried with
DuckDB. No database server.**

```text
/var/lib/tuppi-corpus/                       (Fedora; ~/Developer/TuppiRuns/phase7 on the Mac)
  catalog.json                               run ids -> shard digests, append-only
  runs/<run_id>/
    manifest.json                            the generation_run row, content-addressed
    matches/part-<stream_lo>-<stream_hi>.parquet
    deals/part-….parquet                     research-private
    exact/part-….parquet
    pairs/part-….parquet
    oracle/part-….parquet
  derived/<encoder_id>/{train,validation,heldout}.{bin,idx}
```

Why this shape:

- **Parquet + zstd** is columnar, so a query wanting only `contract`,
  `deal_points`, and `starting_score` reads three columns instead of every deal.
  Packed-binary columns keep hands and action sequences opaque and small.
- **DuckDB** reads Parquet in place: no server, no daemon on the generation host,
  no migration story, and it handles hundreds of millions of rows on one box.
  "All veto-passing showing decisions with RAMI score in [12, 13] from held-out
  streams, clustered by source deal" becomes one SQL statement - exactly the query
  the threshold experiment and the valuation work each hand-rolled.
- **Not JSONL** - §3.1, a ~1 700x size penalty, and slow to scan.
- **Not PostgreSQL** - a server, migrations, and tuning in exchange for nothing
  this workload needs. Reconsider only if multiple hosts or concurrent writers
  appear.
- **Shard = stream range**, one writer per worker, no coordination. A worker
  writes its shard, fsyncs, then appends `(path, sha256, row count)` to the
  catalogue. A crash leaves an uncatalogued shard, which is discarded and
  regenerated. Runs are resumable at shard granularity and every shard is
  independently citable.
- **Identity discipline** follows the repository: content-addressed run manifest,
  sha256 per shard, and any training or analysis run cites the exact shard digest
  set it consumed - as Phase 6 cites `dataset:sha256:7c30cf5a…`.

### 4.2 The recipe is a deliverable, not a side effect (D5)

Because there is no 100M tier, the thing that makes a larger corpus a scheduling
question rather than a research one is the **regeneration recipe**. It is a
deliverable in its own right and must satisfy four properties:

1. **One command rebuilds any shard.** `tuppi-corpus generate --run <manifest>
   --streams <lo>:<hi>` reproduces that shard byte-for-byte, on any host, with no
   reference to the original run's output.
2. **The manifest is self-contained and content-addressed.** Root seed, stream
   ranges, stratum mixture and its parameters, seat policy identities, score and
   dealer schedules, exact-label budget, engine identity, and a sha256 per source
   file that can affect play. The `run_id` is the digest of that object.
3. **Regeneration is verified, not asserted.** The T0 gate regenerates a randomly
   chosen shard in a separate process and requires digest equality. The same check
   runs on one shard of every subsequent run.
4. **Code drift is detected, not silently absorbed.** If any pinned source digest
   has changed, regeneration *fails* rather than producing a differently-generated
   shard under the same `run_id` - the discipline
   `docs/nolo/tasks/source_manifest.json` and `test_input_provenance` already
   apply to the NOLO evidence packet.

The practical consequence: the corpus on disk is disposable, and a decision to
grow it to 100M deals later costs scheduling time and nothing else.

### 4.1 The privacy boundary is the main structural risk

`deal`, `oracle_label`, and `belief_target` hold hidden state or its
consequences. The repository's central invariant is that a policy sees only a
formal `PlayerObservation`, and the whole Phase 4/5 evidence chain rests on it. A
training pipeline that read `deal` directly to build features would break it
silently, and nothing in the existing suite watches a corpus.

Required mitigations, in the style the repo already uses:

- Feature materialisation goes through `match_observation_for` /
  `encode_observation` only. There is no other supported path from `deal` to a
  model input.
- A test that plants sentinel cards in the three non-acting hands and fails if any
  appears in a materialised feature tensor - mirroring the existing diagnostics
  sentinel tests.
- `belief_target` and `oracle_label` are readable by training code only, and no
  deployment path may import them - the same one-way containment check
  `tuppi_exact.integrity` and `tuppi_search.validation` already perform by source
  scan.
- The corpus directory is research-private, never Git-tracked, and never placed
  under iCloud (the README already warns about the synced tree).

---

## 5. Diversity is a correctness requirement, not a nice-to-have

### 5.1 The hard constraint on N1

`handoff.md` §3.1-3.2 means a belief model trained on a deterministic-policy
corpus **learns to invert that policy**, not to infer cards, and will not
transfer to a human or to a different bot. This is not a quality concern; it
invalidates the result. Three requirements follow, and N1 must not be attempted
without them:

1. **The generating population must be stochastic and heterogeneous.** Mixed
   profiles across seats, plus a randomisation temperature over near-equal
   scored actions, so lead rank and duck choice are not constants.
2. **Held-out evaluation must be cross-policy.** Train on population A, evaluate
   on population B. A within-policy held-out score measures policy inversion and
   must not be reported as inference accuracy.
3. **Prefer the observation classes that survive.** Proven voids (~30% of
   follower plays generate one) and "took a trick it could have ducked" (fires on
   ~45% of NOLO follower choices) are robust under rationality rather than under
   policy. Which low card someone ducks with is policy noise. Both robust classes
   are materialised in `belief_target` for exactly this reason.

### 5.2 Proposed mixture, by deal count

| Share | Stratum | What it buys |
| ---: | --- | --- |
| 30% | reference self-play, the §1.6 stack in all four seats, from 0-0 | the canonical on-policy distribution; comparable with existing results |
| 20% | population crossplay over the registered profiles, the §1.6 stack, and protocol controls | off-policy coverage, heterogeneous partners, opponent-model data |
| 15% | softened reference: randomisation over near-equal scored actions | breaks the determinism that §5.1 forbids, at a known and bounded strength cost |
| 15% | epsilon-branch: one uniformly random legal action at a sampled ply, on-policy after | states a stronger player reaches; one-step counterfactual coverage |
| 10% | forced-contract pairs at showing decisions, both contracts from the identical state | contract advantages free of the selection bias of `handoff.md` §3.4, where a natural RAMI declarer averages 15.77 HCP |
| 5% | forced-branch pairs at trick-play decisions | measured card-play advantages - the scarcest and most valuable label |
| 5% | score-stratified: extreme, near-target, and asymmetric starting scores | the region where `match_aware_v1` measured *worse*, under-sampled from 0-0 |

Two requirements carried over from existing practice, both free at generation
time and impossible to add afterwards:

- **Complementary pairing and four-arm layouts.** Store `pair_id` and
  `arm_layout`. The same shipped policy measured +0.164 (z = +2.4) on one seed
  and +0.360 (z = +5.1) on another at 500 deals each - seed variation alone - so
  arms must be compared on *identical* deals, and the dominance arm (`cc - bc`)
  is a separate necessary reading from the primary one.
- **Clustering by source deal.** `source_deal_cluster_id` on every decision and
  pair. One deal contributes ~55 correlated decisions and four non-independent
  seats sharing exactly 13 tricks; any interval computed as if decisions were
  independent will be too narrow.

---

## 6. Engine and bot work, ordered by measured payoff

Each item carries the gate this repository normally requires: freeze source
hashes and canonical outputs from the pre-change tree, measure paired and
alternating with at least five repetitions, and treat a correctness mismatch as a
failure even if the timing gate passes (`docs/engine/efficiency_plan.md`).

### E1 - Trusted generation transition path *(measured 12.4x, byte-identical)*

Validate at deal boundaries instead of three times per action. Two options:

- **E1a**: a `trusted=True` transition mode in `tuppi_engine` that skips
  `validate_match_state` in `apply_match_action` and `match_observation_for` and
  suppresses `__post_init__` revalidation on internally-constructed successors.
  Smaller, one implementation, but the authoritative engine gains a path that
  skips its own invariants.
- **E1b**: a generation-local state modelled on `fast_trick.FastTrickState`,
  extended to cover showing. Leaves the authoritative engine untouched and has an
  accepted precedent, at the cost of a second implementation of the state machine.

**Decided (D3): E1a, with E1b's differential harness.** The 12.4x is already
achieved without removing event construction, and a second state machine is a
correctness liability. Because the authoritative engine will contain a path that
skips its own invariants, two safeguards are mandatory rather than advisory: the
differential gate below, and a configurable sample of deals inside every real
run that is re-validated through the untrusted path and must agree exactly.
Gate: every action, score, and deal count identical over a fixed
stream set, plus periodic full authoritative revalidation on a configurable
sample of deals inside the real run.

E1 also speeds up every existing evaluation and search run, which all pay the
same tax.

### E2 - Incremental history validation *(fixes the quadratic term)*

Independently of E1, `_validate_match_state` revalidates all completed deals on
every call. Validating only the delta since the last validated state removes the
1.55 -> 2.14 ms/action growth of §1.2 while keeping full coverage of everything
new. This one belongs in the authoritative engine and in the INF series, not just
in generation.

### E3 - Incremental public inference *(the top cost once E1 lands)*

With revalidation gone, `tuppi_agents.public_inference.build` becomes the largest
single cost - about 36% of the remaining path, rebuilt from scratch once per
decision and scanning the whole deal history each time. Maintain it incrementally
per deal. Constraint: `PublicInference` is part of a frozen Phase 4 agent, so the
optimisation must be **exactly** output-identical or it mints a new agent
identity and breaks comparability with every prior result. Differential-test over
the full decision corpus, not a sample.

### E4 - Card representation

The elided-path profile shows 6.5M frozen-dataclass `__hash__` calls and 2.4M
`enum` property lookups per 11 615 actions. Precomputed integer tables for suit,
rank, and ordering would cut this. Lower payoff than E1-E3 and a wide blast
radius across `tuppi_rules`; defer until E1-E3 are measured.

### E5 - Runtime choice

The generator has **no C dependencies** (`numpy` and `torch` are needed only for
training, in a separate process), so PyPy is legitimate for this workload and is
typically worth 3-10x on code shaped like this. Pure measurement question,
resolvable in an afternoon: run the E1 gate under PyPy 3.11 and compare
throughput and byte-identity. If it works it is the cheapest remaining
multiplier by a wide margin. A C or Rust extension for the transition core is
**not** recommended: it would be a second authoritative implementation of the
rules, which this project has consistently refused.

### 6.5 The bot: quality first, and settle it before generating

The bot is 6.4% of the authoritative cost and ~40% of the fast-path cost, so
weakening it buys at most ~1.7x and costs the corpus its only claim to quality.
Do not do it. The quality work runs the other way, and it must precede the large
run because the generating policy is baked into every row:

- **B1 - pin and commit the reference stack. Decided (D4).**
  `partner_aware_lead_v2` is the corpus reference policy;
  `partner_aware_discard_v3` is committed and registered alongside it but enters
  only through the population stratum, so the corpus can measure whether it should
  be promoted rather than presupposing it. Both modules are self-contained within
  `tuppi_agents` - their mentions of `tuppi_valuation` and `tuppi_exact` are prose
  documenting a deliberate code duplication that avoids the dependency - so
  committing them drags in no other untracked package, and it repairs the tracked
  files in `tuppi_server`, `tuppi_nolo`, `tests/` and `tools/` that already import
  them.

  The real work is **identity**. Both modules currently derive an id by prefixing
  the base profile's: `partner_aware_lead_v2:agent:sha256:d8b4…`. That names the
  base profile, not the improved policy's own behavioural content, so changing a
  lead rule would leave the id unchanged. The corpus needs a content-addressed
  `agent:sha256:…` over the improved policy's *own* behaviour, minted without
  touching `STRATEGIC_PROFILE_KEYS` or any frozen Phase 4 identity.
- **B2 - the showing threshold is deferred into the corpus (D2).** Showing
  decisions are generated as forced branches under both thresholds, so the corpus
  answers the question instead of presupposing it, and no generation is wasted if
  the answer changes. The disagreement being deferred: two analyses agree the bot
  under-declares and disagree on significance.
  `TuppiRuns/rami-nolo-threshold` finds `simple_rami_threshold` 15.0 -> 12.5
  worth **+0.307 signed deal points per decision**, CI [0.108, 0.516] over 4 096
  held-out decisions; `docs/valuation/rami_declaration.md` finds the best
  two-term descriptor rule beats the bot by **+0.00066 ± 0.00048, z = +1.37 -
  not significant** on an equity-per-deal endpoint over 4 000 deals. They are
  different scales and different endpoints, so the disagreement is about the
  estimand, not the data - which is exactly why a forced-branch corpus can settle
  it and a single-threshold corpus cannot. The endpoint question (signed deal
  points per decision vs. equity per deal) still has to be answered before the
  result is read, but it no longer blocks generation.
- **B3 - do not promote `match_aware_v1`.** Action-identical at 0-0, worse from
  48-0, and its score adaptation is worth exactly zero equity.
- **B4 - hedge the residual.** `policy_id` on every decision, plus the population,
  softened, and forced-branch strata, so a later change of reference invalidates
  only the on-policy stratum's *canonicality*, not the corpus's validity.

---

## 7. The Fedora run

### 7.1 Throughput and calendar

Two hosts are available (D6), with opposite strengths:

| | **Fedora box** (primary) | **MacBook Pro** (backup) |
| --- | --- | --- |
| CPU | Intel i7-6700K, Skylake 2015 | Apple M3 Max |
| cores | **4 physical / 8 threads** (HT on) | 14 (10 performance + 4 efficiency) |
| memory | **31.3 GB** | 36 GB unified |
| OS / Python | Fedora 44, CPython 3.14.7 | macOS 26.6, CPython 3.14.2 |
| GPU | **GTX 1070**, 8 GB, sm_61 | Metal / MPS only, **no CUDA** |
| wall clock | unlimited | it is somebody's laptop |

**Both hosts are now measured** (`work/phase7_planning/calibrate.py`, 2026-09-08).
The assumption band this section used to carry is gone.

| | Fedora box | dev Mac | ratio |
| --- | ---: | ---: | ---: |
| authoritative engine | 251.6 act/s | 415.0 | 0.61x |
| trusted mode | 1 843.1 act/s | 3 497.0 | 0.53x |
| trusted mode | **33.7 deals/s** | 64.0 | 0.53x |
| trusted speedup | 7.3x | 8.4x | 0.87x |
| parallel, all threads | **138.4 deals/s** (8 workers) | 534.7 (12 workers) | 0.26x |
| parallel, per worker | 17.3 deals/s | 43.2 | 0.40x |
| bytes per deal | 68.3 | 68.6 | - |
| **10M deals** | **20.1 h** | ~5.2 h | - |

**The correctness gate passed on the Fedora box**: identical play over 8 255
checkpoints. Generation there is valid.

Four things came out differently than assumed, and three of them matter:

1. **The box is faster per core than assumed** - 0.53x the Mac rather than the
   0.35-0.50x band this section guessed. T1 is **20.1 hours**, not ~37.
2. **Hyper-threading is on, and it is worth almost nothing here.** The host
   reports 8 usable CPUs, not the 4 D6 recorded. But per-worker throughput
   halves under it: 17.3 deals/s against 33.7 single-core. Eight threads deliver
   138.4 deals/s where four physical cores at full speed would give 134.8 - a
   gain of about **+3%**, not the 15-30% the runbook expected. Do not plan
   around it.
3. **Memory is 31.3 GB, not 48.** Irrelevant at these corpus sizes - T1 is
   0.68 GB - but it changes the headroom for in-RAM tensor materialisation.
4. It runs **CPython 3.14.7**, newer than the development machine's 3.14.2, so
   `compression.zstd` is present and the zlib fallback never engages. Bytes per
   deal matches the Mac to within 0.4%.

**What this now prices.** Under decision D7 the 10M-deal T1 run is deferred, so
these rates matter less as a corpus calendar and more as the cost of the
*targeted* rollouts the showing programme needs:

| Workload | Fedora | dev Mac |
| --- | ---: | ---: |
| S1, 131 072 rollouts (`docs/showing/hypotheses_s1.md`) | **16 min** | 4 min |
| S2 training set, ~440 000 rollouts | 53 min | 14 min |
| 1M rollouts | 2.0 h | 31 min |

Every experiment in the adopted programme is a coffee break on either machine.
That is the strongest argument for the review's ordering: the whole first
programme costs less than one T1 shard.

Operational notes:

- One worker per hardware thread gave the best total throughput, but note item 2
  before assuming that is worth the contention.
- `OMP_NUM_THREADS=1` in each worker; there is no BLAS work.
- The GPU is idle during generation.
- Sustained load: the box showed a +41% per-action cost rise within a match
  (3.381 -> 4.768 ms/action), close to the Mac's +75% pattern, confirming the
  quadratic history term is a property of the code and not of the host.

### 7.2 Sizing recommendation

Denominated in deals, with decisions derived:

| Tier | Content | Deals | Decisions | Approx. size |
| --- | --- | ---: | ---: | ---: |
| **T0 pilot** | full mixture, every integrity gate - **run, passed** | 141 601 | 3.5M | **9.2 MB measured** |
| **T1 core** | the primary corpus | 10M | ~250M | **~680 MB** at the measured 68 bytes/deal |
| **T2 exact** | exact labels at every node with <=5 tricks left, over T1 | - | ~50M nodes | ~0.6 GB |
| **T3 pairs** | forced-branch counterfactual pairs, four arms | 1M pairs | - | ~0.1 GB |

Why 10M deals for T1:

- **Statistical**: the threshold experiment resolved a 0.307-point effect with
  4 096 decisions, and the valuation work resolved z ≈ -12 effects with 2 000
  deals. Estimating effects of that size *within strata* - 30 RAMI-score bins x 5
  shape classes x 4 score regimes x 4 showing positions - needs on the order of
  1-4M focal decisions, and focal decisions are a small fraction of all decisions.
- **Learning**: a 1-10M parameter network wants on the order of 10-50M distinct
  decisions. T1 supplies 550M, more than an order of magnitude of headroom over
  the largest model a GTX 1070 will comfortably train.
- **Cost**: ~10-14 hours on the target box, and small enough to sit in page cache
  on a 32 GB machine.
- **Deal exhaustion is not a concern**: there are ~5.4 x 10^28 distinct deals. The
  binding constraint is *state and policy* diversity (§5), not deal diversity.
- **There is no T4 (D5).** A 100M-deal tier is dropped rather than deferred,
  because the corpus is a cache of a pure function and the *recipe* (§4.2) is the
  artifact that makes a larger tier a scheduling question rather than a research
  one.

Run T0 first, in full, and gate on it: schema stable, digests reproducible, a
regenerated shard byte-identical, the sentinel privacy test passing, cross-policy
splits disjoint, and DuckDB returning the expected counts. Only then launch T1.

### 7.3 The GTX 1070, honestly

- Generation does not use it at all.
- **Verify Pascal support before planning around it.** Recent PyTorch wheels have
  been dropping `sm_61`. The check is
  `python -c "import torch; print(torch.cuda.get_arch_list())"`, and `sm_61` must
  appear. If it does not, pin an older wheel/CUDA pair or build from source.
  `pyproject.toml` pins `torch>=2.13,<2.14`, which needs confirming against
  Pascal on this box specifically.
- **Do not expect mixed precision to help.** GP104's fp16 throughput is a small
  fraction of its fp32 throughput; train fp32. The 1070's 8 GB and ~6.5 fp32
  TFLOPS are ample for the 1-20M parameter range, which is the right size class -
  Phase 6's actor had 41 900 parameters, and part of why it had nothing to learn
  from was that there was nothing to learn *with*.
- The realistic training bottleneck is the input pipeline, which is why §3.4
  pre-materialises memory-mapped tensor caches instead of replaying inside the
  training loop.

---

## 8. Work packages, in order

| # | Package | Depends on | Output |
| --- | --- | --- | --- |
| **P0** | **B1**: pin, register, and commit the reference policy stack | - | **done** - `partner_aware_lead_v2` = `agent:sha256:252fe227...`, `discard_v3` = `agent:sha256:4b52fd90...` |
| **P1** | Calibrate the Fedora host | - | **done 2026-09-08** - gate passed, 0.53x per core, 138.4 deals/s on 8 workers, 10M deals = 20.1 h. PyTorch/Pascal status still unchecked |
| **P2** | Implement the D2 forced-branch showing stratum (both thresholds) | P0 | **done** - `forced_contract_pair`, ~8.4% of deals |
| **P3** | **E1** trusted transition path plus differential gate | - | **done** - `tuppi_engine.trusted`, 11.1x, byte-identical |
| **P4** | Corpus schema, writer, catalogue, integrity and privacy tests | P3 | **done** - `tuppi_corpus`, T0 pilot 141 601 deals, gates green. Parquet export not built |
| **P5** | **E2**, **E3**, and the **E5** PyPy measurement | P3, P4 | on a 4-core host these gate P6 rather than following it (§7.1) |
| **P6** | T1 generation run on Fedora, per-shard digests, periodic authoritative revalidation | P0-P5 | 10M deals, ~550M decisions |
| **P7** | T2 exact labelling and T3 forced-branch pairs over T1 | P6 | ~50M exact nodes, 1M four-arm pairs |
| **P8** | **Re-run the Phase 5 comparisons on a per-deal endpoint** (`handoff.md` §1.6) | P6 | either Phase 5 reopens or its closure is confirmed on an endpoint that can actually resolve it |
| **P9** | **N4** showing network against the §1.7 ceiling | P6, P7 | share-of-ceiling for a learned function vs. 33.8% for the descriptor family |
| **P10** | **N1** belief network under the §5.1 constraints, checked against `suits.layouts()` | P6 | cross-policy card-location accuracy vs. the hard-uniform baseline of Phase 5G-B |
| **P11** | **N2** value network, then substitution into existing search as a rollout replacement | P6, P7 | the first search comparison whose rollout is not a heuristic bot |
| **P12** | **N3** advantage-trained policy, evaluated on the per-deal endpoint and then the complete-match protocol | P6, P7 | the first candidate whose supervised optimum is not the reference agent |

**P8 and P9 are the cheapest high-information packages** and should not wait
behind the network work. P8 costs almost nothing once the corpus exists and could
reopen a closed programme. P9 has a measured ceiling, a measured heuristic
baseline, and a measured cap on the competing family - which makes it the
best-posed learning question in the project.

`N0`, the scaled behaviour clone, sits alongside P9 as a cheap baseline. The
sealed promotion bank stays closed throughout; everything above is development
evidence until a preregistered, uncensored comparison says otherwise.

## 9. Open questions for the corpus owner

D1-D3 are settled; see the decisions block above. What remains:

1. **Fedora host specification** - physical core count, RAM, free disk, and
   whether the box can be dedicated for 10-20 hours. All of §7.1 is provisional
   until this is known.
2. **B1** - what identity should the improved stack carry, and can `void_lead.py`
   and `nolo_discard.py` be committed independently of the other untracked work
   in the tree? This blocks everything.
3. **T4** - is 100M deals a real goal, or is 10M plus a regeneration recipe the
   right ceiling? The corpus is a cache of a pure function, so the recipe is
   arguably the more valuable artifact.
