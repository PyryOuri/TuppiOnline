"""Pure observation-only feature layer shared by every Phase 4 policy.

Every value here is derived from a single frozen :class:`PlayerObservation`.
The layer is a set of pure functions returning immutable dataclasses. It
contains no randomness, no hidden-state reconstruction, no probability, and no
assumption that an unaccounted card belongs to a specific player unless
:mod:`tuppi_agents.public_inference` proves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_engine import EnginePhase, PlayerObservation, ShowAction
from tuppi_rules import (
    MATCH_TARGET,
    SUIT_ORDER,
    Card,
    Contract,
    Rank,
    ShowAction as RulesShowAction,
    Suit,
    Team,
    card_color,
    contract_color,
    is_show_rank_eligible,
    opposing_team,
    team_for_seat,
    valid_show_cards,
)

from .errors import AgentsValidationError
from .ordering import canonical_card_order_key, require_observation
from .public_inference import PublicInference
from .trick_context import TrickContext, build_trick_context


FEATURES_SCHEMA_VERSION = "tuppi.agents.public_features.v1"

_HIGH_CARD_POINTS: dict[int, int] = {14: 4, 13: 3, 12: 2, 11: 1}
_TRICKS_PER_DEAL = 13


class VerbalFallbackCategory(StrEnum):
    """Which branch of the authoritative showing hierarchy applies."""

    DIRECT_COLOR_CARD = "direct_color_card"
    ELIGIBLE_OFF_COLOR = "eligible_off_color"
    NO_ELIGIBLE_RANK = "no_eligible_rank"


class MatchRole(StrEnum):
    """The acting partnership's position in the continuous rising score."""

    TABLE = "table"
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class HandDescriptors:
    """Generic rank and suit descriptors of the observing player's own hand."""

    card_count: int
    high_card_points: int
    aces: int
    kings: int
    control_cards: int
    top_five_count: int
    honour_count: int
    low_card_count: int
    exit_card_count: int
    dangerous_high_cards: int
    suit_lengths: tuple[int, int, int, int]
    longest_suit_length: int
    shortest_suit_length: int
    void_count: int
    singleton_count: int
    doubleton_count: int
    schema_version: str = field(default="tuppi.agents.hand_descriptors.v1", init=False)

    def suit_length(self, suit: Suit) -> int:
        if not isinstance(suit, Suit):
            raise AgentsValidationError("suit_length requires a Suit value")
        return self.suit_lengths[SUIT_ORDER.index(suit)]


@dataclass(frozen=True, slots=True)
class ShowingContext:
    """Immutable showing-phase facts, including eligibility and fallback class."""

    observing_seat: int
    dealer: int
    forehand: int
    showing_position: int
    previous_show_actions: tuple[RulesShowAction, ...]
    previous_nolo_count: int
    rami_already_resolved: bool
    eligible_rami_show_cards: tuple[Card, ...]
    eligible_nolo_show_cards: tuple[Card, ...]
    rami_fallback_category: VerbalFallbackCategory
    nolo_fallback_category: VerbalFallbackCategory
    schema_version: str = field(default="tuppi.agents.showing_context.v1", init=False)

    def fallback_category(self, contract: Contract) -> VerbalFallbackCategory:
        if contract is Contract.RAMI:
            return self.rami_fallback_category
        return self.nolo_fallback_category

    def eligible_show_cards(self, contract: Contract) -> tuple[Card, ...]:
        if contract is Contract.RAMI:
            return self.eligible_rami_show_cards
        return self.eligible_nolo_show_cards

    def verbal_required(self, contract: Contract) -> bool:
        return self.fallback_category(contract) is not (
            VerbalFallbackCategory.DIRECT_COLOR_CARD
        )


