# T0: frozen experimental contract for the rule-defect / tactical-ceiling audit

**Status: pre-registered 2026-09-09, before any performance comparison was run.**
Committed before the T2 and T3 runners existed. Nothing below may be revised
after seeing a performance outcome.

This work package executes **T0-T3 only**. It cannot promote a policy, and it
does not authorise T5-T9, neural training, a new corpus, an endgame solver, or a
self-play programme.

---

## 1. Identities

| Item | Value |
| --- | --- |
| commit | `2aaf9902b673464fc8e797cabf7d589e65809a22` |
| pinned source set | 66 files, digest `sha256:2d6432fa75a37b91c067c555394539dff8acc5a18f642df9e95c07743f6868f5` |
| pinned-set worktree status | **clean** - all 66 pinned files byte-identical to HEAD (verified, not assumed) |
| runtime | CPython 3.14.2, macOS-26.6.2-arm64 |
| ruleset | `project_target_v1` |
| card encoding | `project_target_v1_suit_major_hdcs_rank_2_to_ace` |

The working tree is **not** clean overall: `src/tuppi_server/*`,
`src/tuppi_nolo/*` and their tests carry another author's uncommitted work. None
of those files is in the pinned set, none is imported by the reference policy or
the engine, and each of the 66 pinned files was checked against HEAD
individually. The precise claim is therefore *pinned-set clean at HEAD*, not
*clean worktree*.

### 1.1 The reference, resolved by identity

| Role | Profile key | Agent identity |
| --- | --- | --- |
| **control / production reference** | `partner_aware_lead_v2` | `agent:sha256:252fe227b01900e3c1d94822179adee07a64e3a3eb761a529a425f39b95d435d` |
| the profile it scores through | `partner_aware_v1` | `profile:sha256:c5e74faedbf001d91834fd6f40e5ac3d8a8cb8512d1c46cdd793bc71bd373030` |
| frozen Phase 4 rung it extends | `partner_aware_v1` | `agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929` |

`partner_aware_lead_v2` is chosen as the control because it is the deployed AI,
the analysis reference, and the corpus reference under charter decision D4.
Auditing `partner_aware_v1` instead would risk finding defects in lead rules
that `lead_v2` has already replaced.

It is **not** modified by anything in this package. Every variant is a distinct
content-addressed identity.

## 2. Endpoint

**Primary: per-deal frozen-continuation match equity**, from
`src/tuppi_valuation/equity.py`. This is an already-validated, precisely defined
endpoint in the repository and it was exercised and checked in
`docs/showing/results_s1.md`; no new estimator is built here.

- Utility orientation: equity gained by **the evaluated partnership** across the
  deal, from 0-0.
- The deal model feeding the absorbing chain is fitted from **reference
  self-play deals only** in the existing T0 corpus pilot, by the same code path
  S1 used, so there is exactly one normalisation in play.
- Endpoint self-checks, all of which must pass before any comparison is priced:
  symmetric-model control `V(0-0) = 0.5` exactly; the empirical table within the
  measured dealer asymmetry of the model-free `[1/4, 3/4]` bounds.

Secondary and **diagnostic only**, never promoted to primary after the fact:
signed deal points, team tricks, deal-win rate, contract shares.

**Minimum worthwhile gain: δ = 0.001 equity per deal.** This is the project's
already-committed threshold for this endpoint (charter D7 / `hypotheses_s1.md`),
carried over unchanged. It is a resource-allocation threshold, not a measured
property of Tuppi and not equivalent to the 0.10-signed-point alternative.

## 3. Deal manifest and normalisation

| Item | Value |
| --- | --- |
| discovery deals | **2 000** |
| root seed | `tuppi-t0-audit-v1` |
| stream indices | 0 … 1999 |
| dealer | `stream_index mod 4` - exactly 500 per seat |
| deal drawn | `MatchStream.deal(0)`, hands canonicalised before play |
| starting score | 0-0 |
| showing | **natural** - no forced contract |
| **held-out manifest** | root seed `tuppi-t0-audit-v1`, stream indices **100 000 … 101 999**, recorded here and **not executed or inspected in this session** |

Hands are canonicalised to deck order before play, because the dealt order is
behaviourally material and packed hands do not preserve it (measured: it changed
the selected action in 3 of 12 deals).

**Complementary assignment and the paired contrast.** For each underlying deal:

```
control  : reference in all four seats            -> U_ctrl(team0), U_ctrl(team1) = -U_ctrl(team0)
A        : variant in seats {0,2}, reference {1,3} -> U_A(team0)
B        : variant in seats {1,3}, reference {0,2} -> U_B(team1)
contrast = ½ · [ (U_A(team0) − U_ctrl(team0)) + (U_B(team1) − U_ctrl(team1)) ]
```

**One contrast per underlying deal.** Both assignments, all four seats and every
decision inside a deal are one cluster. Confidence intervals resample underlying
deals and nothing finer.

Interval method: cluster bootstrap over deals, 5 000 replicates, deterministic
seed derivation (`tuppi_corpus.seeds`), no global RNG and no dependence on worker
completion order. Aggregation is by sorted deal index, so worker order cannot
affect a number.

## 4. T2 variant list, frozen

**The repository supports 4 single-rule ablations of this reference, not 38.**
Established before any performance measurement, and by the repository's own
guard rather than by choice.

Of the 24 catalogued rules that `partner_aware_v1`'s profile implements,
`HeuristicProfile` refuses to disable 20:

- **8 mechanical** - refused by design; they are consequences of the ruleset, not
  strategy, and the non-negotiables forbid ablating them anyway;
