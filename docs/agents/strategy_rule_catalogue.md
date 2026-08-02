# Phase 4 strategy-rule catalogue

Every heuristic rule and every weighted feature used by a Phase 4 policy is
listed here with a stable identifier and an explicit provenance. The machine
readable form is `examples/agents/strategy_rule_catalogue.json`, validated by
`schemas/agents/strategy_rule_catalogue.schema.json`; this document is
generated from the same source and is checked against it by
`tests/agents/test_documentation.py`.

## Provenance classes

| Class | Meaning |
| --- | --- |
| `mechanical` | Directly implied by `project_target_v1`. Not a strategic opinion. |
| `legacy_port` | Adapted from the frozen `Archive/tuppi_emulator_v9.py` implementation. |
| `generic_trick_taking_hypothesis` | Ordinary plain-suit trick-taking practice, untested here. |
| `project_hypothesis` | Invented for this project to make a distinction explicit and ablatable. |
| `owner_supplied` | Supplied by the project owner. Not used in Phase 4. |
| `expert_validated` | Reserved. **No Phase 4 rule carries this label**, because no expert validation has taken place. |
| `simulation_validated` | Reserved for rules that survive a preregistered controlled ablation. Phase 4 only sets those ablations up. |

A rule marked *independently disableable* can be switched off through
`disabled_rule_ids` in a profile, which changes the profile identity and
therefore the agent identity. Mechanical rules cannot be switched off: they are
consequences of the ruleset, not conventions.

## Score components are priorities, not weights

Candidate actions are compared as fixed-length lexicographic score vectors. The
*order* of the named components is the rule priority; a magnitude only matters
inside its own component. That is why Phase 4 exposes exactly one numeric play
weight (`rami_lead_length_bonus`, which trades length against high-card weight
inside a single component) and expresses everything else as component order or
as an on/off rule.

## Mechanical rules shared by every profile

### `common.play.differentiated_trick_reward.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** A policy compares candidate cards by trick value.
- **Action preference:** Take the sign of a trick's value from the contract and keep RAMI and NOLO on separate rule branches. The deal-point scale is exposed as +4 per trick for a RAMI declaring team, +8 for a RAMI defending partnership above the sixth trick, and -4 in NOLO. No policy may use one undifferentiated trick reward.
- **Rationale:** The scoring formulas award 4*(declarer tricks - 6), 8*(defender tricks - 6) and 4*(7 - fewer tricks); the sign and the scale genuinely differ.
- **Known limitations:** Marginal values are exact only away from the 6/7 boundary, where the swing is larger than one increment.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `common.play.legal_actions_only.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING, TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** A policy is asked for an action.
- **Action preference:** Consider only the actions present in PlayerObservation.legal_actions, in the engine's stable order.
- **Rationale:** The engine rejects illegal actions and never repairs them, so the legal set is the whole action space.
- **Known limitations:** None; this is a restatement of the rules.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `common.select.deterministic_maximum.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING, TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** More than one legal action remains after scoring.
- **Action preference:** Select the lexicographic maximum score vector; break ties by the lowest engine legal-action index.
- **Rationale:** A single documented tie-break makes the policy reproducible without depending on set iteration or object identity.
- **Known limitations:** The tie-break is arbitrary with respect to strength; it is chosen only for reproducibility.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `common.show.authoritative_fallback.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** A policy declares a contract during showing.
- **Action preference:** Show only a card allowed by project_target_v1 valid_show_cards; accept the derived verbal_required flag.
- **Rationale:** project_target_v1 restricts show ranks to 3-9 and defines an explicit off-colour and no-eligible-rank fallback hierarchy.
- **Known limitations:** project_target_v1 has no cardless verbal declaration, so the legacy 'declare with no card' branch cannot be reproduced.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`


## Showing rules

### `show.legacy.minimum_information_card.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy showing profile has chosen a contract.
- **Action preference:** Show the lowest eligible rank of the contract colour; break rank ties by the frozen legacy suit precedence (spades, hearts, diamonds, clubs).
- **Rationale:** The frozen policy revealed the lowest allowed rank of the wanted colour to minimise the information given away.
- **Known limitations:** Legacy allowed ranks 3-10 and the ace; project_target_v1 allows only 3-9, so the eligible set is narrower.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `reactive_contract_legacy_show_v1`

