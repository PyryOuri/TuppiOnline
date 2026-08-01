"""Explicit invertible seat, partnership, script, and suit transformations."""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import Action, ExplicitDeal, PlayCardAction, ShowAction
from tuppi_rules import SUIT_ORDER, Card, MatchScore, Suit, card_to_code

from .deals import BaseDeal
from .errors import TransformationError
from .serialization import content_digest, require_exact_keys, require_object


TRANSFORMATION_SCHEMA_VERSION = "tuppi.eval.transformation.v1"
TRANSFORMED_DEAL_SCHEMA_VERSION = "tuppi.eval.transformed_deal.v1"


@dataclass(frozen=True, slots=True)
class Transformation:
    transformation_id: str
    seat_rotation: int
    team_assignment_exchange: bool
    partner_seat_exchange: bool
    suit_permutation: tuple[Suit, Suit, Suit, Suit]
    label: str
    strength_estimation: bool
    schema_version: str = field(default=TRANSFORMATION_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.seat_rotation) is not int or self.seat_rotation not in range(4):
            raise TransformationError("seat_rotation must be in 0..3")
        if type(self.team_assignment_exchange) is not bool:
            raise TransformationError("team_assignment_exchange must be boolean")
        if type(self.partner_seat_exchange) is not bool:
            raise TransformationError("partner_seat_exchange must be boolean")
        if (
            type(self.suit_permutation) is not tuple
            or len(self.suit_permutation) != 4
            or any(not isinstance(suit, Suit) for suit in self.suit_permutation)
            or frozenset(self.suit_permutation) != frozenset(SUIT_ORDER)
        ):
            raise TransformationError("suit_permutation must permute all four suits")
        if not isinstance(self.label, str) or not self.label:
            raise TransformationError("transformation label must be nonempty")
        if type(self.strength_estimation) is not bool:
            raise TransformationError("strength_estimation must be boolean")
        if self.strength_estimation and self.suit_permutation != SUIT_ORDER:
            raise TransformationError(
                "suit permutations are diagnostic and cannot be automatic strength rows"
            )
        expected = f"transform:{content_digest(self.identity_data())}"
        if self.transformation_id != expected:
            raise TransformationError(
                "transformation_id disagrees with transformation content"
            )

    @classmethod
    def build(
        cls,
        *,
        seat_rotation: int,
        team_assignment_exchange: bool,
        partner_seat_exchange: bool,
        suit_permutation: tuple[Suit, Suit, Suit, Suit] = SUIT_ORDER,
        label: str,
        strength_estimation: bool,
        claimed_transformation_id: str | None = None,
    ) -> "Transformation":
        identity = {
            "partner_seat_exchange": partner_seat_exchange,
            "schema_version": TRANSFORMATION_SCHEMA_VERSION,
            "seat_rotation": seat_rotation,
            "strength_estimation": strength_estimation,
            "suit_permutation": [suit.value for suit in suit_permutation],
            "team_assignment_exchange": team_assignment_exchange,
        }
        computed = f"transform:{content_digest(identity)}"
        return cls(
            transformation_id=claimed_transformation_id or computed,
            seat_rotation=seat_rotation,
            team_assignment_exchange=team_assignment_exchange,
            partner_seat_exchange=partner_seat_exchange,
            suit_permutation=tuple(suit_permutation),
            label=label,
            strength_estimation=strength_estimation,
        )

    def identity_data(self) -> dict[str, object]:
        return {
            "partner_seat_exchange": self.partner_seat_exchange,
            "schema_version": self.schema_version,
            "seat_rotation": self.seat_rotation,
            "strength_estimation": self.strength_estimation,
            "suit_permutation": [suit.value for suit in self.suit_permutation],
            "team_assignment_exchange": self.team_assignment_exchange,
        }

    def map_seat(self, seat: int) -> int:
        if type(seat) is not int or seat not in range(4):
            raise TransformationError("seat must be in 0..3")
        return (seat + self.seat_rotation) % 4

    def map_card(self, card: Card) -> Card:
        if not isinstance(card, Card):
            raise TransformationError("card transformation requires a Card")
        mapped_suit = self.suit_permutation[SUIT_ORDER.index(card.suit)]
        return Card(suit=mapped_suit, rank=card.rank)

    def inverse(self) -> "Transformation":
        inverse_suits = tuple(
            SUIT_ORDER[self.suit_permutation.index(suit)] for suit in SUIT_ORDER
        )
        return Transformation.build(
            seat_rotation=(-self.seat_rotation) % 4,
            team_assignment_exchange=self.team_assignment_exchange,
            partner_seat_exchange=self.partner_seat_exchange,
            suit_permutation=inverse_suits,
            label=f"inverse({self.label})",
            strength_estimation=(
                self.strength_estimation and inverse_suits == SUIT_ORDER
            ),
        )


