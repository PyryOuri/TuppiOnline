# The Phase 7 corpus layer

`src/tuppi_corpus/` generates play into records, stores only what replay cannot
recompute, and derives decisions on demand. The plan, its measurements and its
decisions are in `docs/database/phase7_charter.md`; the operational side is in
`docs/database/fedora_runbook.md`. This document is the architecture.

## The dependency direction is one-way, and checked

```text
tuppi_rules -> tuppi_engine -> tuppi_eval -> tuppi_agents -> tuppi_match -> tuppi_exact
                                                                                 |
                                                                                 v
                                                                           tuppi_search
                                                                                 |
                                                                                 v
                                                                           tuppi_corpus
```

`tuppi_corpus` may read the earlier packages. **None of them may import it.**
`tuppi_corpus.validation.dependency_direction_problems` parses their source and
fails if any does, for the reason every layer here gives: the earlier results are
quoted against specifications recording no corpus, no learning and no sampling,
and if an engine or agent module could reach this package those claims would
become retroactively corpus-assisted.

One wrinkle is worth knowing, because this layer walked into it: the exact and
search boundary checks read raw module **text**, so naming an outer package in a
comment inside an earlier one reports a dependency that does not exist. This
layer's own check matches an `import` statement instead of a mention.

## Modules

| Module | Responsibility |
| --- | --- |
| `seeds` | Domain-separated deterministic seed derivation; unbiased draws. |
| `packing` | Hands as two bits of seat per card; actions as card indices; the canonical hand order. |
| `records` | The two stored row types and their fixed-width encodings. |
| `manifest` | The recipe: content-addressed, with a SHA-256 per source that can affect play. |
| `strata` | The mixture, the policy population, per-stream planning, split assignment. |
| `generation` | Playing one stream into records. The only place an action is chosen. |
| `shards` | Shard files and the append-only catalogue. |
| `replay` | Deriving decisions from a stored deal, and verifying one. |
| `validation` | The boundary gate. |
| `runner` | The finite noninteractive CLI. |

## Store only what replay cannot recompute

An observation is a pure function of `(explicit deal, action prefix, seat)`, and
`tests/agents/test_conformance.py` already proves a selected action is
independent of `match_ref`, output paths and observation construction count. So
a deal's hands plus its ordered actions are a complete record of it, and every
feature vector, legal action set and inferred void is derived.

| | Bytes per deal |
| --- | ---: |
| one serialised observation per example, JSONL, as Phase 6 stored it | ~110 000 |
| a `DealRecord` | 104 |
| a `DealRecord` after zstd, measured over the T0 pilot | **70** |

There are no decision rows. 10M deals is about 550M decisions; materialising
them would cost more than the deals do and would pin the corpus to one encoder
version. `replay.replay_deal` reconstructs them at a measured **16 481
decisions per second per core**, which is faster than any consumer here needs.

The corpus is consequently a *cache of a pure function*, and the manifest is the
artifact. That is what decision D5 traded the 100M tier for.

## Two things the pilot proved were not safe to assume

**Hand order is behaviourally material.** Packed hands are sets per seat, so the
order a hand was dealt in is not recoverable from them - and that order changed
the selected action in **3 of 12** measured deals, because a hand's order reaches
`legal_actions` and some tie-breaks resolve on the lowest legal index. This is
the effect `docs/agents/baseline_profiles.md` describes as the legacy
min-information convention. Generation therefore canonicalises the explicit deal
**before playing it**, so what is stored fully determines what was played.
Without that step the corpus would have been silently unreplayable.
`tests/corpus/test_corpus.py::test_dealt_hand_order_is_behaviourally_material`
asserts the underlying fact rather than trusting this paragraph.

**A stored deal must reproduce its own recorded outcome.** `replay.verify_deal`
replays through the **authoritative** engine and requires the contract, team
tricks, trick winners and resulting score to reappear. If that ever failed, every
label derived from the corpus would be wrong in a way nothing else would notice.
`verify` runs it on a sample of every run.

## Determinism

Every random quantity - which stratum a stream draws, its split, its policy set,
its initial score, where a branch fires, and what a softened decision picks -
comes from `seeds.derive_seed`, a canonical JSON object over named coordinates.
Nothing uses a module-global RNG, a mutable stream, worker completion order,
wall-clock time, or `hash()`, which is salted per process.

`generation` is the only module that chooses an action, deliberately: every
deviation from on-policy play is decided in one place from an explicit
coordinate, rather than by a stateful wrapper policy whose behaviour would depend
on how many times it had been asked a question.

`--workers` therefore affects wall-clock time and nothing else. A shard's bytes
are a pure function of the manifest and its stream range, and `verify` proves it
by rebuilding one in a fresh process and comparing digests.

## Where randomness is *required*, not tolerated

