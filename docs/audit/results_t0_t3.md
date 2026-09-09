# T0-T3 audit results: rule defects and the two-trick ceiling

**Status: COMPLETE for T0-T3. T4 packet prepared, unreviewed.**

| Route | Decision |
| --- | --- |
| **T2 rule-ablation discovery** | **CLOSED** - no qualifying variant at this budget |
| **T3 two-trick intervention ceiling** | **INCONCLUSIVE** - stop at the fixed budget |

Pre-registration: [prereg_t0.md](prereg_t0.md), committed as `af0f5b9` before
any runner existed and before any performance comparison. Nothing below revises
it.

This session did not modify the reference, did not promote a policy, and did not
implement any strategic repair.

---

## 1. Separating what was measured from what is hypothesised

Section 2 is measurement. Section 3 is measurement. Section 4 is hypothesis
about *mechanism*, labelled as such. Section 6 is limitations. Section 7 is the
gate decisions. Nothing in §4 is used to support a gate.

## 2. T0 - the frozen contract, and one structural blocker

Identities, endpoint, manifest and gates are in the pre-registration. Two
results from freezing it are findings in their own right.

**Blocking pre-conditions passed.** 118 legality, observation-boundary, replay
and determinism tests at `2aaf990`.

**The pinned source set is clean at HEAD**, verified file by file: all 66 files
byte-identical. The working tree carries another author's uncommitted work in
`tuppi_server` and `tuppi_nolo`; none of it is pinned, imported by the reference,
or part of the engine. The precise claim is *pinned-set clean*, not *clean
worktree*.

### 2.1 The repository supports 4 single-rule ablations, not 38

Established before any performance measurement, by the repository's own guard.

| | Count |
| --- | ---: |
| catalogued strategy rules | 38 |
| implemented by the reference's profile | 24 |
| of those, **mechanical** - refused by design, and out of scope anyway | 8 |
| of those, **strategic and unvalidated** | **16** |
| of those 16, **the profile will let us disable** | **4** |
| **unvalidated strategic rules with no ablation switch** | **12** |

`HeuristicProfile` refuses the other 12 with
`rule '<id>' cannot be disabled` - they carry
`independently_disableable = False`, meaning no documented downstream legal
fallback exists. Disabling them would require an undocumented code edit, which
the non-negotiables forbid and which would risk a compound subsystem removal
presented as a single-rule ablation.

**This is the binding constraint on the whole discovery route.** The budget
permitted 152 000 variant executions; 20 000 were used. The limit was the switch
surface, not compute. **Three quarters of the reference's unvalidated strategy is
untestable by ablation with the tooling that exists.**

## 3. Measurements

### 3.1 T1 - catalogue, tracing, and the reference's certainties

**Tracing is inert.** Traced and untraced reference runs selected identical
actions and reached identical outcomes on 64 fixed deals. The trace is therefore
admissible as evidence.

**Rule firing**, 400 deals / 21 899 decisions (1 099 showing, 20 800 trick play).
2.6% of decisions were settled by the tie-break.

**The reference's hard ownership exclusions are sound.**

| | |
| --- | ---: |
| `PublicInference.can_seat_hold` checks against true deals | **202 800** |
| cases where a seat was excluded from a card it actually held | **0** |

The hypothesis that the reference acts on false ownership certainties is
**refuted** for its implemented deductions, at this sample. That is a clean
negative and it removes a candidate mechanism.

**The behavioural ducking deduction is not sound**, and it is not the
reference's. "A seat that took a trick it could have ducked holds nothing below
the current high card" is recorded in `docs/valuation/handoff.md` §3.1 as
"robust under rationality". Checked against true deals:

| Contract | Violations | Rate |
| --- | ---: | ---: |
| NOLO | 71 / 429 | **16.6%** |
| RAMI | 334 / 792 | 42.2% |
| overall | 405 / 1 221 | 33.2% |

RAMI is unsurprising - taking tricks is the objective. But it fails in **one NOLO
case in six**, which is the case it was proposed for. The reference does not
implement it; the finding is that it must not be promoted to a hard mask if
anything later wants it. NOLO scores *team* trick totals, so a player has sound
reasons to take a conceded trick while holding lower cards.

### 3.2 T2 - rule ablation, 2 000 deals, exploratory one-sided 95%

Each variant deployed in **both** candidate seats against the reference in the
other two, then the candidate team swapped on identical hands; one paired
contrast per underlying deal. 22 000 deal executions in **44.3 s** (497/s, 12
workers).

