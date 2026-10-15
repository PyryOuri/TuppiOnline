"""Pure current-trick context derived from one player observation."""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import PlayCardAction, PlayerObservation
from tuppi_rules import Card, PlayedCard, Suit, partner_for_seat, team_for_seat

from .errors import AgentsValidationError
from .ordering import canonical_card_order_key, require_observation


TRICK_CONTEXT_SCHEMA_VERSION = "tuppi.agents.trick_context.v1"


@dataclass(frozen=True, slots=True)
class TrickContext:
    """Immutable facts about the trick the observing player must act in.

    When the observing player is on lead there is no led suit and no current
    winner. In that case every legal card is reported as "currently winning"
    and none as "currently losing", because a led card is by construction the
    provisional winner of the trick it starts.

    "Currently winning" is always provisional for a player who is not last to
    play: a later seat may still overtake. Policies that need certainty use
    :mod:`tuppi_agents.public_inference` instead.
    """

    trick_index: int
    leader: int
    led_suit: Suit | None
    plays: tuple[PlayedCard, ...]
    acting_position: int
    is_leading: bool
    is_last_to_play: bool
    seats_still_to_play: tuple[int, ...]
    current_winning_seat: int | None
    current_winning_card: Card | None
    partner_is_winning: bool
    opponent_is_winning: bool
    can_follow_suit: bool
    legal_cards: tuple[Card, ...]
    currently_winning_cards: tuple[Card, ...]
    currently_losing_cards: tuple[Card, ...]
    lowest_winning_card: Card | None
    highest_winning_card: Card | None
    lowest_losing_card: Card | None
    highest_losing_card: Card | None
    schema_version: str = field(default=TRICK_CONTEXT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.plays) is not tuple or len(self.plays) > 3:
            raise AgentsValidationError("a partial trick holds zero to three plays")
        if self.acting_position != len(self.plays):
            raise AgentsValidationError("acting position disagrees with the trick")
        if self.is_leading is not (self.acting_position == 0):
            raise AgentsValidationError("leading flag disagrees with acting position")
        if self.is_last_to_play is not (self.acting_position == 3):
            raise AgentsValidationError("last-to-play flag disagrees with position")
        if not self.legal_cards:
            raise AgentsValidationError("a trick context requires legal cards")
        combined = set(self.currently_winning_cards) | set(self.currently_losing_cards)
        if combined != set(self.legal_cards):
            raise AgentsValidationError(
                "winning and losing legal cards must partition the legal cards"
            )
        if set(self.currently_winning_cards) & set(self.currently_losing_cards):
            raise AgentsValidationError(
                "a legal card cannot both win and lose the current trick"
            )
        if self.partner_is_winning and self.opponent_is_winning:
            raise AgentsValidationError("only one side can hold the current trick")

    def wins_now(self, card: Card) -> bool:
        return card in self.currently_winning_cards

    def overtakes_partner(self, card: Card) -> bool:
        """True when playing ``card`` would take the trick away from a partner."""

        return self.partner_is_winning and self.wins_now(card)


def build_trick_context(observation: PlayerObservation) -> TrickContext:
    checked = require_observation(observation)
    seat = checked.observing_seat
    partner = partner_for_seat(seat)
    plays = checked.current_trick
    position = len(plays)
    leader = seat if position == 0 else plays[0].seat
    led_suit = plays[0].card.suit if plays else None

    legal_cards = tuple(
        action.card
        for action in checked.legal_actions
        if isinstance(action, PlayCardAction)
    )
    if not legal_cards:
        raise AgentsValidationError(
            "trick context requires an observation with legal card plays"
        )

    winning_seat: int | None = None
    winning_card: Card | None = None
    if plays:
        for play in plays:
            if play.card.suit is not led_suit:
                continue
            if winning_card is None or play.card.rank.value > winning_card.rank.value:
                winning_seat = play.seat
                winning_card = play.card

    if led_suit is None:
        winning = legal_cards
        losing: tuple[Card, ...] = ()
    else:
        threshold = winning_card.rank.value if winning_card is not None else 0
        winning = tuple(
            card
            for card in legal_cards
            if card.suit is led_suit and card.rank.value > threshold
        )
        winning_set = frozenset(winning)
        losing = tuple(card for card in legal_cards if card not in winning_set)

    own_team = team_for_seat(seat)
    partner_winning = winning_seat == partner
    opponent_winning = winning_seat is not None and (
        team_for_seat(winning_seat) is not own_team
    )

    return TrickContext(
        trick_index=len(checked.completed_tricks),
        leader=leader,
        led_suit=led_suit,
        plays=plays,
        acting_position=position,
        is_leading=position == 0,
        is_last_to_play=position == 3,
        seats_still_to_play=tuple((seat + offset) % 4 for offset in range(1, 4 - position)),
        current_winning_seat=winning_seat,
        current_winning_card=winning_card,
        partner_is_winning=partner_winning,
        opponent_is_winning=opponent_winning,
        can_follow_suit=led_suit is not None
        and any(card.suit is led_suit for card in legal_cards),
        legal_cards=legal_cards,
        currently_winning_cards=winning,
        currently_losing_cards=losing,
        lowest_winning_card=_extreme(winning, highest=False),
        highest_winning_card=_extreme(winning, highest=True),
        lowest_losing_card=_extreme(losing, highest=False),
        highest_losing_card=_extreme(losing, highest=True),
    )


def _extreme(cards: tuple[Card, ...], *, highest: bool) -> Card | None:
    """Return the highest or lowest card by rank, then canonical suit order.

    Ties in rank are broken by ``project_target_v1`` suit order so the result
    never depends on hand iteration order.
    """

    if not cards:
        return None
    if highest:
        return max(cards, key=lambda card: (card.rank.value, -canonical_card_order_key(card)))
    return min(cards, key=lambda card: (card.rank.value, canonical_card_order_key(card)))