### `show.legacy.rising_score_threshold_adjustment.v1`

- **Contracts:** RAMI
- **Phase:** SHOWING
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy showing profile evaluates the rising score.
- **Action preference:** Require a higher RAMI expected value when the own partnership is up with at least the configured protected score, and a lower one when the opponents are up that high.
- **Rationale:** The frozen policy raised its RAMI bar to 6.0 to protect a large rise and lowered it to 3.0 to gamble for a reset.
- **Known limitations:** project_target_v1 is always played in rising mode, so the legacy flat-scoring branch is unreachable and its 3.0 base is retained only as a configurable parameter.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `reactive_contract_legacy_show_v1`

### `show.legacy.rs_nhi_expected_value.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** A policy using the legacy showing profile must declare.
- **Action preference:** Declare RAMI when the ported RAMI expected value reaches the minimum and exceeds the ported NOLO expected value by the configured margin; otherwise declare NOLO.
- **Rationale:** Ported verbatim from the frozen HeuristicPolicy: RS and NHI feed logistic make/win estimates, which feed a Binomial(13, p) expected value in the actual scoring tables.
- **Known limitations:** The logistic centres, scales and the Binomial trick-share abstraction are uncalibrated legacy constants; the frozen emulator also computed an unused base threshold, which the port omits as dead code.
- **Implementing profiles:** `legacy_heuristic_port_v1`, `reactive_contract_legacy_show_v1`

### `show.simple.lowest_eligible_colour_card.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING
- **Provenance:** `project_hypothesis`
- **Independently disableable:** no
- **Condition:** The simple showing profile has chosen a contract.
- **Action preference:** Show the lowest eligible rank of the contract colour; break rank ties by canonical project_target_v1 suit order.
- **Rationale:** Revealing the lowest legal card gives an opponent the least usable information about the rest of the hand.
- **Known limitations:** Whether minimum-information showing is actually best in this ruleset is untested.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_v1`

### `show.simple.nolo_suitability_veto.v1`

- **Contracts:** RAMI
- **Phase:** SHOWING
- **Provenance:** `project_hypothesis`
- **Independently disableable:** no
- **Condition:** The simple showing profile would otherwise declare RAMI.
- **Action preference:** Withhold the RAMI declaration when the NOLO suitability score exceeds the configured veto threshold.
- **Rationale:** A hand can be strong in high cards and still be a much better NOLO hand; two explicit thresholds avoid comparing two differently scaled scores.
- **Known limitations:** Both thresholds are uncalibrated.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_v1`

### `show.simple.rami_strength_threshold.v1`