- **12 non-mechanical with `independently_disableable = False`** - no documented
  downstream legal fallback exists, so there is no way to disable them that is
  not an undocumented code edit.

The mechanism used for the 4 that are eligible: `profile_key` is a *catalogue
lookup key*, while profile identity is content-addressed over behaviour, so a
variant reuses the key and mints its own `profile_id`. Each was verified to
build and to differ from the control's identity.

| # | Variant | Disabled rule | Provenance | Scope |
| --- | --- | --- | --- | --- |
| V1 | `profile:sha256:753d673191b…` | `partner.nolo.prefer_leading_partner_void_suit.v1` | generic hypothesis | single rule |
| V2 | `profile:sha256:437fd54f8ce…` | `partner.rami.overtake_when_partner_beatable.v1` | generic hypothesis | single rule |
| V3 | `profile:sha256:7b8b384dacf…` | `partner.rami.prefer_leading_suit_partner_can_follow.v1` | generic hypothesis | single rule |
| V4 | `profile:sha256:db83c4a97a4…` | `reactive.rami.avoid_overtaking_partner.v1` | generic hypothesis | single rule |
| V5 | `agent:sha256:d8b426f1263c…` | **both `lead_v2` lead layers** | n/a | **compound**, scope documented below |

**V5 is explicitly a compound subsystem ablation, not a single-rule one.** It
removes both of `partner_aware_lead_v2`'s lead layers at once
(`tuppi.agents.void_seeking_nolo_lead.v1` and
`tuppi.agents.establishment_rami_lead.v1`), and its documented downstream
fallback is the frozen, registered, separately tested `partner_aware_v1`. It is
included because those two layers are the reference's only uncatalogued
behaviour and because their fallback is a real registered profile rather than an
invented one. Its result may not be attributed to either layer individually.

No variant will be added, no seed re-searched and no sample extended because a
result nearly qualifies.

**Budget.** 5 variants × 2 000 deals × 2 assignments = **20 000 variant deal
executions**, plus 2 000 reusable control executions. This is far below the
152 000 the work package permits; the limit is the switch surface, not compute.

## 5. Gates, fixed now

### T2 - rule-ablation discovery (exploratory)

A variant qualifies for later consideration only if **both**:

- mean paired per-deal gain ≥ **+δ** (i.e. disabling the rule *helps* by at least
  the practical threshold), and
- exploratory one-sided **95%** lower bound > 0.

All T2 intervals are exploratory. **No qualifying variant closes this ablation
route at this budget.** Qualification is not promotion; promotion requires a
separate authorised task, fresh locked deals, and a one-sided 97.5% bound.

### T3 - two-trick intervention ceiling (discovery gate)

Scope, fixed now and not movable to a more favourable decision:

- at most **one** intervention per deal for the evaluated partnership;
- at that partnership's **first turn in trick 12** (public: eleven completed
  tricks, the acting seat is in the evaluated partnership, and its partner has
  not yet acted in the current trick), **even if the move is forced**;
- the condition is identifiable from the formal public observation alone; no
  hidden shared counter.

Every legal root action is replayed on the **actual hidden deal** to completion
with all four seats on the frozen reference, each seeing only its own formal
observation, and all 13 tricks played. Hidden state is used **offline only**, to
pick the best realised branch. The reference action is always included, so the
oracle gain is ≥ 0 by construction. Forced and outcome-identical cases
contribute **zero and are retained**, not discarded.

One-sided **95%** bounds on a nonnegative bounded outcome:

| Decision | Condition |
| --- | --- |
| **proceed** (investigation only) | lower bound > δ |
| **kill this scope** | upper bound < δ |
| **inconclusive** | otherwise - stop at this budget, do not enlarge the sample |

Because the outcome is nonnegative and may be zero-inflated, a percentile
bootstrap can return a degenerate `[0, 0]` interval that is **not** evidence that
population headroom is zero. If zero opportunities are observed, the upper bound
will be reported as a conservative exact binomial (Clopper-Pearson) bound on the
opportunity rate combined with the observed maximum per-opportunity gain, and
labelled as such.

## 6. Discovery / test separation

- Everything in T1-T3 is **discovery**. The 2 000-deal manifest is discovery
  data and may not be used for any promotion decision.
- The held-out manifest in §3 is recorded and untouched. It is not inspected in
  this session, not even for descriptive statistics.
- **This session cannot promote a policy.** A qualifying T2 variant or a passing
  T3 gate authorises a *later* implementation task, nothing more.

## 7. Blocking pre-conditions, already satisfied

The work package requires legality, observation-boundary, replay and determinism
tests to pass before performance measurement. Run at
`2aaf990`:

```
tests/agents/test_architecture.py  tests/agents/test_conformance.py
tests/agents/test_properties.py    tests/engine/test_purity.py
tests/engine/test_properties.py    tests/engine/test_differential_rules.py
tests/engine/test_trusted_transitions.py  tests/corpus
-> 118 passed
```

A harness or reference-identity failure discovered later blocks measurement and
must be reported as a defect, not repaired under this experiment identity.

## 8. What this package cannot establish

- Nothing about match strength - the endpoint is a per-deal equity surrogate
  under a frozen continuation, deliberately not a full-match tournament.
- Nothing about the 12 unswitched rules or the 8 mechanical ones.
- Nothing about non-zero starting scores, later showing seats, or opponent
  families other than the reference.
- Nothing human-validated. The T4 packet is prepared for review; no expert
  feedback is invented.
