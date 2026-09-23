# `project_target_v2` rules decision table

`project_target_v2` is `project_target_v1` plus the sooli subgame; see
`project_target_v2.md`. Every row of `project_target_v1_decisions.md` applies to v2 unchanged unless a sooli
is played.

| Domain | Authoritative v2 behaviour | Source / provenance | Normative test references |
| --- | --- | --- | --- |
| Sooli eligibility | Only in a RAMI deal, after showing, before any card is played; only the two defenders. | Project-owner specification 2026-09-24 | `tests/rules/project_target_v2/test_sooli.py` |
| Offer order | Defender `(declarer + 1) mod 4` first, then `(declarer + 3) mod 4`; first acceptance ends the offers; answers are public. | Owner answer 2026-09-24 | same |
| Exchange | Soolaaja gives one card first; partner, having seen it, returns one card (not the one received). Hidden from the RAMI pair. A shown card may be exchanged. | Owner answer 2026-09-24 | same |
| Dead hand | The sooli partner takes no further part; their hand is out of play and not revealed. | Owner specification | same |
| Card order in sooli | Ace low: A < 2 < ... < K, in sooli trick play only. | Owner specification | same |
| Play order | Declarer leads trick 1; each trick: leader, other RAMI player, soolaaja; the trick winner leads next. | Owner specification and answer | same |
| End and scoring | Soolaaja wins a trick: deal ends, RAMI pair 24. Soolaaja takes no trick in 13: soolaaja's team 24. | Owner specification | same |
| Match | The 24 points follow the ordinary rising-score transition (down-team win resets). | Owner answer 2026-09-24 | same |
