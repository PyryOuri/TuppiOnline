# Causal history reconstruction

At a decision point the public prefix is reconstructed from the observation in
this order: public showing actions, completed-trick plays, then the current
partial trick. The current action is absent by construction. There is no access
to later showing, later trick plays, match outcomes, or future void evidence.

For each candidate sampled from the Phase 5B exact sampler, the evaluator adds
the candidate's remaining cards back to that seat's publicly played cards to
form the initial hands. It then replays the prefix through the authoritative
engine. Before every historical action, `observation_for(state, actor)` creates
the actor's candidate formal observation. This supplies the exact hand size,
legal actions, public history, showing state, and match context that a frozen
policy would have seen.

The candidate state is private evaluation material. It is never serialized in
belief diagnostics. Replaying through the engine also validates card
conservation, showing fallback semantics, follow-suit legality, and trick
transitions. A hard-infeasible candidate fails before likelihood evaluation; a
behaviorally unlikely candidate remains possible with a finite smoothed model.

The root observer's own prior actions are omitted from the default score. A
caller can restrict scoring explicitly to partner or opponent physical seats for
ablation, but cannot supply a true hand or future event as a feature.
