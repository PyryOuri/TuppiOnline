# Phase 6 architecture

Phase 6 closes the Phase 5 classical-search programme and tests one learned
policy path. The first milestone is supervised imitation of the frozen
`partner_aware_v1` policy. The second milestone is conditional CTDE/self-play.

The deployment actor is one shared seat-relative network. It receives only the
acting seat's formal `PlayerObservation` and its legal action tuple. Physical
seats are rotated into self, left opponent, partner, and right opponent roles.
The actor never receives `MatchState`, `DealState`, a complete deal, evaluator
labels, fixture identifiers, or critic features.

The optional learning package is isolated under `src/tuppi_learning/`.
Importing the rules, engine, frozen agents, evaluator, exact layer, search
layer, or belief layer does not require PyTorch. Large datasets and weights are
research artifacts under `/Users/pyryouri/Developer/TuppiRuns/phase6`, never
Git-tracked project files.

The centralized critic is training-only. It may consume a private-state feature
vector assembled by an RL environment, but deployment uses the actor alone.
The authoritative objective remains complete-match terminal win/loss from the
candidate team's perspective. No rules or evaluator semantics are changed.
