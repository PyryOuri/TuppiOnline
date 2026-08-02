# Phase 4 baseline profiles

Eight profiles are registered: five ladder rungs and three ablation variants.
A profile is the complete behavioural configuration of one policy, and it is
content-addressed, so any behaviourally material change mints a new
`profile_id` and therefore a new `agent_id`.

## Why no agent here is described as an expert

Nothing in this package has been validated by a Tuppi expert, compared against
expert play, or tuned against any target. The thresholds are round numbers
chosen so that the rule they gate actually fires often enough to be measurable.
Provenance labels record where each rule came from, and two labels are reserved
and unused: `expert_validated` (no expert validation has happened) and
`simulation_validated` (reserved for rules that survive a preregistered
controlled ablation, which Phase 4 only sets up). The rule catalogue is
machine-checked to contain neither label.

The ladder is ordered by **capability**, not by measured strength: each rung is
a strict superset of the rules below it. Whether a larger capability set plays
better is exactly what `docs/agents/phase4_evaluation.md` measures, and where it
does not, the result is preserved.

## Registered profiles

| Profile key | Family | Showing | Convention | Agent ID | Profile ID |
| --- | --- | --- | --- | --- | --- |
| `legacy_heuristic_port_v1` | `legacy_heuristic_port` | `legacy_show_v1` | none | `agent:sha256:2bfd7d7a6f8b8481…` | `profile:sha256:07dc9fce59436441…` |
| `reactive_contract_v1` | `reactive_contract` | `simple_show_v1` | none | `agent:sha256:87e47923e5fbf050…` | `profile:sha256:9bcd8d1d4ac7ffa0…` |
| `public_counting_v1` | `public_counting` | `simple_show_v1` | none | `agent:sha256:87855eb185110bb4…` | `profile:sha256:16c94432f07ca1ec…` |
| `partner_aware_v1` | `partner_aware` | `simple_show_v1` | none | `agent:sha256:d8b426f1263c7ce3…` | `profile:sha256:c5e74faedbf001d9…` |
| `match_aware_v1` | `match_aware` | `simple_show_v1` | none | `agent:sha256:ff888a9b055a7836…` | `profile:sha256:70292f7676a00f40…` |
| `reactive_contract_legacy_show_v1` | `reactive_contract` | `legacy_show_v1` | none | `agent:sha256:12d4e6131b3d4e22…` | `profile:sha256:749d8c74e21e50ea…` |
| `partner_aware_legacy_convention_v1` | `partner_aware` | `simple_show_v1` | `legacy_min_information_show_v1` | `agent:sha256:3ec5a1ee4bdea413…` | `profile:sha256:65e77c16c6a5ce2e…` |
| `match_aware_no_match_features_v1` | `match_aware` | `simple_show_v1` | none | `agent:sha256:1bf0f1b5ed352398…` | `profile:sha256:e1ab77b3781a75d1…` |

The full identities, parameters, and rule sets are in
`examples/agents/heuristic_profiles.json`.

## The ladder

### 1. `legacy_heuristic_port_v1`

A faithful port of the useful public-information parts of the frozen legacy
heuristic. Uses the legacy RS/NHI expected-value showing decision and the legacy
RAMI and NOLO play branches. It has **no** public inference and **no**
partnership awareness - the frozen RAMI follow branch ignored who held the
trick, so the port can and does overtake its own partner. That is preserved on
purpose; see `docs/agents/legacy_port.md`.

### 2. `reactive_contract_v1`

The simple transparent contract-aware baseline. Uses only its own hand, the
current trick, seat relations, the contract, and the legal action set. It does
**not** use inferred voids, card counting, or match-score strategy.

- **RAMI:** avoid overtaking a partner who currently holds the trick; take with
  the cheapest currently winning card; otherwise play the lowest card; on lead,
  play the highest card of the best-scoring suit (high-card weight plus
  `rami_lead_length_bonus` times length).
- **NOLO:** prefer a card that cannot take the trick and, among those, the
  highest; when every legal card would win, purge the highest from the last seat
  and keep the trick cheap from an earlier seat; when void, discard by the
  ported liability table; on lead, play the lowest rank, breaking ties toward
  the shortest suit.

### 3. `public_counting_v1`

Reactive plus hard public inference. Adds one named component per rule:

- `certain_trick` on a RAMI lead - the highest unplayed card of a suit wins with
  certainty when led (mechanical, no trumps);
- `certainty` when following in RAMI - a card that no remaining seat can beat is
  preferred over a merely provisional winner;
- `unaccounted_higher_count` on a NOLO lead - a hard count, not a probability;
- `shed_certain_winner` when losing safely or discarding in NOLO - shed a card
  that no unplayed card can beat, because it is a guaranteed future trick.

### 4. `partner_aware_v1`

Public counting plus explicit partnership rules. Two are mechanical rather than
hypotheses:

- if no seat still to play can beat a partner's winning card, the partnership is
  certain to take the trick, so overtaking cannot add a trick;
- NOLO scores **team** trick totals, so once the partnership is certain to take
  a trick, which partner takes it cannot change the score - the agent therefore
  discards its highest liability instead of protecting its own trick count.

The convention-like rules (overtaking a beatable partner with a proven winner,
preferring or avoiding a suit the partner is publicly void in) are hypotheses
with stable IDs and are independently disableable.