- **Contracts:** RAMI
- **Phase:** SHOWING
- **Provenance:** `project_hypothesis`
- **Independently disableable:** no
- **Condition:** A policy using the simple showing profile must declare.
- **Action preference:** Declare RAMI only when high-card points plus ace, control and length bonuses reach the configured threshold.
- **Rationale:** A small, readable set of hand descriptors is easier to ablate than a calibrated formula and gives an honest floor.
- **Known limitations:** The threshold is uncalibrated and is not claimed to be optimal or even good.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_v1`


## `reactive_contract_v1` trick-play rules

### `reactive.nolo.discard_highest_liability.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The policy cannot follow the led suit in a NOLO deal.
- **Action preference:** Discard the highest-liability card by the ported liability table, preferring short suits on ties.
- **Rationale:** Ported from the frozen discard routine: aces and kings are the cards most likely to be forced to win a later trick.
- **Known limitations:** The liability weights are uncalibrated legacy constants.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.nolo.forced_win_position_rule.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** Every legal card would currently take the trick.
- **Action preference:** Play the highest such card when last to play, otherwise the lowest.
- **Rationale:** Ported from the frozen policy: the last seat cannot be overtaken, so it purges its largest liability; an earlier seat keeps the trick cheap so a later seat can still take it.
- **Known limitations:** The earlier-seat branch relies on an opponent or the partner actually overtaking.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.nolo.lead_lowest_from_shortest_suit.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** The policy is on lead in a NOLO deal.
- **Action preference:** Lead the lowest rank available; break rank ties toward the shortest own suit, then canonical suit order.
- **Rationale:** A low lead is unlikely to win the trick, and shortening a suit creates a void that lets the hand discard liabilities later.
- **Known limitations:** Creating a void can also force the partnership to win later tricks in other suits.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.nolo.prefer_safe_loss.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** At least one legal card cannot take the current trick.
- **Action preference:** Prefer a card that cannot take the trick, and among those the highest, shedding the largest safe liability.
- **Rationale:** In a misere contract a trick is a penalty, and a card that is safe now may be a forced winner later.
- **Known limitations:** Safety is provisional for any seat that is not last to play.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.rami.avoid_overtaking_partner.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** yes
- **Condition:** A partner currently holds the trick in a RAMI deal.
- **Action preference:** Prefer a card that does not take the trick from the partner, and among those prefer the lowest.
- **Rationale:** The partnership already holds the trick, so spending a higher card on it cannot add a trick.
- **Known limitations:** Provisional: a later opponent may still overtake the partner, and this rule does not look at who is still to play.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.rami.cheapest_current_winner.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** An opponent currently holds the trick in a RAMI deal.
- **Action preference:** Play the cheapest legal card that currently takes it.
- **Rationale:** Winning with the cheapest sufficient card preserves strength.
- **Known limitations:** Provisional for any seat that is not last to play; the trick can still be taken back.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.rami.lead_high_from_best_suit.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** The policy is on lead in a RAMI deal.
- **Action preference:** Score each own suit as its high-card weight plus the configured length bonus times its length, then lead the highest card of the best-scoring suit.
- **Rationale:** With no trump suit, top cards and length are the two ordinary sources of tricks; the length bonus makes their trade-off an explicit, ablatable profile weight.
- **Known limitations:** Ignores entries, opponent distribution and the value of keeping a high card for a later round. The weight is uncalibrated.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`

### `reactive.rami.preserve_strength_when_losing.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** No legal card currently takes the trick in a RAMI deal.
- **Action preference:** Play the lowest legal card.
- **Rationale:** A trick that cannot be won should cost as little as possible.
- **Known limitations:** Ignores discard signalling and future suit control.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`, `reactive_contract_legacy_show_v1`, `reactive_contract_v1`


## `legacy_heuristic_port_v1` trick-play rules

### `legacy.nolo.discard_liability_table.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port cannot follow the led suit in NOLO.
- **Action preference:** Discard by the frozen liability table, then a short-suit bonus, then the highest rank, then legacy suit precedence.
- **Rationale:** Ported verbatim from ``_nolo_discard_any``, including its use of full-hand suit lengths for the short-suit bonus.
- **Known limitations:** The liability weights (4, 3, 2, 1, 0.5, 0.25) are uncalibrated legacy constants.
- **Implementing profiles:** `legacy_heuristic_port_v1`

### `legacy.nolo.forced_win_position_rule.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port holds led-suit cards but none of them loses the trick.
- **Action preference:** Play the highest led-suit card when last to play, otherwise the lowest.
- **Rationale:** Ported verbatim: the last seat cannot be overtaken and purges its largest liability, while an earlier seat keeps the trick cheap so a later seat can still take it.
- **Known limitations:** The earlier-seat branch relies on some later seat actually overtaking.
- **Implementing profiles:** `legacy_heuristic_port_v1`

### `legacy.nolo.highest_losing_card.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port can follow suit and lose the trick.
- **Action preference:** Play the highest card of the led suit that still loses.
- **Rationale:** Ported verbatim from the frozen NOLO follow branch.
- **Known limitations:** The frozen branch considered only cards of the led suit, so a safe off-suit discard was never preferred while following.
- **Implementing profiles:** `legacy_heuristic_port_v1`

### `legacy.nolo.lead_lowest_exit_shortest_suit.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port is on lead in a NOLO deal.
- **Action preference:** Prefer an exit card of rank 2-4, choosing the lowest rank and then the shortest suit; otherwise the lowest rank overall.
- **Rationale:** Ported verbatim from the frozen NOLO lead branch.
- **Known limitations:** The 2-4 exit band is an uncalibrated legacy constant.
- **Implementing profiles:** `legacy_heuristic_port_v1`

### `legacy.rami.cheapest_winner_else_lowest.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port is following in a RAMI deal.
- **Action preference:** Play the cheapest card of the led suit that beats the current best; otherwise the lowest card of the led suit; otherwise the lowest legal card.
- **Rationale:** Ported verbatim from the frozen RAMI follow branch.
- **Known limitations:** The frozen branch ignored partnership state entirely, so the port can overtake its own partner.
- **Implementing profiles:** `legacy_heuristic_port_v1`

