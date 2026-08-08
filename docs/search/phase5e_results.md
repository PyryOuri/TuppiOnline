# Phase 5E results

Phase 5E implemented and evaluated `redeterminizing_ismcts_v1`, a narrow
multi-observer information-set search baseline. It is a root-evaluated,
single-tree experiment, not a full MO-ISMCTS equilibrium method. Every real
decision creates a fresh tree. The tree has separate information-state
namespaces for the four physical seats, and a non-root tree decision is
re-determinized from that acting seat's formal observation before its action is
selected. Only the selected legal card is applied to the authoritative parent
simulation.

## Frozen boundaries

Showing remains exactly the frozen `partner_aware_v1` policy. The search and
Phase 5B sampler are not entered during showing, and a conformance test compares
the selected action directly with the frozen agent. Trick-play fallback is also
`partner_aware_v1`. The primary configurations use the exact Phase 5B
uniform-feasible hidden-hand sampler, `match_transition_v1`, bounded `[-1, 1]`
utility, canonical action expansion, availability-aware UCT with `sqrt(2)`,
and no exact-tail solving. There is no nested independent search, persistent
tree, belief weighting, learned model, or self-play training.

The parent root-consistent world is never replaced by an observer-local world.
An observer-local assignment preserves the acting seat's hand and public facts;
it is used only to construct the acting observer's information state. The chosen
card must be legal in the parent state, otherwise the decision fails strictly.
Node keys contain only the formal observation, physical seat, and versioned
schema namespace. They exclude deal references, match references, hidden hands,
sample IDs, simulation IDs, worker IDs, and paths.

## Registered configurations

The separately registered Phase 5E agents are:

| Agent | Simulations | Configuration ID |
| --- | ---: | --- |
| `multi_observer_ismcts_smoke_v1` | 2 | `moismctscfg:sha256:3ce08aee5e6059f32cea18be6dfbc2c5cc06bd98c7ffa19164e19e652268ea4a` |
| `multi_observer_ismcts_small_v1` | 8 | `moismctscfg:sha256:f283c10c50b388cab93412e28661350cae41c381e52a0caff70a58d0aa37719a` |
| `multi_observer_ismcts_standard_v1` | 32 | `moismctscfg:sha256:4fe800e304cb6e8dbf4ad538aadd315cfa4506737013916d9cd1d57f92a4ecdd` |

The primary development profile is the eight-simulation profile. The
32-simulation profile was frozen for the complete-match comparison. The search
agent IDs are recorded in the Phase 5E registry snapshot and are distinct from
all Phase 4, Phase 5C, and Phase 5D-B identities.

## Independent structural oracle

The independent finite oracle in `tiny_multi_observer_reference.py` contains
two equally likely worlds. Under action A, a shared partner information set
must choose one action while the opponent can condition on its private signal.
Under B, the fixed payoff is `0.6`.

The results are:

| Method | A | B | Selected action |
| --- | ---: | ---: | --- |
| Clairvoyant PIMC | 1.0 | 0.6 | A |
| Root-only fixed rollout | 0.5 | 0.6 | A at the one-simulation prefix |
| Exact information-set policy | 0.5 | 0.6 | B |
| Independent multi-observer UCT | — | — | B at the four-simulation prefix |

The toy oracle is deliberately independent of the production search code. It
is the structural acceptance test for the observer-node distinction: PIMC may
choose incompatible partner actions separately by world, whereas a shared
partner information node must choose one contingent action. The production
implementation follows this same node ownership and re-determinization
protocol. The corrected production behavior corpus had one trick-play position
where multi-observer search agreed with the frozen reference while root-only UCT
did not, one where root-only UCT agreed with the reference while multi-observer
search did not, and one other classification. The corpus was not treated as a
strength estimate.

## Privacy, determinism, and semantic checks

