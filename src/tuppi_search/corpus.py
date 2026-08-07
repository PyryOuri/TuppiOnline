"""A frozen, stratified corpus of decision positions.

Phase 5D-A needs to ask the same question of many positions repeatedly - "what does
PIMC choose here at each budget, and how does that differ from the reference?" -
without replaying whole matches each time. This module builds that corpus once, from
reference-agent play on a fresh development bank, and freezes it.

The privacy design is the important part
---------------------------------------

A corpus entry that carried the true hidden hands alongside the observation would be
one attribute access away from leaking them into a deployable decision. So the
corpus is **two structures, not one**:

:class:`CorpusPosition`
    The formal :class:`PlayerObservation` plus provenance and stratum labels. Every
    label is derived from the observation alone. This is what the search sees.

:class:`RestrictedTruth`
    The real :class:`DealState`, in a separate mapping keyed by position id, used
    only by the perfect-information oracle diagnostics.

Nothing in the deployable path takes a ``RestrictedTruth``, and
:mod:`tests.search.test_phase5d_corpus` asserts that a ``CorpusPosition`` exposes no
attribute holding an engine state and that its serialized form names no card the
observing seat cannot see.

Stratification
--------------

Positions are labelled by phase, contract, role, deal stage, partial-trick size,
whether the partner currently holds the trick, score state, feasible-assignment
count band, legal-action count, and whether PIMC disagrees with the reference. The
last one costs a PIMC evaluation per position, so it is computed once and stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayerObservation,
    apply_action,
    begin_explicit_deal,
    create_match,
    observation_for,
)
from tuppi_eval.serialization import content_digest
from tuppi_exact import HardConstraintModel, feasible_assignment_count
from tuppi_rules import MatchScore, team_for_seat

from .config import DEVELOPMENT_REFERENCE_POLICY
from .errors import SearchError
from .random import canonical_action_id, information_state_digest


CORPUS_SCHEMA_VERSION = "tuppi.search.decision_corpus.v1"

#: Spacing between the unforced card decisions one deal may contribute. Prime, and
#: larger than the usual per-deal cap, so the kept decisions land in different tricks
#: rather than in one cluster. The phase is rotated per deal instance in
#: :func:`build_corpus`, which is what makes the pooled stage distribution even.
_PLAY_STRIDE = 11


class DealStage(StrEnum):
    SHOWING = "showing"
    EARLY = "early"
    MIDDLE = "middle"
    LATE = "late"


class ScoreState(StrEnum):
    TABLE = "table"
    UP = "up"
    DOWN = "down"


class Role(StrEnum):
    DECLARER_TEAM = "declarer_team"
    DEFENDING_TEAM = "defending_team"
    NO_DECLARER = "no_declarer"


class FeasibleBand(StrEnum):
    """Coarse bands of the exact feasible-assignment count."""

    DETERMINED = "determined"
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"


def feasible_band(count: int) -> FeasibleBand:
    if count <= 1:
        return FeasibleBand.DETERMINED
    if count <= 12:
        return FeasibleBand.TINY
    if count <= 1_000:
        return FeasibleBand.SMALL
    if count <= 1_000_000:
        return FeasibleBand.MEDIUM
    if count <= 10**12:
        return FeasibleBand.LARGE
    return FeasibleBand.HUGE


def deal_stage(observation: PlayerObservation) -> DealStage:
    if observation.phase is EnginePhase.SHOWING:
        return DealStage.SHOWING
    completed = len(observation.completed_tricks)
    if completed <= 3:
        return DealStage.EARLY
    if completed <= 8:
        return DealStage.MIDDLE
    return DealStage.LATE


def score_state(observation: PlayerObservation) -> ScoreState:
    up = observation.match_score.up_team
    if up is None:
        return ScoreState.TABLE
    return (
        ScoreState.UP
        if up is team_for_seat(observation.observing_seat)
        else ScoreState.DOWN
    )


def role(observation: PlayerObservation) -> Role:
    if observation.declarer is None:
        return Role.NO_DECLARER
    declaring = team_for_seat(observation.declarer)
    own = team_for_seat(observation.observing_seat)
    return Role.DECLARER_TEAM if declaring is own else Role.DEFENDING_TEAM


def partner_holds_trick(observation: PlayerObservation) -> bool:
    """Whether the partner currently wins the partial trick.

    Derived from the public partial trick only. False when no trick is in progress,
    so the label means "partner is currently winning" rather than "partner is not
    losing". Only led-suit cards can win under ``project_target_v1``, which is why
    off-suit plays are skipped rather than compared by rank.
    """

    if not observation.current_trick:
        return False
    led = observation.current_trick[0].card.suit
    best_seat = observation.current_trick[0].seat
    best_rank = observation.current_trick[0].card.rank.value
    for play in observation.current_trick[1:]:
        if play.card.suit is led and play.card.rank.value > best_rank:
            best_seat, best_rank = play.seat, play.card.rank.value
    return best_seat == observation.partner_seat


@dataclass(frozen=True, slots=True)
class CorpusPosition:
    """One frozen decision position. Observation-only, by construction."""

    position_id: str
    observation: PlayerObservation
    stream_index: int
    deal_index: int
    decision_index: int
    information_state: str
    phase: str
    contract: str | None
    role: str
    stage: str
    score_state: str
    partial_trick_size: int
    partner_holds_trick: bool
    legal_action_count: int
    feasible_assignment_count: int
    feasible_band: str
    reference_action_id: str
    pimc_action_id: str
    pimc_disagrees_with_reference: bool
    schema_version: str = field(default=CORPUS_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.observation, PlayerObservation):
            raise SearchError("a corpus position wraps a PlayerObservation")
        if not self.position_id.startswith("pos:"):
            raise SearchError("position_id must carry the pos: prefix")

    @property
    def is_showing(self) -> bool:
        return self.phase == EnginePhase.SHOWING.value

    def strata(self) -> tuple[tuple[str, str], ...]:
        """The stratum labels used for reporting, as ordered pairs."""

        return (
            ("phase", self.phase),
            ("contract", self.contract or "unresolved"),
            ("role", self.role),
            ("stage", self.stage),
            ("score_state", self.score_state),
            ("partial_trick_size", str(self.partial_trick_size)),
            ("partner_holds_trick", str(self.partner_holds_trick).lower()),
            ("legal_action_count", str(self.legal_action_count)),
            ("feasible_band", self.feasible_band),
            ("disagrees", str(self.pimc_disagrees_with_reference).lower()),
        )

    def to_data(self) -> dict[str, object]:
        """Canonical summary. Carries labels and identities, never a hidden hand."""

        return {
            "contract": self.contract,
            "deal_index": self.deal_index,
            "decision_index": self.decision_index,
            "feasible_assignment_count": self.feasible_assignment_count,
            "feasible_band": self.feasible_band,
            "information_state": self.information_state,
            "legal_action_count": self.legal_action_count,
            "partial_trick_size": self.partial_trick_size,
            "partner_holds_trick": self.partner_holds_trick,
            "phase": self.phase,
            "pimc_action": self.pimc_action_id,
            "pimc_disagrees_with_reference": self.pimc_disagrees_with_reference,
            "position_id": self.position_id,
            "reference_action": self.reference_action_id,
            "role": self.role,
            "schema_version": CORPUS_SCHEMA_VERSION,
            "score_state": self.score_state,
            "stage": self.stage,
            "stream_index": self.stream_index,
        }


@dataclass(frozen=True, slots=True)
class RestrictedTruth:
    """The real state behind one corpus position. **Restricted.**

    Held in a separate mapping from the positions themselves so that no deployable
    code path can reach it by attribute access. Used only by the perfect-information
    oracle diagnostics, which are labelled as such.
    """

    position_id: str
    deal_state: DealState
    label: str = field(default="perfect_information_restricted", init=False)


@dataclass(frozen=True, slots=True)
class DecisionCorpus:
    """A frozen corpus plus its restricted truth channel."""

    positions: tuple[CorpusPosition, ...]
    truth: Mapping[str, RestrictedTruth]
    bank_id: str
    reference_policy_key: str
    pimc_profile_key: str
    schema_version: str = field(default=CORPUS_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.positions:
            raise SearchError("a corpus needs at least one position")
        if len({item.position_id for item in self.positions}) != len(self.positions):
            raise SearchError("corpus position ids must be unique")

    def __len__(self) -> int:
        return len(self.positions)

    @property
    def showing(self) -> tuple[CorpusPosition, ...]:
        return tuple(item for item in self.positions if item.is_showing)

    @property
    def trick_play(self) -> tuple[CorpusPosition, ...]:
        return tuple(item for item in self.positions if not item.is_showing)

    def restricted_truth(self, position_id: str) -> RestrictedTruth:
        """Fetch the real state for one position. Oracle diagnostics only."""

        if position_id not in self.truth:
            raise SearchError(f"no restricted truth for position {position_id!r}")
        return self.truth[position_id]

    @property
    def corpus_id(self) -> str:
        return "corpus:" + content_digest(
            {
                "bank_id": self.bank_id,
                "pimc_profile_key": self.pimc_profile_key,
                "position_ids": [item.position_id for item in self.positions],
                "reference_policy_key": self.reference_policy_key,
                "schema_version": CORPUS_SCHEMA_VERSION,
            }
        )

    def stratum_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for position in self.positions:
            for name, value in position.strata():
                counts.setdefault(name, {})
                counts[name][value] = counts[name].get(value, 0) + 1
        return {
            name: dict(sorted(values.items())) for name, values in sorted(counts.items())
        }

    def to_data(self) -> dict[str, object]:
        return {
            "bank_id": self.bank_id,
            "corpus_id": self.corpus_id,
            "pimc_profile_key": self.pimc_profile_key,
            "position_count": len(self.positions),
            "privacy_note": (
                "Positions carry formal observations and derived labels only. The "
                "real states live in a separate restricted channel used solely by "
                "labelled perfect-information diagnostics."
            ),
            "reference_policy_key": self.reference_policy_key,
            "schema_version": CORPUS_SCHEMA_VERSION,
            "showing_positions": len(self.showing),
            "stratum_counts": self.stratum_counts(),
            "trick_play_positions": len(self.trick_play),
        }


def build_corpus(
    *,
    showing_target: int = 256,
    trick_play_target: int = 512,
    streams: int = 96,
    deals_per_stream: int = 2,
    pimc_profile_key: str = "uniform_feasible_pimc_small_v1",
    reference_policy_key: str = DEVELOPMENT_REFERENCE_POLICY,
    score_states: tuple[tuple[int, int], ...] = ((0, 0), (32, 0), (0, 32), (48, 0)),
    trick_play_per_deal: int = 4,
    progress=None,
) -> DecisionCorpus:
    """Sample a frozen corpus from reference play on the Phase 5D-A corpus bank.

    Positions come from *reference* play, not PIMC play, so the corpus is not
    conditioned on PIMC's own trajectory - which would bias every subsequent
    comparison toward positions PIMC happens to reach.

    Two sampling decisions here are load-bearing rather than cosmetic, because the
    obvious implementation produces a corpus that cannot support the analyses.

    ``trick_play_per_deal`` bounds how many trick-play positions one deal may
    contribute. A single deal offers dozens of unforced card decisions, so filling the
    trick-play target in encounter order draws the whole corpus from one or two hands:
    an earlier build took all 96 of its trick-play positions from a *single* set of
    hands, which no amount of stratified reporting can repair. Which decisions are
    taken is also spaced by ``_PLAY_STRIDE`` with a per-hand rotating phase, so the
    sample lands in different tricks instead of always in the opening one.

    **One score state per hand.** Replaying the same hands at every score state
    multiplies cost fourfold while adding almost nothing: the reference policy
    ``partner_aware_v1`` has no match features, so its decision on identical hands is
    typically identical regardless of the score. Each hand therefore gets a single
    score state, rotated across hands, which spends the same budget on four times as
    many distinct deals and still balances the score-state strata in the pooled
    corpus.

    Positions within a deal remain clustered by construction - they share hands, and
    a deal's four showing decisions are not independent of one another. These
    decisions bound that clustering; they do not remove it, and the reported strata
    should be read with the distinct-hand count, not the position count, as the
    effective sample size.
    """

    from .evaluation import phase5d_a_corpus_bank
    from .registry import build_agent

    if showing_target <= 0 or trick_play_target <= 0:
        raise SearchError("corpus targets must be positive")
    if type(trick_play_per_deal) is not int or trick_play_per_deal <= 0:
        raise SearchError("trick_play_per_deal must be a positive integer")
    bank = phase5d_a_corpus_bank(stream_count=max(streams, 1))
    specification = phase4_specifications_by_profile_key()[reference_policy_key]

    positions: list[CorpusPosition] = []
    truth: dict[str, RestrictedTruth] = {}
    showing_kept = play_kept = 0
    total = streams * deals_per_stream
    done = 0

    for stream_index in range(streams):
        stream = bank.stream(stream_index)
        for deal_index in range(deals_per_stream):
            stream_deal = stream.deal(deal_index)
            done += 1
            if progress is not None:
                progress(done, total)
            if showing_kept >= showing_target and play_kept >= trick_play_target:
                continue
            # One score state per hand, rotated, so the budget buys distinct deals
            # rather than repeated replays of the same hands.
            score = score_states[(done - 1) % len(score_states)]
            state = create_match(
                initial_score=MatchScore(*score),
                initial_dealer=stream.initial_dealer,
                match_ref=f"corpus-{stream_index:04d}-{deal_index:02d}",
            )
            state = begin_explicit_deal(
                state,
                ExplicitDeal(dealer=stream.initial_dealer, hands=stream_deal.hands),
            )
            deal = state.active_deal
            decision_index = 0
            # Which unforced card decisions of *this* hand are eligible. The phase
            # rotates per hand so that, pooled over hands, the sample spreads across
            # tricks instead of always taking the opening ones - which would make
            # every trick-play stratum "early".
            play_seen = 0
            play_from_this_deal = 0
            offset = (done - 1) % _PLAY_STRIDE
            while not deal.complete:
                actor = deal.current_actor
                observation = observation_for(deal, actor)
                showing = observation.phase is EnginePhase.SHOWING
                unforced = len(observation.legal_actions) >= 2
                if showing:
                    keep = showing_kept < showing_target
                else:
                    if unforced:
                        play_seen += 1
                    keep = (
                        play_kept < trick_play_target
                        and play_from_this_deal < trick_play_per_deal
                        and (play_seen - 1) % _PLAY_STRIDE == offset
                    )
                # A forced decision teaches nothing about search: there is nothing to
                # choose, so PIMC and the reference must agree.
                if keep and unforced:
                    entry, real = _build_position(
                        observation=observation,
                        deal=deal,
                        stream_index=stream_index,
                        deal_index=deal_index,
                        decision_index=decision_index,
                        specification=specification,
                        pimc_profile_key=pimc_profile_key,
                        build_agent=build_agent,
                    )
                    positions.append(entry)
                    truth[entry.position_id] = real
                    if entry.is_showing:
                        showing_kept += 1
                    else:
                        play_kept += 1
                        play_from_this_deal += 1
                deal = apply_action(
                    deal,
                    construct_agent(specification, seat=actor).choose_action(
                        observation
                    ),
                )
                decision_index += 1
        if showing_kept >= showing_target and play_kept >= trick_play_target:
            break

    if not positions:
        raise SearchError("the corpus sampled no usable position")
    return DecisionCorpus(
        positions=tuple(positions),
        truth=MappingProxyType(truth),
        bank_id=bank.bank_id,
        reference_policy_key=reference_policy_key,
        pimc_profile_key=pimc_profile_key,
    )


def _build_position(
    *,
    observation: PlayerObservation,
    deal: DealState,
    stream_index: int,
    deal_index: int,
    decision_index: int,
    specification,
    pimc_profile_key: str,
    build_agent,
) -> tuple[CorpusPosition, RestrictedTruth]:
    model = HardConstraintModel.build(observation)
    count = feasible_assignment_count(model)
    reference_action = construct_agent(
        specification, seat=observation.observing_seat
    ).choose_action(observation)
    pimc_action = build_agent(
        pimc_profile_key, seat=observation.observing_seat
    ).choose_action(observation)
    digest = information_state_digest(observation)
    position_id = "pos:" + content_digest(
        {
            "deal_index": deal_index,
            "decision_index": decision_index,
            "information_state": digest,
            "schema_version": CORPUS_SCHEMA_VERSION,
            "stream_index": stream_index,
        }
    )
    entry = CorpusPosition(
        position_id=position_id,
        observation=observation,
        stream_index=stream_index,
        deal_index=deal_index,
        decision_index=decision_index,
        information_state=digest,
        phase=observation.phase.value,
        contract=(
            None if observation.contract is None else observation.contract.value
        ),
        role=role(observation).value,
        stage=deal_stage(observation).value,
        score_state=score_state(observation).value,
        partial_trick_size=len(observation.current_trick),
        partner_holds_trick=partner_holds_trick(observation),
        legal_action_count=len(observation.legal_actions),
        feasible_assignment_count=count,
        feasible_band=feasible_band(count).value,
        reference_action_id=canonical_action_id(reference_action),
        pimc_action_id=canonical_action_id(pimc_action),
        pimc_disagrees_with_reference=reference_action != pimc_action,
    )
    return entry, RestrictedTruth(position_id=position_id, deal_state=deal)
