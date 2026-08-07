"""Decomposing where PIMC and the reference policy disagree.

Three descriptive instruments over the frozen corpus:

**Showing decomposition.** On identical showing observations, classify every
PIMC/reference disagreement by which contract each chose. This is the sharp test of
the Phase 5C finding that PIMC declares RAMI more often: it attributes the elevated
rate to specific decisions rather than inferring it from a match-level aggregate.

**Card-play decomposition.** The same for trick play, sliced by the features that
distinguish plausible mechanisms - declarer versus defender, lead versus follow,
whether the partner currently holds the trick, whether PIMC overtakes a winning
partner, and whether it spends a high card where the reference spends a low one.

**Rollout mismatch.** PIMC values an action assuming the *rollout policy* plays every
later turn. This measures how wrong that assumption is against what actually
happened, by replaying the assumed continuation from the same position and comparing
it action-by-action with the realized one.

All three are **descriptive**. A disagreement is not an error, a divergence is not a
cause, and none of these can establish that the mechanism they describe produced the
Phase 5C loss. They narrow where to look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    DealState,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    apply_action,
    observation_for,
)
from tuppi_rules import Contract, team_for_seat

from .corpus import CorpusPosition, DecisionCorpus
from .errors import SearchError


DECOMPOSITION_SCHEMA_VERSION = "tuppi.search.pimc_decomposition.v1"


class ShowingDisagreement(StrEnum):
    SAME_ACTION = "same_action"
    SAME_CONTRACT_DIFFERENT_CARD = "same_contract_different_card"
    PIMC_RAMI_REFERENCE_NOLO = "pimc_rami_reference_nolo"
    PIMC_NOLO_REFERENCE_RAMI = "pimc_nolo_reference_rami"


def classify_showing(
    pimc: ShowAction, reference: ShowAction
) -> ShowingDisagreement:
    if pimc == reference:
        return ShowingDisagreement.SAME_ACTION
    if pimc.declared_contract is reference.declared_contract:
        return ShowingDisagreement.SAME_CONTRACT_DIFFERENT_CARD
    if pimc.declared_contract is Contract.RAMI:
        return ShowingDisagreement.PIMC_RAMI_REFERENCE_NOLO
    return ShowingDisagreement.PIMC_NOLO_REFERENCE_RAMI


def showing_decomposition(corpus: DecisionCorpus) -> dict[str, object]:
    """Classify every showing disagreement in the corpus."""

    positions = corpus.showing
    if not positions:
        raise SearchError("the corpus contains no showing position")
    counts: dict[str, int] = {item.value: 0 for item in ShowingDisagreement}
    by_position: dict[str, dict[str, int]] = {}
    pimc_rami = reference_rami = 0
    for position in positions:
        pimc = _action_from_id(position.pimc_action_id, position.observation)
        reference = _action_from_id(
            position.reference_action_id, position.observation
        )
        label = classify_showing(pimc, reference).value
        counts[label] += 1
        # Showing order R0..R3 measured from the forehand, which is the only
        # position label the ruleset gives a showing decision.
        offset = (position.observation.observing_seat - position.observation.forehand) % 4
        bucket = by_position.setdefault(
            f"R{offset}",
            {item.value: 0 for item in ShowingDisagreement} | {"positions": 0},
        )
        bucket[label] += 1
        bucket["positions"] += 1
        pimc_rami += int(pimc.declared_contract is Contract.RAMI)
        reference_rami += int(reference.declared_contract is Contract.RAMI)
    total = len(positions)
    return {
        "by_showing_position": dict(sorted(by_position.items())),
        "classification_counts": counts,
        "classification_rates": {
            key: round(value / total, 6) for key, value in counts.items()
        },
        "interpretation": (
            "Descriptive. A contract flip is the only showing change that can move a "
            "match: the shown card is public but changes no contract, leader, or "
            "trick. Rates here attribute the Phase 5C declaration gap to specific "
            "decisions; they do not establish that it caused the loss."
        ),
        "pimc_rami_declaration_rate": round(pimc_rami / total, 6),
        "reference_rami_declaration_rate": round(reference_rami / total, 6),
        "rami_rate_difference": round((pimc_rami - reference_rami) / total, 6),
        "schema_version": DECOMPOSITION_SCHEMA_VERSION,
        "showing_positions": total,
    }


def _action_from_id(action_id: str, observation: PlayerObservation):
    """Recover the action object a canonical id refers to.

    Looked up inside the observation's own legal-action set, so an id that does not
    correspond to a legal action raises instead of being reconstructed.
    """

    from .random import canonical_action_id

    for action in observation.legal_actions:
        if canonical_action_id(action) == action_id:
            return action
    raise SearchError(f"action {action_id!r} is not legal in this observation")


def _play_slices(
    position: CorpusPosition, pimc: PlayCardAction, reference: PlayCardAction
) -> tuple[tuple[str, str], ...]:
    """Feature slices that distinguish candidate card-play mechanisms."""

    observation = position.observation
    leading = not observation.current_trick
    slices: list[tuple[str, str]] = [
        ("contract", position.contract or "unresolved"),
        ("role", position.role),
        ("stage", position.stage),
        ("lead_or_follow", "lead" if leading else "follow"),
        ("partner_holds_trick", str(position.partner_holds_trick).lower()),
        ("feasible_band", position.feasible_band),
        ("legal_action_count", str(position.legal_action_count)),
        ("inferred_void_count", str(_void_count(observation))),
    ]
    if position.partner_holds_trick:
        # "Overtakes a winning partner" is the specific behaviour Phase 4's
        # secure-decisive-trick rule exists for, so it gets its own slice.
        beats = _beats_current_best(observation, pimc.card)
        reference_beats = _beats_current_best(observation, reference.card)
        slices.append(
            (
                "overtakes_winning_partner",
                f"pimc={str(beats).lower()}_reference={str(reference_beats).lower()}",
            )
        )
    slices.append(
        (
            "rank_direction",
            "pimc_higher"
            if pimc.card.rank.value > reference.card.rank.value
            else (
                "pimc_lower"
                if pimc.card.rank.value < reference.card.rank.value
                else "equal_rank"
            ),
        )
    )
    slices.append(
        (
            "suit_choice",
            "same_suit" if pimc.card.suit is reference.card.suit else "different_suit",
        )
    )
    return tuple(slices)


def _void_count(observation: PlayerObservation) -> int:
    """How many suit voids public play has proven, across the other three seats."""

    from tuppi_exact import HardConstraintModel

    model = HardConstraintModel.build(observation)
    return sum(
        len(model.void_suits[seat])
        for seat in range(4)
        if seat != observation.observing_seat
    )


def _beats_current_best(observation: PlayerObservation, card) -> bool:
    if not observation.current_trick:
        return False
    led = observation.current_trick[0].card.suit
    best = max(
        (
            play.card.rank.value
            for play in observation.current_trick
            if play.card.suit is led
        ),
        default=0,
    )
    return card.suit is led and card.rank.value > best


def card_play_decomposition(corpus: DecisionCorpus) -> dict[str, object]:
    """Slice trick-play disagreement by the features that separate mechanisms."""

    positions = corpus.trick_play
    if not positions:
        raise SearchError("the corpus contains no trick-play position")
    grouped: dict[str, dict[str, dict[str, int]]] = {}
    disagreements = 0
    for position in positions:
        pimc = _action_from_id(position.pimc_action_id, position.observation)
        reference = _action_from_id(
            position.reference_action_id, position.observation
        )
        disagrees = pimc != reference
        disagreements += int(disagrees)
        for name, value in _play_slices(position, pimc, reference):
            bucket = grouped.setdefault(name, {}).setdefault(
                value, {"disagreements": 0, "positions": 0}
            )
            bucket["positions"] += 1
            bucket["disagreements"] += int(disagrees)
    return {
        "by_slice": {
            name: {
                value: {
                    **counts,
                    "disagreement_rate": round(
                        counts["disagreements"] / counts["positions"], 6
                    ),
                }
                for value, counts in sorted(values.items())
            }
            for name, values in sorted(grouped.items())
        },
        "disagreement_rate": round(disagreements / len(positions), 6),
        "disagreements": disagreements,
        "interpretation": (
            "Descriptive slices, not causes. A disagreement with the reference "
            "policy is not an error: the reference is a transparent heuristic, not "
            "an optimum. Slices with an unusually high disagreement rate indicate "
            "where the two policies differ most, which is where a mechanism would "
            "have to act."
        ),
        "schema_version": DECOMPOSITION_SCHEMA_VERSION,
        "trick_play_positions": len(positions),
    }


# ------------------------------------------------------------ rollout mismatch


@dataclass(frozen=True, slots=True)
class MismatchRecord:
    """How far the assumed continuation matched the realized one."""

    position_id: str
    partner_kind: str
    assumed_actions: int
    matched_prefix: int
    matched_fraction: float
    first_divergence_index: int | None
    first_divergence_seat: int | None
    first_divergence_is_root_team: bool | None
    contract: str | None
    stage: str
    schema_version: str = field(
        default=DECOMPOSITION_SCHEMA_VERSION, init=False
    )

    def to_data(self) -> dict[str, object]:
        return {
            "assumed_actions": self.assumed_actions,
            "contract": self.contract,
            "first_divergence_index": self.first_divergence_index,
            "first_divergence_is_root_team": self.first_divergence_is_root_team,
            "first_divergence_seat": self.first_divergence_seat,
            "matched_fraction": round(self.matched_fraction, 6),
            "matched_prefix": self.matched_prefix,
            "partner_kind": self.partner_kind,
            "position_id": self.position_id,
            "stage": self.stage,
        }


def _continuation_actions(
    state: DealState, *, builders, limit: int
) -> list[tuple[int, str]]:
    """Play a deal forward with the given per-seat builders, recording actions.

    Returns ``(seat, action_id)`` pairs. Cards are recorded as canonical action ids,
    which name only cards the acting seat played - the same information a public
    event log carries.
    """

    from .random import canonical_action_id

    agents = tuple(builders[seat](seat) for seat in range(4))
    recorded: list[tuple[int, str]] = []
    working = state
    while not working.complete and len(recorded) < limit:
        actor = working.current_actor
        action = agents[actor].choose_action(observation_for(working, actor))
        recorded.append((actor, canonical_action_id(action)))
        working = apply_action(working, action)
    return recorded


def rollout_mismatch(
    corpus: DecisionCorpus,
    *,
    pimc_profile_key: str = "uniform_feasible_pimc_small_v1",
    limit: int = 12,
    positions_limit: int = 32,
    progress=None,
) -> dict[str, object]:
    """Compare the assumed rollout continuation with realized continuations.

    Three realized continuations are compared against the one PIMC assumed:

    ``reference_partner``
        every seat plays the frozen rollout policy - this is exactly what PIMC
        assumed, so it is the control and must match perfectly;
    ``pimc_partner``
        the root partnership plays PIMC and the opponents play the reference;
    ``all_pimc``
        every seat plays PIMC.

    The restricted truth channel supplies the real state, because a continuation can
    only be replayed from a real position. That makes this a **perfect-information
    diagnostic**, and it is labelled as one; nothing here feeds a deployable
    decision.
    """

    from .evaluation import phase5d_a_agent_builder
    from .registry import build_agent

    reference = phase4_specifications_by_profile_key()[
        corpus.reference_policy_key
    ]

    def reference_builder(seat: int):
        return construct_agent(reference, seat=seat)

    pimc_builder = phase5d_a_agent_builder(pimc_profile_key)
    del build_agent

    selected = corpus.trick_play[:positions_limit]
    if not selected:
        raise SearchError("no trick-play position available for mismatch analysis")

    records: list[MismatchRecord] = []
    for index, position in enumerate(selected):
        real = corpus.restricted_truth(position.position_id).deal_state
        root_seat = position.observation.observing_seat
        partner = position.observation.partner_seat
        assumed = _continuation_actions(
            real, builders={seat: reference_builder for seat in range(4)}, limit=limit
        )
        designs = {
            "reference_partner": {seat: reference_builder for seat in range(4)},
            "pimc_partner": {
                seat: (pimc_builder if seat in (root_seat, partner) else reference_builder)
                for seat in range(4)
            },
            "all_pimc": {seat: pimc_builder for seat in range(4)},
        }
        for kind, builders in designs.items():
            realized = _continuation_actions(real, builders=builders, limit=limit)
            matched = 0
            for left, right in zip(assumed, realized):
                if left != right:
                    break
                matched += 1
            diverged = matched < min(len(assumed), len(realized))
            seat = realized[matched][0] if diverged and matched < len(realized) else None
            records.append(
                MismatchRecord(
                    position_id=position.position_id,
                    partner_kind=kind,
                    assumed_actions=len(assumed),
                    matched_prefix=matched,
                    matched_fraction=matched / len(assumed) if assumed else 1.0,
                    first_divergence_index=matched if diverged else None,
                    first_divergence_seat=seat,
                    first_divergence_is_root_team=(
                        None
                        if seat is None
                        else team_for_seat(seat) is team_for_seat(root_seat)
                    ),
                    contract=position.contract,
                    stage=position.stage,
                )
            )
        if progress is not None:
            progress(index + 1, len(selected))

    by_kind: dict[str, dict[str, object]] = {}
    for kind in ("reference_partner", "pimc_partner", "all_pimc"):
        subset = [item for item in records if item.partner_kind == kind]
        fractions = [item.matched_fraction for item in subset]
        diverged = [item for item in subset if item.first_divergence_index is not None]
        root_team = [
            item for item in diverged if item.first_divergence_is_root_team
        ]
        by_kind[kind] = {
            "diverged_positions": len(diverged),
            "first_divergence_in_root_team": len(root_team),
            "mean_first_divergence_index": (
                round(
                    math.fsum(item.first_divergence_index for item in diverged)
                    / len(diverged),
                    4,
                )
                if diverged
                else None
            ),
            "mean_matched_fraction": round(
                math.fsum(fractions) / len(fractions), 6
            ),
            "positions": len(subset),
        }
    return {
        "assumed_continuation": (
            f"every seat plays {corpus.reference_policy_key}, which is exactly what "
            "the PIMC rollout assumes"
        ),
        "by_partner_kind": by_kind,
        "horizon_actions": limit,
        "interpretation": (
            "Descriptive. reference_partner is the control and must match perfectly, "
            "because it is the assumption itself. The gap between it and the other "
            "two measures how wrong PIMC's continuation assumption is when its "
            "partner is another PIMC instance - which is the situation in a "
            "homogeneous team. It cannot establish causality on its own."
        ),
        "label": "perfect_information_diagnostic",
        "pimc_profile_key": pimc_profile_key,
        "positions": len(selected),
        "records": [item.to_data() for item in records],
        "schema_version": DECOMPOSITION_SCHEMA_VERSION,
    }
