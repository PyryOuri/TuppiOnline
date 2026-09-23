# `project_target_v3` rules decision table

`project_target_v3` is `project_target_v2` plus locked bids; see
`project_target_v3.md`. Every row of `project_target_v2_decisions.md` (and of
`project_target_v1_decisions.md`) applies to v3 unchanged.

| Domain | Authoritative v3 behaviour | Source / provenance | Normative test references |
| --- | --- | --- | --- |
| Bid visibility | All four bids are chosen blind; no seat sees any other bid, card or declaration, before showing resolves. Public during bidding: which seats have bid. | Owner decision 2026-09-23 (`TuppiAI/docs/LOCKED_BIDS_RULESET_REVIEW.md`) | `tests/engine/test_locked_bids_engine.py` |
| Reveal | At resolution the bids up to and including the first RAMI (all four if none) are revealed in seat order from the forehand. | Owner decision 2026-09-23 | same |
| Later bids | Bids after the first RAMI are never revealed, have no effect and are not stored. | Owner decision 2026-09-23 | same; server privacy tests |
| Legal bids and resolution | Unchanged from v1: card eligibility, colour rule, verbal fallbacks, first RAMI declares, all-NOLO is NOLO. | `project_target_v1` | v1 rules tests |
| Reference collection | Seat order, each seat blind; events `bid_locked` per bid, then `show_accepted` for each revealed bid before `contract_resolved`. | Implementation choice (same outcomes and information) | `tests/engine/test_locked_bids_engine.py` |