@dataclass(frozen=True, slots=True)
class DealMatchContext:
    """Contract, partnership, and rising-score facts for the current deal."""

    contract: Contract | None
    declarer: int | None
    declaring_team: Team | None
    first_leader: int | None
    acting_seat: int
    partner_seat: int
    acting_team: Team
    opponent_team: Team
    team_tricks: tuple[int, int]
    own_team_tricks: int
    opponent_team_tricks: int
    tricks_completed: int
    tricks_remaining: int
    match_score: tuple[int, int]
    own_match_points: int
    opponent_match_points: int
    up_team: Team | None
    match_role: MatchRole
    up_team_distance_to_target: int | None
    own_distance_to_target: int | None
    own_win_requires_at_least_tricks: int | None
    own_win_requires_at_most_tricks: int | None
    reachable_own_win_points: tuple[int, ...]
    reachable_opponent_win_points: tuple[int, ...]
    own_deal_win_possible: bool
    opponent_deal_win_possible: bool
    own_minimum_win_points: int | None
    own_maximum_win_points: int | None
    own_win_can_end_match: bool
    own_minimum_win_ends_match: bool
    up_team_win_can_end_match: bool
    down_team_win_resets_score: bool
    margin_has_match_value: bool
    margin_beyond_minimum_has_match_value: bool
    trick_reward_sign: int
    trick_point_scale: int
    schema_version: str = field(default="tuppi.agents.deal_match_context.v1", init=False)

    @property
    def marginal_own_trick_value(self) -> float:
        """Deal points gained per additional own trick, signed by contract role.

        RAMI and NOLO must never share an undifferentiated trick reward: a
        trick is worth ``+4`` to a RAMI declaring team, ``+8`` to a RAMI
        defending partnership above the sixth trick, and ``-4`` in NOLO.
        """

        return float(self.trick_reward_sign * self.trick_point_scale)

    @property
    def match_weighted_trick_value(self) -> float:
        """Trick value after discarding margin that cannot move the match."""

        multiplier = 1.0 if self.margin_has_match_value else 0.0
        return self.marginal_own_trick_value * multiplier


