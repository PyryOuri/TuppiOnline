"""Counter-derived deterministic deal generation and strict deal banks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any

from tuppi_engine import ExplicitDeal
from tuppi_rules import (
    CARD_ENCODING_ID,
    FULL_DECK,
    RULESET_ID,
    Card,
    MatchScore,
    RulesError,
    card_from_code,
    card_to_code,
    is_match_terminal,
    validate_initial_hands,
)

from .errors import DealBankError
from .serialization import (
    atomic_write_canonical_json,
    canonical_json_text,
    content_digest,
    require_exact_keys,
    require_int,
    require_object,
    strict_json_load_file,
)


BASE_DEAL_SCHEMA_VERSION = "tuppi.eval.base_deal.v1"
DEAL_BANK_SCHEMA_VERSION = "tuppi.eval.deal_bank.v1"
GENERATOR_ID = "tuppi.eval.sha256_fisher_yates"
GENERATOR_VERSION = "1.0.0"
SHUFFLE_ALGORITHM = "sha256_counter_fisher_yates_modulo_v1"


class DealerPolicy(StrEnum):
    ROUND_ROBIN = "round_robin"
    DIGEST_DERIVED = "digest_derived"


def derive_seed(root_seed: int | str, *components: object) -> str:
    """Derive an independent canonical child seed for one namespace."""

    if type(root_seed) not in (int, str) or isinstance(root_seed, bool):
        raise DealBankError("root seed must be an integer or string")
    material = {
        "components": [str(component) for component in components],
        "root_seed": root_seed,
        "schema_version": "tuppi.eval.seed_derivation.v1",
    }
    return content_digest(material)


def _score(value: MatchScore) -> tuple[int, int]:
    if not isinstance(value, MatchScore) or is_match_terminal(value):
        raise DealBankError("starting score must be a nonterminal MatchScore")
    try:
        checked = MatchScore(value.team0, value.team1)
    except RulesError as exc:
        raise DealBankError("starting score is invalid") from exc
    return checked.as_tuple()


@dataclass(frozen=True, slots=True)
class BaseDeal:
    base_deal_id: str
    index: int
    dealer: int
    hands: tuple[tuple[Card, ...], ...]
    starting_score: MatchScore
    schema_version: str = field(default=BASE_DEAL_SCHEMA_VERSION, init=False)
    ruleset_id: str = field(default=RULESET_ID.value, init=False)
    card_encoding: str = field(default=CARD_ENCODING_ID, init=False)

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise DealBankError("base deal index must be nonnegative")
        if type(self.dealer) is not int or self.dealer not in range(4):
            raise DealBankError("base deal dealer must be in 0..3")
        try:
            checked_hands = validate_initial_hands(self.hands)
        except RulesError as exc:
            raise DealBankError(f"invalid base-deal hands: {exc}") from exc
        if checked_hands != self.hands or any(
            type(hand) is not tuple for hand in self.hands
        ):
            raise DealBankError("base-deal hands must be immutable ordered tuples")
        _score(self.starting_score)
        expected = f"base:{content_digest(self.identity_data())}"
        if self.base_deal_id != expected:
            raise DealBankError("base_deal_id disagrees with canonical content")

    @classmethod
    def build(
        cls,
        *,
        index: int,
        dealer: int,
        hands: tuple[tuple[Card, ...], ...],
        starting_score: MatchScore,
        claimed_base_deal_id: str | None = None,
    ) -> "BaseDeal":
        normalized = validate_initial_hands(hands)
        identity = {
            "card_encoding": CARD_ENCODING_ID,
            "dealer": dealer,
            "hands": [[card_to_code(card) for card in hand] for hand in normalized],
            "ruleset_id": RULESET_ID.value,
            "schema_version": BASE_DEAL_SCHEMA_VERSION,
            "starting_score": list(_score(starting_score)),
        }
        computed = f"base:{content_digest(identity)}"
        return cls(
            base_deal_id=claimed_base_deal_id or computed,
            index=index,
            dealer=dealer,
            hands=normalized,
            starting_score=starting_score,
        )

    def identity_data(self) -> dict[str, object]:
        return {
            "card_encoding": self.card_encoding,
            "dealer": self.dealer,
            "hands": [
                [card_to_code(card) for card in hand] for hand in self.hands
            ],
            "ruleset_id": self.ruleset_id,
            "schema_version": self.schema_version,
            "starting_score": list(self.starting_score.as_tuple()),
        }

    def explicit_deal(self) -> ExplicitDeal:
        return ExplicitDeal(dealer=self.dealer, hands=self.hands)


def base_deal_to_data(deal: BaseDeal) -> dict[str, object]:
    return {
        "base_deal_id": deal.base_deal_id,
        "card_encoding": deal.card_encoding,
        "dealer": deal.dealer,
        "hands": [[card_to_code(card) for card in hand] for hand in deal.hands],
        "index": deal.index,
        "ruleset_id": deal.ruleset_id,
        "schema_version": deal.schema_version,
        "starting_score": list(deal.starting_score.as_tuple()),
    }


def base_deal_from_data(value: object) -> BaseDeal:
    obj = require_object(value, "base deal")
    require_exact_keys(
        obj,
        {
            "base_deal_id",
            "card_encoding",
            "dealer",
            "hands",
            "index",
            "ruleset_id",
            "schema_version",
            "starting_score",
        },
        "base deal",
    )
    if obj["schema_version"] != BASE_DEAL_SCHEMA_VERSION:
        raise DealBankError("unsupported base-deal schema_version")
    if obj["ruleset_id"] != RULESET_ID.value:
        raise DealBankError("base deal ruleset mismatch")
    if obj["card_encoding"] != CARD_ENCODING_ID:
        raise DealBankError("base deal card encoding mismatch")
    hands_value = obj["hands"]
    if type(hands_value) is not list or len(hands_value) != 4:
        raise DealBankError("base deal must contain four hands")
    try:
        hands = tuple(
            tuple(card_from_code(code) for code in hand) for hand in hands_value
        )
    except (RulesError, TypeError) as exc:
        raise DealBankError("base deal contains an invalid card") from exc
    score_value = obj["starting_score"]
    if type(score_value) is not list or len(score_value) != 2:
        raise DealBankError("starting_score must contain two integers")
    try:
        score = MatchScore(score_value[0], score_value[1])
    except RulesError as exc:
        raise DealBankError("starting_score is invalid") from exc
    return BaseDeal.build(
        index=obj["index"],
        dealer=obj["dealer"],
        hands=hands,
        starting_score=score,
        claimed_base_deal_id=obj["base_deal_id"],
    )


@dataclass(frozen=True, slots=True)
class DealBank:
    deal_bank_id: str
    content_digest: str
    generator_id: str
    generator_version: str
    shuffle_algorithm: str
    root_seed: int | str
    dealer_policy: DealerPolicy
    initial_dealer: int
    base_deals: tuple[BaseDeal, ...]
    creation_metadata_json: str
    schema_version: str = field(default=DEAL_BANK_SCHEMA_VERSION, init=False)
    ruleset_id: str = field(default=RULESET_ID.value, init=False)

    def __post_init__(self) -> None:
        if self.generator_id != GENERATOR_ID or self.generator_version != GENERATOR_VERSION:
            raise DealBankError("unsupported deal generator identity")
        if self.shuffle_algorithm != SHUFFLE_ALGORITHM:
            raise DealBankError("unsupported shuffle algorithm")
        if type(self.root_seed) not in (int, str) or isinstance(self.root_seed, bool):
            raise DealBankError("root_seed must be an integer or string")
        if isinstance(self.root_seed, str) and not self.root_seed:
            raise DealBankError("root_seed must not be empty")
        if not isinstance(self.dealer_policy, DealerPolicy):
            raise DealBankError("dealer_policy must be a DealerPolicy")
        if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
            raise DealBankError("initial_dealer must be in 0..3")
        if type(self.base_deals) is not tuple or not self.base_deals:
            raise DealBankError("deal bank must contain at least one base deal")
        if tuple(deal.index for deal in self.base_deals) != tuple(
            range(len(self.base_deals))
        ):
            raise DealBankError("base-deal indices must be contiguous from zero")
        ids = tuple(deal.base_deal_id for deal in self.base_deals)
        if len(set(ids)) != len(ids):
            raise DealBankError("deal bank contains duplicate deals")
        material_digests = tuple(
            content_digest(
                {
                    "hands": [
                        [card_to_code(card) for card in hand]
                        for hand in deal.hands
                    ],
                    "schema_version": "tuppi.eval.deal_material.v1",
                }
            )
            for deal in self.base_deals
        )
        if len(set(material_digests)) != len(material_digests):
            raise DealBankError("deal bank contains duplicate card material")
        for deal in self.base_deals:
            expected_dealer = _dealer_for(
                root_seed=self.root_seed,
                index=deal.index,
                policy=self.dealer_policy,
                initial_dealer=self.initial_dealer,
            )
            if deal.dealer != expected_dealer:
                raise DealBankError("base-deal dealer disagrees with dealer policy")
        try:
            metadata = json.loads(self.creation_metadata_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise DealBankError("creation metadata is invalid JSON") from exc
        if type(metadata) is not dict or canonical_json_text(metadata) != self.creation_metadata_json:
            raise DealBankError("creation metadata must be a canonical JSON object")
        semantic = self.semantic_data()
        digest = content_digest(semantic)
        if self.content_digest != digest or self.deal_bank_id != f"bank:{digest}":
            raise DealBankError("deal-bank identity disagrees with canonical content")

    @classmethod
    def build(
        cls,
        *,
        root_seed: int | str,
        dealer_policy: DealerPolicy,
        initial_dealer: int,
        base_deals: tuple[BaseDeal, ...],
        creation_metadata: dict[str, Any],
        claimed_deal_bank_id: str | None = None,
        claimed_content_digest: str | None = None,
    ) -> "DealBank":
        semantic = {
            "base_deals": [base_deal_to_data(deal) for deal in base_deals],
            "dealer_policy": dealer_policy.value,
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "initial_dealer": initial_dealer,
            "root_seed": root_seed,
            "ruleset_id": RULESET_ID.value,
            "schema_version": DEAL_BANK_SCHEMA_VERSION,
            "shuffle_algorithm": SHUFFLE_ALGORITHM,
        }
        digest = content_digest(semantic)
        return cls(
            deal_bank_id=claimed_deal_bank_id or f"bank:{digest}",
            content_digest=claimed_content_digest or digest,
            generator_id=GENERATOR_ID,
            generator_version=GENERATOR_VERSION,
            shuffle_algorithm=SHUFFLE_ALGORITHM,
            root_seed=root_seed,
            dealer_policy=dealer_policy,
            initial_dealer=initial_dealer,
            base_deals=tuple(base_deals),
            creation_metadata_json=canonical_json_text(creation_metadata),
        )

    @property
    def creation_metadata(self) -> dict[str, Any]:
        return json.loads(self.creation_metadata_json)

    def semantic_data(self) -> dict[str, object]:
        return {
            "base_deals": [base_deal_to_data(deal) for deal in self.base_deals],
            "dealer_policy": self.dealer_policy.value,
            "generator_id": self.generator_id,
            "generator_version": self.generator_version,
            "initial_dealer": self.initial_dealer,
            "root_seed": self.root_seed,
            "ruleset_id": self.ruleset_id,
            "schema_version": self.schema_version,
            "shuffle_algorithm": self.shuffle_algorithm,
        }


def _digest_integer(*parts: object) -> int:
    payload = "\0".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def _dealer_for(
    *,
    root_seed: int | str,
    index: int,
    policy: DealerPolicy,
    initial_dealer: int,
) -> int:
    if policy is DealerPolicy.ROUND_ROBIN:
        return (initial_dealer + index) % 4
    return _digest_integer(
        "tuppi.eval.dealer.v1", root_seed, index, initial_dealer
    ) % 4


def generate_base_deal(
    *,
    root_seed: int | str,
    index: int,
    dealer_policy: DealerPolicy,
    initial_dealer: int,
    starting_score: MatchScore,
) -> BaseDeal:
    if type(index) is not int or index < 0:
        raise DealBankError("deal index must be nonnegative")
    if type(initial_dealer) is not int or initial_dealer not in range(4):
        raise DealBankError("initial_dealer must be in 0..3")
    _score(starting_score)
    cards = list(FULL_DECK)
    for upper in range(len(cards) - 1, 0, -1):
        random_value = _digest_integer(
            "tuppi.eval.shuffle.v1",
            GENERATOR_VERSION,
            root_seed,
            index,
            upper,
        )
        chosen = random_value % (upper + 1)
        cards[upper], cards[chosen] = cards[chosen], cards[upper]
    hands = tuple(
        tuple(cards[seat * 13 : (seat + 1) * 13]) for seat in range(4)
    )
    dealer = _dealer_for(
        root_seed=root_seed,
        index=index,
        policy=dealer_policy,
        initial_dealer=initial_dealer,
    )
    return BaseDeal.build(
        index=index,
        dealer=dealer,
        hands=hands,
        starting_score=starting_score,
    )


def generate_deal_bank(
    *,
    count: int,
    root_seed: int | str,
    dealer_policy: DealerPolicy,
    initial_dealer: int,
    starting_score: MatchScore,
    creation_metadata: dict[str, Any],
) -> DealBank:
    if type(count) is not int or count <= 0:
        raise DealBankError("deal-bank count must be positive")
    deals = tuple(
        generate_base_deal(
            root_seed=root_seed,
            index=index,
            dealer_policy=dealer_policy,
            initial_dealer=initial_dealer,
            starting_score=starting_score,
        )
        for index in range(count)
    )
    return DealBank.build(
        root_seed=root_seed,
        dealer_policy=dealer_policy,
        initial_dealer=initial_dealer,
        base_deals=deals,
        creation_metadata=creation_metadata,
    )


def deal_bank_to_data(bank: DealBank) -> dict[str, object]:
    return {
        **bank.semantic_data(),
        "content_digest": bank.content_digest,
        "creation_metadata": bank.creation_metadata,
        "deal_bank_id": bank.deal_bank_id,
    }


def deal_bank_from_data(
    value: object, *, expected_ruleset_id: str = RULESET_ID.value
) -> DealBank:
    obj = require_object(value, "deal bank")
    require_exact_keys(
        obj,
        {
            "base_deals",
            "content_digest",
            "creation_metadata",
            "deal_bank_id",
            "dealer_policy",
            "generator_id",
            "generator_version",
            "initial_dealer",
            "root_seed",
            "ruleset_id",
            "schema_version",
            "shuffle_algorithm",
        },
        "deal bank",
    )
    if obj["schema_version"] != DEAL_BANK_SCHEMA_VERSION:
        raise DealBankError("unsupported deal-bank schema_version")
    if obj["ruleset_id"] != expected_ruleset_id:
        raise DealBankError("deal-bank ruleset mismatch")
    if obj["generator_id"] != GENERATOR_ID or obj["generator_version"] != GENERATOR_VERSION:
        raise DealBankError("unsupported deal-bank generator")
    if obj["shuffle_algorithm"] != SHUFFLE_ALGORITHM:
        raise DealBankError("unsupported shuffle algorithm")
    try:
        policy = DealerPolicy(obj["dealer_policy"])
    except (TypeError, ValueError) as exc:
        raise DealBankError("unknown dealer policy") from exc
    raw_deals = obj["base_deals"]
    if type(raw_deals) is not list or not raw_deals:
        raise DealBankError("deal bank requires a nonempty base_deals array")
    return DealBank.build(
        root_seed=obj["root_seed"],
        dealer_policy=policy,
        initial_dealer=require_int(obj["initial_dealer"], "initial_dealer"),
        base_deals=tuple(base_deal_from_data(item) for item in raw_deals),
        creation_metadata=require_object(
            obj["creation_metadata"], "creation_metadata"
        ),
        claimed_deal_bank_id=obj["deal_bank_id"],
        claimed_content_digest=obj["content_digest"],
    )


def save_deal_bank(path: str | Path, bank: DealBank) -> None:
    atomic_write_canonical_json(path, deal_bank_to_data(bank))


def load_deal_bank(
    path: str | Path, *, expected_ruleset_id: str = RULESET_ID.value
) -> DealBank:
    return deal_bank_from_data(
        strict_json_load_file(path), expected_ruleset_id=expected_ruleset_id
    )