### `legacy.rami.lead_best_suit_highest_card.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `legacy_port`
- **Independently disableable:** no
- **Condition:** The legacy port is on lead in a RAMI deal.
- **Action preference:** Score each suit present in hand by honour weight plus a length bonus and a tiny length tiebreaker, then lead the highest card of the best suit.
- **Rationale:** Ported verbatim from the frozen RAMI lead branch.
- **Known limitations:** The 0.01-per-card term exists in the frozen code only to avoid selecting an empty suit.
- **Implementing profiles:** `legacy_heuristic_port_v1`


## `public_counting_v1` rules

### `counting.nolo.avoid_retaining_certain_winner.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** The policy may discard or safely lose in a NOLO deal.
- **Action preference:** Prefer to shed a card that is the highest unplayed card of its suit.
- **Rationale:** A card that no unplayed card can beat is a guaranteed future trick, which is exactly what a misere contract must avoid.
- **Known limitations:** Shedding a top card can also strip a suit and force later wins elsewhere.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`

### `counting.nolo.lead_suit_with_most_unaccounted_higher.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** no
- **Condition:** The policy is on lead in a NOLO deal.
- **Action preference:** Among the lowest-rank candidates, prefer the card with the most unaccounted higher cards in its suit.
- **Rationale:** The count of unaccounted higher cards is a hard public count, and a larger count means more cards that can take the trick instead of the leader.
- **Known limitations:** A count is not a probability; the rule makes no claim about how those cards are distributed.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`

### `counting.play.certain_winner_priority.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** The policy is following, an opponent holds the trick, and some legal card beats every led-suit card the remaining seats could still hold.
- **Action preference:** Prefer the cheapest such certain winner over a merely provisional winner.
- **Rationale:** Hard public inference proves that no remaining seat can hold a higher card of the led suit, so the trick cannot be taken back.
- **Known limitations:** Only as strong as the public record: an unaccounted higher card blocks the deduction even when nobody actually holds it.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`

### `counting.play.lead_certain_winner.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** The policy is on lead and holds the highest unplayed card of some suit.
- **Action preference:** Prefer leading that card.
- **Rationale:** project_target_v1 has no trump suit and only led-suit cards can win, so the highest unplayed card of a suit wins with certainty when it is led.
- **Known limitations:** Certain for this trick only; it says nothing about who leads the next one or about the rest of the deal.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`, `public_counting_v1`


## `partner_aware_v1` rules

### `partner.legacy.minimum_information_show.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** SHOWING
- **Provenance:** `legacy_port`
- **Independently disableable:** yes
- **Condition:** The optional legacy convention profile is enabled.
- **Action preference:** Show with legacy suit precedence rather than canonical suit order, reproducing the frozen implementation's implicit card choice among equal ranks.
- **Rationale:** The frozen policy's card choice depended on its hand sort order; treating that as a partnership convention makes the assumption explicit and separately testable.
- **Known limitations:** There is no evidence that any partner interprets this choice, and it must not be described as Finnish expert practice.
- **Implementing profiles:** `partner_aware_legacy_convention_v1`

### `partner.nolo.dump_liability_when_partner_certainly_wins.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** A partner holds the trick in a NOLO deal and no seat still to play can beat the partner's card.
- **Action preference:** Treat the trick as already conceded by the partnership and discard the highest-liability legal card.
- **Rationale:** NOLO scores team trick totals, so once the partnership is certain to take the trick the choice of card cannot change the team count. Individual trick counts are not scored.
- **Known limitations:** Ignores that taking the trick oneself would change who leads the next trick.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`

### `partner.nolo.prefer_leading_partner_void_suit.v1`

- **Contracts:** NOLO
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** yes
- **Condition:** The policy is on lead in a NOLO deal and the partner is publicly void in a candidate suit.
- **Action preference:** Prefer leading a suit the partner is publicly void in.
- **Rationale:** A void partner cannot be forced to win that trick and can discard a liability instead.
- **Known limitations:** Only voids proven by a public failure to follow are used, so the rule is silent early in a deal.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`