def compose_transformations(
    first: Transformation, second: Transformation, *, label: str
) -> Transformation:
    """Return the transform equivalent to applying *first*, then *second*."""

    if not isinstance(first, Transformation) or not isinstance(second, Transformation):
        raise TransformationError("composition requires two transformations")
    suits = tuple(
        second.suit_permutation[SUIT_ORDER.index(first.suit_permutation[index])]
        for index in range(4)
    )
    return Transformation.build(
        seat_rotation=(first.seat_rotation + second.seat_rotation) % 4,
        team_assignment_exchange=(
            first.team_assignment_exchange ^ second.team_assignment_exchange
        ),
        partner_seat_exchange=(
            first.partner_seat_exchange ^ second.partner_seat_exchange
        ),
        suit_permutation=suits,
        label=label,
        strength_estimation=(
            first.strength_estimation
            and second.strength_estimation
            and suits == SUIT_ORDER
        ),
    )


@dataclass(frozen=True, slots=True)
class TransformedDeal:
    transformed_deal_id: str
    base_deal_id: str
    transformation_id: str
    dealer: int
    hands: tuple[tuple[Card, ...], ...]
    starting_score: MatchScore
    explicit_deal_id: str
    schema_version: str = field(default=TRANSFORMED_DEAL_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        explicit = ExplicitDeal(
            dealer=self.dealer,
            hands=self.hands,
            claimed_deal_id=self.explicit_deal_id,
        )
        identity = {
            "base_deal_id": self.base_deal_id,
            "explicit_deal_id": explicit.deal_id,
            "schema_version": self.schema_version,
            "starting_score": list(self.starting_score.as_tuple()),
            "transformation_id": self.transformation_id,
        }
        if self.transformed_deal_id != f"concrete:{content_digest(identity)}":
            raise TransformationError("transformed_deal_id is invalid")

    def explicit_deal(self) -> ExplicitDeal:
        return ExplicitDeal(
            dealer=self.dealer,
            hands=self.hands,
            claimed_deal_id=self.explicit_deal_id,
        )


def transform_deal(base_deal: BaseDeal, transformation: Transformation) -> TransformedDeal:
    if not isinstance(base_deal, BaseDeal):
        raise TransformationError("transform_deal requires a BaseDeal")
    if not isinstance(transformation, Transformation):
        raise TransformationError("transform_deal requires a Transformation")
    mutable: list[tuple[Card, ...] | None] = [None, None, None, None]
    for old_seat, hand in enumerate(base_deal.hands):
        mutable[transformation.map_seat(old_seat)] = tuple(
            transformation.map_card(card) for card in hand
        )
    if any(hand is None for hand in mutable):
        raise TransformationError("seat transformation did not cover all seats")
    hands = tuple(mutable)  # type: ignore[arg-type]
    dealer = transformation.map_seat(base_deal.dealer)
    score = base_deal.starting_score
    if transformation.seat_rotation % 2:
        score = MatchScore(score.team1, score.team0)
    explicit = ExplicitDeal(dealer=dealer, hands=hands)
    identity = {
        "base_deal_id": base_deal.base_deal_id,
        "explicit_deal_id": explicit.deal_id,
        "schema_version": TRANSFORMED_DEAL_SCHEMA_VERSION,
        "starting_score": list(score.as_tuple()),
        "transformation_id": transformation.transformation_id,
    }
    return TransformedDeal(
        transformed_deal_id=f"concrete:{content_digest(identity)}",
        base_deal_id=base_deal.base_deal_id,
        transformation_id=transformation.transformation_id,
        dealer=dealer,
        hands=hands,
        starting_score=score,
        explicit_deal_id=explicit.deal_id,
    )


def transform_action(action: Action, transformation: Transformation) -> Action:
    if isinstance(action, ShowAction):
        return ShowAction(
            seat=transformation.map_seat(action.seat),
            shown_card=transformation.map_card(action.shown_card),
            declared_contract=action.declared_contract,
        )
    if isinstance(action, PlayCardAction):
        return PlayCardAction(
            seat=transformation.map_seat(action.seat),
            card=transformation.map_card(action.card),
        )
    raise TransformationError("cannot transform a non-engine action")


def transform_actions(
    actions: tuple[Action, ...], transformation: Transformation
) -> tuple[Action, ...]:
    if type(actions) is not tuple:
        raise TransformationError("script actions must be an immutable tuple")
    return tuple(transform_action(action, transformation) for action in actions)


def transformation_to_data(value: Transformation) -> dict[str, object]:
    return {
        "label": value.label,
        "partner_seat_exchange": value.partner_seat_exchange,
        "schema_version": value.schema_version,
        "seat_rotation": value.seat_rotation,
        "strength_estimation": value.strength_estimation,
        "suit_permutation": [suit.value for suit in value.suit_permutation],
        "team_assignment_exchange": value.team_assignment_exchange,
        "transformation_id": value.transformation_id,
    }


def transformation_from_data(value: object) -> Transformation:
    obj = require_object(value, "transformation")
    require_exact_keys(
        obj,
        {
            "label",
            "partner_seat_exchange",
            "schema_version",
            "seat_rotation",
            "strength_estimation",
            "suit_permutation",
            "team_assignment_exchange",
            "transformation_id",
        },
        "transformation",
    )
    if obj["schema_version"] != TRANSFORMATION_SCHEMA_VERSION:
        raise TransformationError("unsupported transformation schema_version")
    raw_suits = obj["suit_permutation"]
    if type(raw_suits) is not list or len(raw_suits) != 4:
        raise TransformationError("suit_permutation must contain four suits")
    try:
        suits = tuple(Suit(item) for item in raw_suits)
    except (TypeError, ValueError) as exc:
        raise TransformationError("suit_permutation contains an invalid suit") from exc
    return Transformation.build(
        seat_rotation=obj["seat_rotation"],
        team_assignment_exchange=obj["team_assignment_exchange"],
        partner_seat_exchange=obj["partner_seat_exchange"],
        suit_permutation=suits,  # type: ignore[arg-type]
        label=obj["label"],
        strength_estimation=obj["strength_estimation"],
        claimed_transformation_id=obj["transformation_id"],
    )


def identity_transformation() -> Transformation:
    return Transformation.build(
        seat_rotation=0,
        team_assignment_exchange=False,
        partner_seat_exchange=False,
        label="identity",
        strength_estimation=True,
    )


def rotation_transformation(rotation: int) -> Transformation:
    return Transformation.build(
        seat_rotation=rotation,
        team_assignment_exchange=False,
        partner_seat_exchange=False,
        label=f"clockwise_rotation_{rotation}",
        strength_estimation=True,
    )


def partnership_swap_transformation() -> Transformation:
    return Transformation.build(
        seat_rotation=0,
        team_assignment_exchange=True,
        partner_seat_exchange=False,
        label="partnership_assignment_swap",
        strength_estimation=True,
    )


def partner_seat_exchange_transformation() -> Transformation:
    return Transformation.build(
        seat_rotation=0,
        team_assignment_exchange=False,
        partner_seat_exchange=True,
        label="partner_seat_exchange",
        strength_estimation=True,
    )


def diagnostic_suit_permutation(
    suits: tuple[Suit, Suit, Suit, Suit], *, label: str
) -> Transformation:
    return Transformation.build(
        seat_rotation=0,
        team_assignment_exchange=False,
        partner_seat_exchange=False,
        suit_permutation=suits,
        label=label,
        strength_estimation=False,
    )


def transformed_deal_debug_data(value: TransformedDeal) -> dict[str, object]:
    """Full-information diagnostic representation used in raw records."""

    return {
        "base_deal_id": value.base_deal_id,
        "dealer": value.dealer,
        "explicit_deal_id": value.explicit_deal_id,
        "hands": [[card_to_code(card) for card in hand] for hand in value.hands],
        "schema_version": value.schema_version,
        "starting_score": list(value.starting_score.as_tuple()),
        "transformation_id": value.transformation_id,
        "transformed_deal_id": value.transformed_deal_id,
    }