`docs/valuation/handoff.md` §3.1 is the reason the softened stratum exists.
Inference fitted on a deterministic-policy corpus measures that policy's
determinism rather than the game: drop the policy assumption and the retained
signal is **1-5%** for exactly the high-card observations that looked most
informative. §3.2 gives the mechanism - `partner_aware_v1` leads its lowest card
100% of the time, and real players do not.

So three properties are built into `strata` rather than left to a convention:

- the **softened** stratum picks uniformly among the policy's top *k* actions
  with probability *n/d*, so lead rank and duck choice are not constants;
- **held-out streams draw only from reserved policy sets**, making a held-out
  score cross-policy by construction;
- **splits are by stream, never by row** - a stream's ~55 decisions per deal are
  correlated, and splitting rows would leak.

A softened policy cannot live in `tuppi_agents`: that package's architecture test
forbids sampling vocabulary in the policy layer, and rightly. The softening is a
research device and sits here.

## Forced branches are where the advantages come from

`forced_contract_pair` and `forced_play_pair` generate **two arms from one deal**
at an identical prior state: same hands, same score, same dealer, divergent
action. That is the RAMI/NOLO threshold experiment's design generalised, and the
statistical unit its intervals are computed over.

Forcing the *contract* while letting the policy choose the card is also decision
D2. With both branches recorded from the same state, any showing threshold can be
evaluated after the fact, so the corpus **settles** the contested threshold
instead of presupposing one - and no generation is wasted if the answer changes.

`forced_play_pair` takes the policy's own runner-up as the second arm rather than
a random legal card, so the pair measures a decision a competent player might
actually have made.

Both are single-deal units. The primary utility is **signed deal points for the
acting partnership**, the endpoint both the threshold experiment and the
valuation work chose, and for the reason `handoff.md` §1.6 gives: effects visible
at z ≈ -9 on per-deal tricks are invisible at 32 match pairs.

## Privacy

`DealRecord.hands` holds the complete deal. The only supported path from it to
anything a model may read is `replay`, which goes through
`match_observation_for`, so each derived observation carries exactly what the
acting seat was entitled to see.

`tests/corpus/test_corpus.py::test_a_derived_decision_never_carries_another_seat_card`
is the sentinel: it checks that no card from the other three hands appears in a
derived observation's own-hand view, and that no serialised observation carries a
hands field. A pipeline that read `hands` directly to build features would pass
nothing like it, which is the point.

Bulk output belongs on a plain local filesystem outside the repository and
outside any synced folder.

## Trusted transitions, and what generation owes in exchange

Generation runs inside `tuppi_engine.trusted.trusted_transitions`, worth a
measured 11.1x. That module's docstring names two conditions for using it at all,
and both are met here rather than assumed:

- the differential gate is `tests/engine/test_trusted_transitions.py`, which
  plays the same streams through both paths and compares every action, score and
  deal count;
- every `revalidation_period`-th deal is additionally checked through the
  authoritative path *inside* the trusted block - which works because an explicit
  `validate_match_state` is always honoured - and the deal carries
  `FLAG_REVALIDATED`, so the guarantee is recorded in the data rather than
  claimed in a log.

Deal boundaries stay validated regardless: `begin_explicit_deal` accepts external
data and `research_deal_result_from_state` closes every deal. That is not
incidental - it is what caught an unconstructible entry in the first stratified
score schedule, since only one team may hold a positive rising score.

## What this layer is not

It generates and stores play; it does not learn from it. Model fitting, gradient
descent, search integration and belief weighting belong to the layers that
consume a corpus. `tuppi_corpus.validation.excluded_technique_problems` scans for
`torch`, `tensorflow`, `jax`, `sklearn`, `numpy`, `random` and `secrets` rather
than trusting this paragraph.

It is also not an expert corpus, and no quantity of it makes the generating
policy stronger than it is. The reference is `partner_aware_lead_v2`, which is
measured against `partner_aware_v1` and nothing else; zero of the 38 catalogued
strategy rules carry `expert_validated` or `simulation_validated` provenance.
What the corpus adds is not a better player but resources the project did not
have: ground-truth hidden hands, measured counterfactual advantages, and dense
per-deal returns.

## Not yet built

Three tiers from the charter have their interfaces here but no implementation:

- **T2, exact endgame labels.** `exact_label_max_tricks` is a manifest field,
  validated and carried into the run identity, and currently must be 0. The
  labelling pass over a completed T1 is unwritten. Cost is known: ~6.7 ms per
  deal for a solve at every node with five or fewer tricks left.
- **Oracle / perfect-foresight labels**, the 100% column of the charter's §1.7
  ceiling.
- **Parquet export.** The canonical format is deliberately dependency-free
  binary; a DuckDB-queryable export is a converter over `read_shard`, not a
  change to what is trusted.