### `partner.rami.overtake_when_partner_beatable.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** yes
- **Condition:** A partner holds the trick, a seat still to play could beat it, and the policy holds a card that beats every such card.
- **Action preference:** Overtake with the cheapest certain winner.
- **Rationale:** Converting a beatable partner winner into an unbeatable one secures a trick the partnership would otherwise risk.
- **Known limitations:** Spends a high card on a trick the partner might have won anyway, and the deduction ignores how likely that is.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`

### `partner.rami.prefer_leading_suit_partner_can_follow.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `generic_trick_taking_hypothesis`
- **Independently disableable:** yes
- **Condition:** The policy is on lead in a RAMI deal and the partner is publicly void in some candidate suit.
- **Action preference:** Avoid leading a suit the partner is publicly void in.
- **Rationale:** A void partner cannot support the suit, so the lead is worth less to the partnership.
- **Known limitations:** A void partner can also discard usefully; the rule is a weak preference only.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`

### `partner.rami.protect_certain_partner_winner.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** no
- **Condition:** A partner holds the trick and no seat still to play can beat the partner's card.
- **Action preference:** Never overtake; play the lowest legal card.
- **Rationale:** The partnership is certain to take the trick, so any card spent on it is pure loss.
- **Known limitations:** Certainty depends on the public record; unaccounted higher cards defeat the deduction.
- **Implementing profiles:** `match_aware_no_match_features_v1`, `match_aware_v1`, `partner_aware_legacy_convention_v1`, `partner_aware_v1`


## `match_aware_v1` rules

### `match.play.coast_when_margin_worthless.v1`

- **Contracts:** NOLO, RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `mechanical`
- **Independently disableable:** yes
- **Condition:** The own partnership's deal win is already secured and extra margin cannot move the match: either the opponents hold the rising score, or the own minimum win already reaches the target.
- **Action preference:** Stop competing for further tricks and play the lowest legal card.
- **Rationale:** A deal win by the non-rising partnership resets the score to 0-0 and awards it nothing, so a 56-point win and a 4-point win have identical match value; and points beyond the target are discarded. In both cases the remaining tricks are worthless.
- **Known limitations:** Deliberately ignores tournament-style aggregate margin, which project_target_v1 does not score.
- **Implementing profiles:** `match_aware_v1`

### `match.play.secure_decisive_trick.v1`

- **Contracts:** RAMI
- **Phase:** TRICK_PLAY
- **Provenance:** `project_hypothesis`
- **Independently disableable:** yes
- **Condition:** The own partnership holds exactly six tricks, a partner currently holds the trick, and a seat still to play could beat the partner's card.
- **Action preference:** Overtake the partner with the cheapest winning card even when no card is a proven winner, instead of leaving the decisive trick at risk.
- **Rationale:** Crossing the 6/7 boundary changes the deal winner, which is worth far more than one increment of margin or one preserved high card.
- **Known limitations:** Deterministic and myopic: it looks only at the current trick and spends a card the partner might not have needed.
- **Implementing profiles:** `match_aware_v1`

### `match.show.protect_terminal_lead.v1`

- **Contracts:** RAMI
- **Phase:** SHOWING
- **Provenance:** `project_hypothesis`
- **Independently disableable:** yes
- **Condition:** The own partnership is up and within the configured protected distance of the target.
- **Action preference:** Raise the RAMI declaration threshold, preferring the reliable NOLO line.
- **Rationale:** At 48 points any NOLO win scores at least 4 and reaches 52, while a failed RAMI hands the opponents 8 per trick above six and destroys the whole accumulated rise.
- **Known limitations:** Reliability is asserted by rule, not estimated; the protected distance and the threshold bonus are uncalibrated.
- **Implementing profiles:** `match_aware_v1`

### `match.show.reset_opponent_rise.v1`

- **Contracts:** RAMI
- **Phase:** SHOWING
- **Provenance:** `project_hypothesis`
- **Independently disableable:** yes
- **Condition:** The opponents are up and within the configured pressure distance of the target.
- **Action preference:** Lower the RAMI declaration threshold.
- **Rationale:** A deal win resets the opponents to 0-0 whatever its margin, so the partnership should accept more variance to obtain one.
- **Known limitations:** A failed RAMI also accelerates the opponents; the trade-off is asserted, not computed.
- **Implementing profiles:** `match_aware_v1`

