# Information-state node identity

The Phase 5D-B node key is `rootinfo:sha256:...` over the observable state that
can affect a root-player decision:

- root hand and legal action order;
- contract, declarer, first leader, dealer and forehand;
- current actor, ordered current trick and completed public tricks;
- public shown cards and public voids witnessed by trick play;
- team trick totals, match score, root seat/team and partner seat;
- ruleset and observation schema versions.

It excludes `match_ref`, `deal_ref`, fixture IDs, true deal IDs, sampled-world IDs,
simulation indices, worker indices, output paths, timestamps, and every hidden
hand allocation. Two engine-validated hypothetical states that project to the
same root observation therefore resolve to the same node, even when their
hidden hands differ. A changed public trick or changed root hand produces a
different key.

The existing Phase 5C seed digest remains unchanged. It serves the old PIMC
protocol and intentionally retains public match/deal coordinates. The stricter
Phase 5D-B key is separate so introducing node sharing cannot silently rewrite
any Phase 5C identity.

## Projection contract

The key is calculated after `observation_for` has projected a hypothetical
`DealState` to the original root seat. The projection is the security boundary:
the tree code never receives a second argument containing the sampled world or
the full state. The node constructor enumerates actions from that observation
in the engine's canonical order and stores only their canonical action IDs. If a
later simulation reaches the same key with a different legal-action tuple, the
search fails as a tree invariant violation rather than silently combining
incompatible nodes.

Public void information is derived from witnessed lead/follow events in the
public trick history. It is not reconstructed from the hidden assignment and it
does not call the Phase 5B constraint model while the showing policy is being
run. Consequently, two hidden worlds can differ in every still-unseen card and
still merge, while a changed public lead, completed trick, score, shown-card
fact, or root hand necessarily changes the identity. This is the intended
behavioural equivalence relation, not a serialization of the complete deal.

The identity is used for both the deterministic decision seed and the tree map.
It deliberately omits output paths, process/worker coordinates, timestamps,
fixture labels, and match/deal references. A caller may therefore replay a
decision from an equivalent observation in a different evaluation stream
without allowing the stream metadata to split the information set. The tree is
nevertheless ephemeral: the key is not a persistent player memory and no node
survives submission of the real action or the end of the deal.
