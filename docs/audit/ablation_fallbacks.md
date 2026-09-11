# Ablation fallbacks: what it takes to make an assumption testable

T0-T3 found that **12 of the incumbent's 16 unvalidated strategic rules cannot be
ablated at all**. `HeuristicProfile` refuses to disable them, because no
documented downstream legal fallback exists, and T0-T3 called this "the binding
constraint on the whole discovery route" — the limit was the switch surface, not
compute. Three quarters of the strategy has never been tested, and could not be.

That was never a science problem. It is a design decision about what a policy
does when a rule is taken away, and this document is that decision.

## 1. The fallback, stated once

> **A disabled rule's contribution is removed from the score layout. Whatever
> components remain decide. If none remain, the existing deterministic tie-break
> selects the lowest canonical legal action index.**

The last clause is not a new mechanism. `CandidateEvaluation.selection_key` is
already `(score_vector, -action_order_index)`, so an exact tie across every
component already resolves to the lowest engine action index — which is precisely
the `first_legal` Phase 3 control, the floor every rung is measured against. The
fallback therefore terminates in a policy that already exists, is already
deterministic, and is already a published baseline.

This is not a licence to flip flags. A rule is only ablatable once *removing it*
leaves the score vector the same length as the layout and the policy still
choosing a legal action, and that has to be implemented and exercised per rule.

## 2. Flipping the flag is identity-safe, which removes the usual objection

`HeuristicProfile.identity_data` digests `disabled_rule_ids` and
`enabled_rule_ids` — the *lists* — not the `independently_disableable` flag.
Verified directly: flipping all 29 non-disableable rules in memory leaves every
Phase 4 agent id and every improved agent id unchanged. So nothing here can move
the frozen baseline that Phase 4-6 results are quoted against. The cost of
unblocking a rule is the implementation and the test, not a re-baselining.

## 3. The 12, in three classes

### Class A — structural fallback. **Unblocked.**

| Rule | Component it adds |
| --- | --- |
| `counting.nolo.lead_suit_with_most_unaccounted_higher.v1` | `unaccounted_higher_count` |
| `counting.nolo.avoid_retaining_certain_winner.v1` | `shed_certain_winner` |

Each inserts exactly one named component above the reactive base, in the pattern
`partner_aware.partner_layout` already uses for its disableable rules. Disabling
does not insert the component, so the mode falls back to the layout of
`reactive_contract_v1` — a real, shipped, measured profile rather than an
invented state. Both the layout and the value insertion are gated together,
because the score vector must stay the same length as the component names.

Measured after the change, over 208 NOLO trick-play decisions from 24 deals:
both ablations play legally throughout, and they **change the selected action**
in 3.8% and 1.0% of decisions respectively. That matters, because T1 found three
of the four previously-ablatable rules were entirely inert — 0.0% divergence over
44,000 decisions. These two are not.

### Class B — shared components under disjoint conditions. **Still blocked, and now understood.**

`reactive.nolo.discard_highest_liability.v1`,
`reactive.nolo.forced_win_position_rule.v1`,
`reactive.nolo.lead_lowest_from_shortest_suit.v1`,
`reactive.nolo.prefer_safe_loss.v1`,
`reactive.rami.cheapest_current_winner.v1`,
`reactive.rami.lead_high_from_best_suit.v1`,
`reactive.rami.preserve_strength_when_losing.v1`

These are base components, and the obstacle is sharper than "no fallback": **they
share components under disjoint conditions**. `cheapest_current_winner` applies
when an opponent holds the trick and `preserve_strength_when_losing` when nothing
can take it, and both express themselves through `rank_cost` in
`RAMI_FOLLOW_LAYOUT`. A component-name mask cannot separate them, so the
neutralisation has to happen inside the component computation, scoped to each
rule's own condition.

That is seven separate careful edits to the production incumbent's scoring path.
The fallback semantics are settled by section 1; what remains is implementation
risk, and it should be done one rule at a time with a divergence measurement for
each, not in one change.

### Class C — thresholds and vetoes. **Blocked on a semantic question, not a mechanism.**

`show.simple.rami_strength_threshold.v1`, `show.simple.nolo_suitability_veto.v1`,
`show.simple.lowest_eligible_colour_card.v1`

Section 1 does not answer these. "Declare RAMI only when strength reaches the
threshold" has no neutral removal: disabling it could mean always declare RAMI,
never declare it, or declare at a threshold of zero, and those are three
different policies with three different meanings. The same is true of the NOLO
veto. Until somebody decides *which*, these are not blocked on code.

The honest reading is that Class C rules are not "assumptions with a missing
switch" but **parameters whose ablation is ill-defined**. A threshold is better
studied by varying it than by removing it, and the profile already exposes it as
a parameter.

## 4. What this changes

Two of twelve are unblocked, and both turn out to be decisive rather than inert,
which is a better hit rate than the previously-ablatable four managed. More
usefully, the remaining ten are no longer an undifferentiated wall: seven are a
known, bounded implementation job with the semantics already settled, and three
should probably never have been counted as ablatable assumptions at all.

If Class C is reclassified, the real figure is **10 unvalidated strategic rules
with a defined ablation route, of which 2 are done** — rather than "12 blocked,
no route".