Focused Phase 5E tests cover root determinization, acting-hand preservation,
observer-local sampling, node merging, public-state separation, action mapping,
strict illegal-action behavior, privacy-safe diagnostics, no nested search, and
showing delegation. The complete Phase 5D-C fast-state differential evidence
remains valid: 16,000 transition checks and 1,000 complete remainder checks had
zero discrepancies. Phase 5E reuses that validated `FastTrickState` path.

Two parent worlds with the same formal observer observation produce the same
observer information-state key and deterministic re-determinization sequence.
Changing public trick history produces a different key. Diagnostics contain no
sampled hands or hidden-world identifiers. Replaying a decision with the same
observation, seed, and profile produces identical action statistics and action.

The Phase 5D-B root-UCT registry digest remains
`sha256:853ce7a1f8fc6957ec54f0f18d20870a437b3a8d256c5b500bd64c894330094e`.
The Phase 4 and Phase 5C identity tests remain unchanged.

## Budget stability and performance

On the reused privacy-safe Phase 5D-A corpus, adjacent selected-action
agreement was:

| Budget transition | Agreement |
| --- | ---: |
| 2 to 8 | 0.833 |
| 8 to 32 | 1.000 |

The corrected full-tree standard profile was benchmarked on a representative
early trick-play position. A 32-simulation decision took approximately 1.48
seconds, traversed all 52 simulated card plays, created 1,632 information nodes
across the four seat namespaces, and performed 1,248 observer
re-determinizations. Fallback count was zero. This is approximately 21.7
simulations per second for this early position; late positions are cheaper but
still much slower than the Phase 5D-C root-only implementation because every
simulated observer decision now participates in the tree.

Using the measured 32-simulation decision latency and the prior development
match action distribution, a standard-budget complete match is projected to
take tens of minutes per leg and many hours for a 32-pair comparison. The
uncorrected traversal probe that was started before this semantic correction
was stopped and its artifact is not used as evidence. These are pure
decision-call measurements; CLI and JSON output are excluded.

## Complete-match feasibility

The corrected traversal was not evaluated on the sealed bank. A 32-pair
standard-budget comparison was not computationally practical after enforcing
the future-root-turn invariant: a single early decision already costs about
1.48 seconds, and every real match contains hundreds to thousands of decisions.
The earlier 32-stream artifact from the pre-correction traversal is explicitly
discarded because its fallback behavior did not satisfy the Phase 5E algorithm
contract. No strength estimate is claimed for the corrected standard agent.

The existing frozen Phase 5D-C result remains the relevant historical strength
comparison: root-only UCT lost all 32 unsealed pairs to the development
reference. Phase 5E's corrected implementation has not been substituted into
that result, and the sealed bank remains unopened.

## Heterogeneous diagnostic status

A 16-pair heterogeneous run was also started with the pre-correction traversal
and completed with one censored pair per arrangement. It is retained only as an
operational debugging record and is not evidence: its search did not keep later
root turns in the shared tree. The corrected implementation requires a new,
separate heterogeneous run after a feasible budget or execution optimization is
chosen.

## Decision gate

The result is **G4** at this corrected semantic boundary: the independent oracle
and focused tests validate the intended observer-consistent structure, but the
full-tree implementation is not yet computationally practical for a meaningful
complete-match strength comparison. The remaining strength question is
therefore open; the prior G2 conclusion from the pre-correction traversal is
withdrawn. The next phase should optimize observer-local constraint sampling,
public-inference construction, and compact tree transitions, or assess a
compiled kernel, before running a new strength bank. Belief weighting remains a
separate future identity and is not mixed into this result.

The next phase should compare observer-consistent search with explicitly
validated belief weighting and/or stronger partner/opponent modelling. Any such
change must receive a new algorithm and identity. The sealed promotion bank
should remain unopened until that branch has a preregistered, uncensored
development result.

Bulk benchmark and evaluation artifacts are under
`/Users/pyryouri/Developer/TuppiRuns/phase5e`, outside the repository. The
repository contains no hidden sampled worlds or bulk match output.