| | Rule / scope | Mean gain | 95% lower | 95% upper | Action divergence | Outcome change | Qualifies |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| V1 | `partner.nolo.prefer_leading_partner_void_suit.v1` | +0.00000 | +0.00000 | +0.00000 | **0.0%** | 0.0% | no |
| V2 | `partner.rami.overtake_when_partner_beatable.v1` | −0.00020 | −0.00040 | +0.00000 | 5.2% | 3.6% | no |
| V3 | `partner.rami.prefer_leading_suit_partner_can_follow.v1` | +0.00000 | +0.00000 | +0.00000 | **0.0%** | 0.0% | no |
| V4 | `reactive.rami.avoid_overtaking_partner.v1` | +0.00000 | +0.00000 | +0.00000 | **0.0%** | 0.0% | no |
| V5 | both `lead_v2` lead layers → `partner_aware_v1` *(compound)* | **−0.00574** | −0.00652 | −0.00498 | — | 66.9% | no |

Qualification required mean ≥ +0.001 **and** an exploratory lower bound above
zero. **No variant qualified.**

**Three of the four ablatable rules are inert: disabling them changed not one
action in 4 000 assignments.** They are not merely outcome-neutral - they never
altered a selected action at all, over roughly 44 000 decisions of play. Yet the
trace shows they are cited by the *winning* candidate regularly:

| Rule | Cited by any candidate | Cited by the winner | Action divergence when disabled |
| --- | ---: | ---: | ---: |
| V1 | 5.82% | 5.82% | 0.0% |
| V2 | 0.51% | 0.51% | **5.2%** |
| V3 | **17.93%** | **17.93%** | 0.0% |
| V4 | 1.90% | 1.68% | 0.0% |

So citation frequency and decisiveness are almost inverted: V3 participates in
scoring the winning candidate on nearly one decision in five and never changes
what is played, while V2 participates on one in two hundred and is the only rule
that changes anything.

**V5 is the positive control, and it works.** Removing both lead layers costs
**−0.00574 equity per deal**, one-sided 95% [−0.00652, −0.00498] - about 5.7×
the practical threshold, on a tight interval. The instrument detects a real
effect of the expected size on this manifest and endpoint. The null results for
V1, V3 and V4 are therefore informative rather than a blindness artifact. It
also independently reconfirms the previously measured lead improvements on an
endpoint and manifest they were not fitted to.

V5's result may **not** be attributed to either lead layer individually; it is a
two-layer compound ablation and was pre-registered as one.

### 3.3 T3 - two-trick intervention ceiling

Same 2 000 control deals. At the evaluated partnership's first turn in trick 12
(public trigger: eleven completed tricks, acting seat in the evaluated
partnership, partner not yet acted), every legal action replayed on the **actual
hidden deal** to completion with the frozen reference in all four seats. Hidden
state used offline only, to select the best realised branch.

| | |
| --- | ---: |
| assignments reaching the root | **4 000 / 4 000** |
| forced at the root (retained as zero) | 570 = 14.2% |
| assignments with **any** oracle gain | 139 = **3.5%** |
| mean per-deal oracle gain | **+0.000846** |
| one-sided 95% bounds | **[+0.000698, +0.001004]** |
| δ | 0.001000 |

**INCONCLUSIVE.** The lower bound (+0.000698) does not exceed δ, so the route
may not proceed; the upper bound (+0.001004) does not fall below δ, so the scope
is not killed. The interval straddles the threshold by **4 × 10⁻⁶** on the upper
side.

Per the pre-registration this stops at the fixed budget. The sample was not
enlarged and will not be in this session.

Opportunities were observed (139), so the degenerate-interval provision did not
apply; the Clopper-Pearson fallback was implemented and not needed.

## 4. Hypothesised mechanisms - not measurements

**Why V1 and V3 are inert.** Both are *lead* rules, and `partner_aware_lead_v2`
replaces both leads outright with its own two layers. The catalogued lead
preferences still participate in scoring - hence the 5.82% and 17.93% citation
rates - but a higher-priority component decides every lead. **The reference's own
improvement shadowed two of the four rules the repository lets us audit.** This
is consistent with all the evidence here but was not established by a
manipulation.

**Why V4 is inert.** Plausibly because the mechanical
`partner.rami.protect_certain_partner_winner.v1` already covers the cases where
overtaking a partner matters, and elsewhere the cheapest-winner component
decides. Untested.

**Why the trick-12 opportunity is small.** With two cards left, the acting seat
has at most two legal actions, 14.2% of the time only one, and a separately
measured 50.3% of trick-play choices are outcome-neutral. A 3.5% opportunity
rate is what that structure predicts. Untested as a causal claim.

## 5. Reproduction

```bash
cd TuppiProject && export PYTHONPATH=src

# blocking pre-conditions
python -m pytest tests/agents/test_architecture.py tests/agents/test_conformance.py \
  tests/agents/test_properties.py tests/engine/test_purity.py \
  tests/engine/test_properties.py tests/engine/test_differential_rules.py \
  tests/engine/test_trusted_transitions.py tests/corpus -q     # 118 passed, 24 s

# T1
python work/audit/t1_rule_audit.py --output reports/audit \
  --trace-deals 64 --audit-deals 200

# T2 + T3
python work/audit/t2_t3_runner.py --output reports/audit --workers 12   # 44.3 s

# T1 firing analysis + T4 packet
python work/audit/t4_packet.py --output reports/audit

# T2 action disagreement (single-threaded; parallelise if repeated)
python work/audit/t2_action_disagreement.py
```