### 5. `match_aware_v1`

Partner-aware plus deterministic rising-score rules. Phase 4 has no search and
no probability model, so match awareness is restricted to distinctions the
observation supports directly:

- **Showing overlay.** Up and within `match_protect_distance` (4) of 52: raise
  the RAMI threshold by `match_protect_threshold_bonus` (3.0), because every
  NOLO win pays at least 4 and reaches the target while a failed RAMI hands the
  opponents 8 per trick above six and resets the whole rise. Down and within
  `match_pressure_distance` (8) of the opponents' target: lower it by
  `match_pressure_threshold_discount` (2.0), because a win resets them whatever
  its margin.
- **Coasting.** Once the deal win is secured and further margin cannot move the
  match - the partnership is down, so a win only resets, or it is up and the
  smallest remaining win already reaches 52 - stop competing and play the lowest
  legal card.
- **Decisive trick.** Holding exactly six tricks in RAMI with a beatable partner
  on the trick, overtake with the cheapest winner even without proof, because
  crossing the 6/7 boundary changes the deal winner.

One rule was examined and deliberately **not** implemented: "deny the opponents'
terminal margin". In both contracts the opponents' points fall as the acting
partnership takes more tricks, which is already the direction ordinary play
takes, so a separate rule would change nothing. The negative result is recorded
in `match_aware.py` rather than shipped as a rule that does nothing.

## Showing profiles

### A. `legacy_show_v1` (legacy-derived)

Ports RS (`hcp + 0.5*long + 0.2*shape + 0.5*aces`) and NHI, the logistic
make/win estimates, and the Binomial(13, p) expected-value tables, which happen
to match `project_target_v1` scoring exactly. Declares RAMI when the RAMI
expected value reaches its minimum **and** exceeds the NOLO expected value by
`legacy_rami_ev_margin` (0.5). Shows the lowest eligible rank of the wanted
colour, breaking rank ties by legacy suit precedence.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `legacy_rami_ev_minimum_table` | 4.0 | RAMI bar at 0-0. |
| `legacy_rami_ev_minimum_protected` | 6.0 | Bar when own team is up with at least `legacy_protected_score`. |
| `legacy_rami_ev_minimum_pressured` | 3.0 | Bar when the opponents are up that high. |
| `legacy_protected_score` | 40 | The "large rise" threshold. |
| `legacy_rami_ev_margin` | 0.5 | Margin RAMI must beat NOLO by. |

All five are uncalibrated legacy constants. The profile rejects a configuration
where the protected bar is below the table bar, or the pressured bar above it.

### B. `simple_show_v1` (simple transparent)

Two explicit thresholds over a small set of documented hand descriptors, so no
two differently scaled scores are ever compared:

```text
rami_score = high_card_points + 0.5*aces + 0.25*controls + 0.5*max(0, longest - 4)
nolo_score = 1.5*low_cards + 3*voids + 2*singletons + 1*doubletons
             - 1.0*top_five - 0.5*honours
declare RAMI  <=>  rami_score >= simple_rami_threshold
                   and nolo_score <= simple_nolo_veto_threshold
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `simple_rami_threshold` | 15.0 | Minimum RAMI strength. |
| `simple_nolo_veto_threshold` | 2.0 | A hand this NOLO-suited withholds the RAMI declaration. |

Neither threshold is claimed to be optimal, or even good. The shown card is the
lowest eligible rank of the contract colour, breaking rank ties by canonical
`project_target_v1` suit order.

Both profiles obey the authoritative fallback hierarchy: eligible ranks are 3-9,
an off-colour eligible card is shown when no on-colour one exists, and the
`verbal_required` flag is derived by the ruleset rather than claimed.

## Profile configuration is strict

`HeuristicProfile` rejects unknown parameters, wrong types, out-of-range values,
showing parameters that belong to the other showing policy, a family that does
not support the requested showing policy, disabling a rule that is not part of
the profile, disabling a mechanical rule, and contradictory settings (a
protected RAMI bar below the table bar, a pressured bar above it, a protected
distance beyond the pressure distance, a partner convention ID without its rule,
or a match-state switch on a family that has none).

## Partner assumptions

Every rung is documented as assuming **no convention**: a partner's card is read
only through the public record and the scoring formulas, never through a private
meaning. `partner_aware_legacy_convention_v1` is the single exception and is
labelled `legacy_port`: the frozen implementation's card choice among equal
ranks depended on its hand sort order, and treating that as a convention makes
the assumption explicit, separately identified, and independently disableable.
It is not Finnish expert practice and must never be described as such.

Because the rules are fixed, two instances of *different* profiles are not
assumed to interpret each other's actions consistently. Heterogeneous pairings
are therefore evaluated, not assumed away: `partner_aware_v1` with
`reactive_contract_v1`, with `legacy_heuristic_port_v1`, and with a protocol
control all complete deals and matches in the test suite, and two heterogeneous
teams appear in cross-play.

## Protocol controls

The Phase 3 fixtures - first legal, lowest legal, highest legal, deterministic
seeded random, and fixed scripted - are re-exported through
`tuppi_agents.controls`, not reimplemented. Their specifications are
byte-identical to `tuppi_eval.registry.baseline_agent_specifications()`. They
are evaluator controls that establish a floor; they are not rungs of the ladder.
