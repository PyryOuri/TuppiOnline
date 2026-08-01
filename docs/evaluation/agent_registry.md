# Agent and team registry

## Agent specifications

An `AgentSpecification` is immutable and content addressed. Its stable ID is
derived from:

- agent family and configuration version;
- implementation reference;
- compatible ruleset and observation schema IDs;
- deterministic or seeded-stochastic classification;
- explicit seed policy;
- canonical configuration and its digest;
- optional model/checkpoint ID and search budget; and
- optional partner-convention ID.

The human description is retained but does not define configuration identity.
Two parameter sets therefore cannot share an agent ID merely because their
display name is the same. Paths and object reprs never participate.

Seeded agents must use `derived_per_entry_seat`; deterministic agents must use
`none`. The registry is sorted by agent ID, rejects duplicates, and has its own
digest. Evaluation configurations embed the full registry content and digest.

## Team specifications

A team contains an ordered pair of component agent IDs corresponding to the
two partner roles before schedule transformations. Repeating an ID represents
a homogeneous team; two IDs represent a heterogeneous team. Partner convention
is explicit. Component order and convention affect the team ID; description
does not.

`shared_instances=false` is mandatory. Even a homogeneous team receives two
separate runtime objects, and all four seat objects are reconstructed for every
schedule entry. A future shared-state protocol would require an explicit safe
design before this field could be enabled.

## Phase 3 baseline catalog

The built-in registry contains only mechanical evaluator fixtures:

- first action in the engine's canonical legal order;
- lowest legal card;
- highest legal card;
- SHA-256-counter seeded random legal action; and
- configurable rules-valid RAMI/NOLO show selection followed by ordered legal
  card play.

The construction layer also supports explicit fixed scripts for tests and
failure fixtures. All choices flow through `PlayerObservation.legal_actions`;
an invalid scripted action is recorded as failure, never replaced.

These policies exist to validate the arena. Their names and cross-play results
are not claims of expert play, rankings, or transitive strategic strength. No
model/checkpoint or search budget is used by the built-in Phase 3 catalog.