| Stage | Executions | Runtime | Throughput |
| --- | ---: | ---: | ---: |
| T2 + T3 | 22 000 deals | 44.3 s | 497 deals/s (12 workers) |
| T2 action disagreement | 32 000 deals | >10 min | single-threaded, not parallelised |
| T1 certainty audit | 200 deals, 202 800 checks | ~1 min | — |

Machine: Apple M3 Max, CPython 3.14.2. Artifacts in `reports/audit/`:
`t1_rule_catalogue.json`, `t1_trace_sample.json`, `t1_certainty_audit.json`,
`t1_firing_analysis.json`, `t2_t3_results.json`, `t2_action_disagreement.json`,
`t4_review_packet.json`, `t4_researcher_only.json`.

## 6. Limitations

- **The endpoint is a per-deal equity surrogate** under a frozen reference
  continuation. It is not a match-strength claim and no tournament was run.
- **Nothing is established about the 12 unswitched unvalidated rules** or the 8
  mechanical ones. That is three quarters of the reference's unvalidated
  strategy.
- **V5 is compound.** It says the two lead layers together are worth ~0.0057
  equity per deal; it says nothing about either alone.
- **T3 bounds one scope only**: a single intervention, at that exact public
  trigger, followed by the reference. It does **not** bound a general endgame
  policy, repeated interventions, other decision locations, or a
  feasible-world-enumerating module. Statewise improvements were not summed.
- **The certainty audit reads hidden hands.** It is an offline analysis path,
  confined to one function, and nothing it produces re-enters an observation.
- **Discovery data only.** The 2 000-deal manifest may not support a promotion.
  The held-out manifest (stream indices 100 000-101 999) was recorded and not
  executed or inspected.
- **No human review.** The T4 packet is prepared and unread; no expert
  validation is claimed.
- Measured at 0-0 with natural showing, against the reference only.

## 7. Gate decisions

### T2: CLOSED

No variant met the pre-registered qualification. Per the pre-registration, no
qualifying variant closes this ablation route at this budget. The answer to
objective (A) - "frequent, repairable strategic-rule defects" - is **no, among
the rules the repository permits testing**: three are inert and the fourth is
mildly beneficial. The instrument's power is demonstrated by V5.

The important caveat is §2.1: this tested 4 of 16 unvalidated strategic rules.
The route is closed *at this budget with this tooling*, not answered in general.

### T3: INCONCLUSIVE

Neither bound resolves. Stop at the fixed budget; the sample was not enlarged.

The evidence leans against this scope being worth funding, though it does not
formally kill it. The oracle gain is a **ceiling** on any observation-only
policy at this trigger, and it sits at δ. A separate measurement on the showing
decision (`docs/showing/results_s1b.md`) found that a perfect
observation-compatible selector realised **3.9%** of the corresponding oracle
gain. If a comparable ratio held here, the realisable value would be roughly
30× below δ. That is inference from a different decision class, not a
measurement of this one, and it may not be used as a gate.

## 8. Recommended next tasks - at most two, not executed

**1. Extend the ablation switch surface (capability, not strategy).**

The audit route is blocked by tooling rather than by evidence: 12 of the 16
unvalidated strategic rules have no documented downstream fallback, so they
cannot be ablated at all. Giving each a declared fallback and setting
`independently_disableable = True` would make the T2 design executable over the
whole unvalidated surface at ~5× the compute already spent - well inside the
152 000-execution budget this package allocated and did not use. This is the
highest-value next task because it converts an untestable three quarters of the
reference's strategy into a testable one. It changes no behaviour: the switch is
inert until a variant sets it.

**2. Measure rule *blocs* using the registered ladder rungs (measurement, no new code).**

The frozen ladder already isolates groups of rules: `reactive_contract_v1` →
`public_counting_v1` adds the hard-inference bloc, → `partner_aware_v1` adds the
partnership bloc, → `match_aware_v1` adds the score-aware bloc. All are
registered, frozen, separately tested profiles. Running them on the **same T0
manifest with the same endpoint and normalisation** would attribute value to
each bloc without a single new variant or code edit, and would partially
substitute for the per-rule ablation that §2.1 blocks. Estimated cost: 5 rungs ×
2 000 deals × 2 assignments ≈ 20 000 executions, about 45 s. Bloc attribution is
weaker than per-rule attribution and must be reported as such.

**Not recommended:** enlarging T3's sample. Resolving a ceiling that already sits
at δ would answer a question whose practical answer is very likely "not worth
it", and the pre-registration forbids enlarging it here in any case. If the
tactical route is pursued at all, it should be re-scoped - a wider late-deal
window with its own pre-registration - rather than re-powered at the same
trigger.

**Explicitly not done and not authorised by this session:** no strategic repair,
no production override, no joint rule grid, no communication convention, no
recovered search component, no promotion from discovery data, and no
feasible-world enumeration.