@dataclass(frozen=True, slots=True)
class PublicFeatures:
    """The complete observation-only feature bundle handed to a policy."""

    phase: EnginePhase
    observing_seat: int
    partner_seat: int
    dealer: int
    forehand: int
    own_hand: tuple[Card, ...]
    hand: HandDescriptors
    deal: DealMatchContext
    showing: ShowingContext | None
    trick: TrickContext | None
    inference: PublicInference | None
    schema_version: str = field(default=FEATURES_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.phase is EnginePhase.SHOWING:
            if self.showing is None or self.trick is not None:
                raise AgentsValidationError(
                    "showing features require a showing context and no trick context"
                )
        elif self.phase is EnginePhase.TRICK_PLAY:
            if self.trick is None or self.showing is not None:
                raise AgentsValidationError(
                    "trick features require a trick context and no showing context"
                )
        else:
            raise AgentsValidationError(
                "features are defined only for SHOWING and TRICK_PLAY"
            )

    def require_trick(self) -> TrickContext:
        if self.trick is None:
            raise AgentsValidationError("trick context is unavailable")
        return self.trick

    def require_showing(self) -> ShowingContext:
        if self.showing is None:
            raise AgentsValidationError("showing context is unavailable")
        return self.showing

    def require_inference(self) -> PublicInference:
        if self.inference is None:
            raise AgentsValidationError(
                "this policy was configured without hard public inference"
            )
        return self.inference


# --------------------------------------------------------------------- builders


def describe_hand(hand: tuple[Card, ...]) -> HandDescriptors:
    """Return generic immutable descriptors of an ordered hand."""

    if type(hand) is not tuple or not hand:
        raise AgentsValidationError("hand descriptors require a nonempty tuple")
    lengths = [0, 0, 0, 0]
    high_card_points = 0
    aces = kings = top_five = honours = low = exits = dangerous = 0
    for card in hand:
        if not isinstance(card, Card):
            raise AgentsValidationError("hand descriptors require Card values")
        lengths[SUIT_ORDER.index(card.suit)] += 1
        value = card.rank.value
        high_card_points += _HIGH_CARD_POINTS.get(value, 0)
        if value == Rank.ACE.value:
            aces += 1
        if value == Rank.KING.value:
            kings += 1
        if value >= Rank.TEN.value:
            top_five += 1
        if value >= Rank.JACK.value:
            honours += 1
        if value <= Rank.FOUR.value:
            low += 1
        if value in (2, 3, 4):
            exits += 1
        if value >= Rank.QUEEN.value:
            dangerous += 1
    return HandDescriptors(
        card_count=len(hand),
        high_card_points=high_card_points,
        aces=aces,
        kings=kings,
        control_cards=aces + kings,
        top_five_count=top_five,
        honour_count=honours,
        low_card_count=low,
        exit_card_count=exits,
        dangerous_high_cards=dangerous,
        suit_lengths=(lengths[0], lengths[1], lengths[2], lengths[3]),
        longest_suit_length=max(lengths),
        shortest_suit_length=min(lengths),
        void_count=sum(1 for value in lengths if value == 0),
        singleton_count=sum(1 for value in lengths if value == 1),
        doubleton_count=sum(1 for value in lengths if value == 2),
    )


def verbal_fallback_category(
    hand: tuple[Card, ...], contract: Contract
) -> VerbalFallbackCategory:
    """Classify which branch of the showing hierarchy a hand falls into."""

    eligible = tuple(card for card in hand if is_show_rank_eligible(card))
    if not eligible:
        return VerbalFallbackCategory.NO_ELIGIBLE_RANK
    desired = contract_color(contract)
    if any(card_color(card) is desired for card in eligible):
        return VerbalFallbackCategory.DIRECT_COLOR_CARD
    return VerbalFallbackCategory.ELIGIBLE_OFF_COLOR


def build_showing_context(observation: PlayerObservation) -> ShowingContext:
    checked = require_observation(observation)
    if checked.phase is not EnginePhase.SHOWING:
        raise AgentsValidationError("showing context requires the SHOWING phase")
    hand = checked.own_hand
    shows = checked.show_actions
    return ShowingContext(
        observing_seat=checked.observing_seat,
        dealer=checked.dealer,
        forehand=checked.forehand,
        showing_position=len(shows),
        previous_show_actions=shows,
        previous_nolo_count=sum(
            1 for action in shows if action.declared_contract is Contract.NOLO
        ),
        rami_already_resolved=any(
            action.declared_contract is Contract.RAMI for action in shows
        ),
        eligible_rami_show_cards=_sorted_cards(valid_show_cards(hand, Contract.RAMI)),
        eligible_nolo_show_cards=_sorted_cards(valid_show_cards(hand, Contract.NOLO)),
        rami_fallback_category=verbal_fallback_category(hand, Contract.RAMI),
        nolo_fallback_category=verbal_fallback_category(hand, Contract.NOLO),
    )


def build_deal_match_context(observation: PlayerObservation) -> DealMatchContext:
    checked = require_observation(observation)
    seat = checked.observing_seat
    own_team = team_for_seat(seat)
    opponent = opposing_team(own_team)
    declaring_team = None if checked.declarer is None else team_for_seat(checked.declarer)
    own_tricks = checked.team_tricks[own_team.value]
    opponent_tricks = checked.team_tricks[opponent.value]
    completed = own_tricks + opponent_tricks
    remaining = _TRICKS_PER_DEAL - completed
    score = checked.match_score
    up_team = score.up_team
    own_points = score.for_team(own_team)
    opponent_points = score.for_team(opponent)

    if up_team is None:
        role = MatchRole.TABLE
    elif up_team is own_team:
        role = MatchRole.UP
    else:
        role = MatchRole.DOWN

    own_wins: list[int] = []
    opponent_wins: list[int] = []
    if checked.contract is not None:
        for final_own in range(own_tricks, own_tricks + remaining + 1):
            winner, points = _deal_outcome(
                contract=checked.contract,
                declaring_team=declaring_team,
                own_team=own_team,
                own_final_tricks=final_own,
            )
            if winner is own_team:
                own_wins.append(points)
            else:
                opponent_wins.append(points)

    reachable_own = tuple(sorted(set(own_wins)))
    reachable_opponent = tuple(sorted(set(opponent_wins)))
    minimum_win = reachable_own[0] if reachable_own else None
    maximum_win = reachable_own[-1] if reachable_own else None

    if role is MatchRole.UP:
        distance = MATCH_TARGET - own_points
        own_can_end = maximum_win is not None and maximum_win >= distance
        minimum_ends = minimum_win is not None and minimum_win >= distance
    elif role is MatchRole.TABLE:
        distance = MATCH_TARGET
        own_can_end = maximum_win is not None and maximum_win >= MATCH_TARGET
        minimum_ends = minimum_win is not None and minimum_win >= MATCH_TARGET
    else:
        # A down-team deal win only resets the rising score to 0-0. It can
        # never end the match, whatever the deal margin is.
        distance = None
        own_can_end = False
        minimum_ends = False

    up_distance = None if up_team is None else MATCH_TARGET - score.for_team(up_team)
    if up_team is None:
        up_can_end = bool(reachable_own or reachable_opponent) and max(
            reachable_own + reachable_opponent, default=0
        ) >= MATCH_TARGET
    elif up_team is own_team:
        up_can_end = own_can_end
    else:
        up_can_end = bool(reachable_opponent) and (
            max(reachable_opponent) >= (up_distance or MATCH_TARGET)
        )

    margin_value = role is not MatchRole.DOWN
    beyond_minimum = margin_value and not (
        role is MatchRole.UP and minimum_ends
    )

    sign, scale = _trick_reward(
        contract=checked.contract, own_team=own_team, declaring_team=declaring_team
    )
    at_least, at_most = _win_trick_thresholds(
        contract=checked.contract, own_team=own_team, declaring_team=declaring_team
    )

    return DealMatchContext(
        contract=checked.contract,
        declarer=checked.declarer,
        declaring_team=declaring_team,
        first_leader=checked.first_leader,
        acting_seat=seat,
        partner_seat=checked.partner_seat,
        acting_team=own_team,
        opponent_team=opponent,
        team_tricks=checked.team_tricks,
        own_team_tricks=own_tricks,
        opponent_team_tricks=opponent_tricks,
        tricks_completed=completed,
        tricks_remaining=remaining,
        match_score=score.as_tuple(),
        own_match_points=own_points,
        opponent_match_points=opponent_points,
        up_team=up_team,
        match_role=role,
        up_team_distance_to_target=up_distance,
        own_distance_to_target=distance,
        own_win_requires_at_least_tricks=at_least,
        own_win_requires_at_most_tricks=at_most,
        reachable_own_win_points=reachable_own,
        reachable_opponent_win_points=reachable_opponent,
        own_deal_win_possible=bool(reachable_own),
        opponent_deal_win_possible=bool(reachable_opponent),
        own_minimum_win_points=minimum_win,
        own_maximum_win_points=maximum_win,
        own_win_can_end_match=own_can_end,
        own_minimum_win_ends_match=minimum_ends,
        up_team_win_can_end_match=up_can_end,
        down_team_win_resets_score=up_team is not None,
        margin_has_match_value=margin_value,
        margin_beyond_minimum_has_match_value=beyond_minimum,
        trick_reward_sign=sign,
        trick_point_scale=scale,
    )


def build_features(
    observation: PlayerObservation, *, include_inference: bool
) -> PublicFeatures:
    """Build the feature bundle for one acting observation.

    ``include_inference`` is a capability switch, not a tuning knob: policies
    that are defined to work without hard public inference are constructed
    without it so that the ablation between them is structural.
    """

    checked = require_observation(observation)
    if type(include_inference) is not bool:
        raise AgentsValidationError("include_inference must be a boolean")
    if checked.current_actor != checked.observing_seat:
        raise AgentsValidationError(
            "features are built only for the acting seat's own observation"
        )
    phase = checked.phase
    showing = build_showing_context(checked) if phase is EnginePhase.SHOWING else None
    trick = build_trick_context(checked) if phase is EnginePhase.TRICK_PLAY else None
    return PublicFeatures(
        phase=phase,
        observing_seat=checked.observing_seat,
        partner_seat=checked.partner_seat,
        dealer=checked.dealer,
        forehand=checked.forehand,
        own_hand=checked.own_hand,
        hand=describe_hand(checked.own_hand),
        deal=build_deal_match_context(checked),
        showing=showing,
        trick=trick,
        inference=PublicInference.build(checked) if include_inference else None,
    )


# ---------------------------------------------------------------------- helpers


def _sorted_cards(cards: frozenset[Card]) -> tuple[Card, ...]:
    return tuple(sorted(cards, key=canonical_card_order_key))


def _deal_outcome(
    *,
    contract: Contract,
    declaring_team: Team | None,
    own_team: Team,
    own_final_tricks: int,
) -> tuple[Team, int]:
    opponent = opposing_team(own_team)
    opponent_final = _TRICKS_PER_DEAL - own_final_tricks
    if contract is Contract.NOLO:
        if own_final_tricks < opponent_final:
            return (own_team, 4 * (7 - own_final_tricks))
        return (opponent, 4 * (7 - opponent_final))
    if declaring_team is None:
        raise AgentsValidationError("a RAMI deal requires a declaring team")
    declaring_final = (
        own_final_tricks if declaring_team is own_team else opponent_final
    )
    if declaring_final >= 7:
        return (declaring_team, 4 * (declaring_final - 6))
    defending = opposing_team(declaring_team)
    defending_final = _TRICKS_PER_DEAL - declaring_final
    return (defending, 8 * (defending_final - 6))


def _trick_reward(
    *, contract: Contract | None, own_team: Team, declaring_team: Team | None
) -> tuple[int, int]:
    if contract is None:
        return (0, 0)
    if contract is Contract.NOLO:
        return (-1, 4)
    if declaring_team is own_team:
        return (1, 4)
    return (1, 8)


def _win_trick_thresholds(
    *, contract: Contract | None, own_team: Team, declaring_team: Team | None
) -> tuple[int | None, int | None]:
    if contract is None:
        return (None, None)
    if contract is Contract.NOLO:
        return (None, 6)
    return (7, None)


def show_action_for(
    observation: PlayerObservation, *, contract: Contract, card: Card
) -> ShowAction:
    """Return the engine show action for an explicit contract and card."""

    checked = require_observation(observation)
    for action in checked.legal_actions:
        if (
            isinstance(action, ShowAction)
            and action.declared_contract is contract
            and action.shown_card == card
        ):
            return action
    raise AgentsValidationError("requested show action is not legal in this observation")
