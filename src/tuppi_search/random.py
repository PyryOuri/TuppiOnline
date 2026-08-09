"""Domain-separated deterministic seeding for the search layer.

Every random quantity in Phase 5C is a pure function of explicit, named
coordinates. There is no module-global RNG, no mutable shared stream, no process
identity, no wall-clock time, and no use of Python's ``hash()`` - which is salted
per process and would make a run irreproducible.

The coordinate namespace
------------------------

A seed is derived from a canonical JSON object over the coordinates that are
*semantically* responsible for the value:

``pimc_protocol``      the search protocol version
``information_state``  the digest of the acting seat's complete information set
``decision_seed``      the caller's explicit per-decision seed
``domain``             which quantity is being drawn
``sample_index``       which sampled world
``candidate_action``   which root action (rollout domains only)
``rollout_replica``    which replica of a stochastic rollout
``acting_seat``        which simulated seat
``decision_index``     which simulated decision inside a rollout

**World sampling never includes the candidate action.** That is the load-bearing
rule of the whole design: if the world set depended on the candidate, each action
would be evaluated on its own private worlds and the comparison between actions
would be confounded by sampling noise instead of controlled by common random
numbers.

Rollout domains *may* include the candidate action, because different root actions
produce genuinely different histories and a shared per-decision stream would
couple unrelated decisions. Phase 5C's registered agents use deterministic
rollout policies, so no rollout randomness is drawn at all; the coordinates exist
so that a later stochastic policy has a documented, non-improvised place to sit.

Information-state identity
--------------------------

:func:`information_state_digest` digests the *whole* observation: the public
history and the observing seat's own hand, which together are exactly the
information set. Two different real deals that produce the same observation
therefore produce the same digest, the same seeds, and the same worlds - which is
what :mod:`tests.search.test_information_set_invariance` checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from enum import StrEnum
import hashlib

from tuppi_engine import PlayerObservation
from tuppi_eval.serialization import content_digest
from tuppi_rules import card_to_code

from .errors import SeedError


SEED_PROTOCOL_VERSION = "tuppi.search.seed_hierarchy.v1"
INFORMATION_STATE_SCHEMA_VERSION = "tuppi.search.information_state.v1"


class SeedDomain(StrEnum):
    """The named quantities Phase 5C may draw randomness for."""

    HIDDEN_WORLD_SAMPLING = "hidden_world_sampling"
    ROLLOUT_REPLICA = "rollout_replica"
    ROLLOUT_SEAT_DECISION = "rollout_seat_decision"
    ROLLOUT_POLICY = "rollout_policy"
    ANALYSIS = "analysis"


#: Domains that may legitimately depend on which root action is being evaluated.
CANDIDATE_DEPENDENT_DOMAINS: frozenset[SeedDomain] = frozenset(
    {
        SeedDomain.ROLLOUT_REPLICA,
        SeedDomain.ROLLOUT_SEAT_DECISION,
        SeedDomain.ROLLOUT_POLICY,
    }
)


def information_state_digest(observation: PlayerObservation) -> str:
    """Digest the acting seat's complete information set.

    The digest covers everything the seat legitimately knows and nothing else:
    its own hand, the public showing and play history, the resolved contract, the
    match score, the seating, and the legal action set. It deliberately includes
    the public ``match_ref`` and ``deal_ref``, which the complete-match protocol
    derives from an ordinal precisely so that they carry no fixture identity.
    """

    if not isinstance(observation, PlayerObservation):
        raise SeedError("information_state_digest requires a PlayerObservation")
    return content_digest(
        {
            "completed_tricks": [
                {
                    "leader": trick.leader,
                    "plays": [
                        {"card": card_to_code(play.card), "seat": play.seat}
                        for play in trick.plays
                    ],
                    "trick_index": trick.trick_index,
                    "winner": trick.winner,
                }
                for trick in observation.completed_tricks
            ],
            "contract": (
                None if observation.contract is None else observation.contract.value
            ),
            "current_actor": observation.current_actor,
            "current_trick": [
                {"card": card_to_code(play.card), "seat": play.seat}
                for play in observation.current_trick
            ],
            "deal_ref": observation.deal_ref,
            "dealer": observation.dealer,
            "declarer": observation.declarer,
            "first_leader": observation.first_leader,
            "forehand": observation.forehand,
            "legal_actions": [
                _action_label(action) for action in observation.legal_actions
            ],
            "match_ref": observation.match_ref,
            "match_score": list(observation.match_score.as_tuple()),
            "observing_seat": observation.observing_seat,
            "own_hand": [card_to_code(card) for card in observation.own_hand],
            "phase": observation.phase.value,
            "publicly_shown_cards": [
                {"card": card_to_code(card), "seat": seat}
                for seat, card in observation.publicly_shown_cards
            ],
            "schema_version": INFORMATION_STATE_SCHEMA_VERSION,
            "show_actions": [
                {
                    "declared_contract": action.declared_contract.value,
                    "seat": action.seat,
                    "shown_card": card_to_code(action.shown_card),
                    "verbal_required": action.verbal_required,
                }
                for action in observation.show_actions
            ],
            "team_tricks": list(observation.team_tricks),
        }
    )


def _action_label(action: object) -> str:
    from tuppi_engine import PlayCardAction, ShowAction

    if isinstance(action, PlayCardAction):
        return f"play:{action.seat}:{card_to_code(action.card)}"
    if isinstance(action, ShowAction):
        return (
            f"show:{action.seat}:{card_to_code(action.shown_card)}:"
            f"{action.declared_contract.value}"
        )
    raise SeedError("unknown action type in an information state")


@lru_cache(maxsize=512)
def canonical_action_id(action: object) -> str:
    """Return the stable identifier of one candidate root action."""

    return _action_label(action)


@dataclass(frozen=True, slots=True)
class SearchSeedHierarchy:
    """A frozen set of coordinates from which every seed is derived."""

    pimc_protocol: str
    information_state: str
    decision_seed: str
    protocol_version: str = field(default=SEED_PROTOCOL_VERSION, init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("pimc_protocol", self.pimc_protocol),
            ("information_state", self.information_state),
            ("decision_seed", self.decision_seed),
        ):
            if not isinstance(value, str) or not value:
                raise SeedError(f"{label} must be a nonempty string")

    def derive(
        self,
        domain: SeedDomain,
        *,
        sample_index: int | None = None,
        candidate_action_id: str | None = None,
        rollout_replica: int | None = None,
        acting_seat: int | None = None,
        decision_index: int | None = None,
    ) -> str:
        """Derive one canonical child seed.

        Passing ``candidate_action_id`` for a candidate-independent domain is an
        error rather than a silently ignored argument: the world set must not
        depend on the action, and a typo that made it depend on the action would
        otherwise be invisible.
        """

        if not isinstance(domain, SeedDomain):
            raise SeedError("domain must be a SeedDomain value")
        if candidate_action_id is not None and domain not in (
            CANDIDATE_DEPENDENT_DOMAINS
        ):
            raise SeedError(
                f"domain {domain.value!r} must not depend on the candidate action"
            )
        for label, value in (
            ("sample_index", sample_index),
            ("rollout_replica", rollout_replica),
            ("acting_seat", acting_seat),
            ("decision_index", decision_index),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise SeedError(f"{label} must be a nonnegative integer")
        if acting_seat is not None and acting_seat not in range(4):
            raise SeedError("acting_seat must be an integer in 0..3")
        return content_digest(
            {
                "acting_seat": acting_seat,
                "candidate_action_id": candidate_action_id,
                "decision_index": decision_index,
                "decision_seed": self.decision_seed,
                "domain": domain.value,
                "information_state": self.information_state,
                "pimc_protocol": self.pimc_protocol,
                "protocol_version": self.protocol_version,
                "rollout_replica": rollout_replica,
                "sample_index": sample_index,
                "schema_version": SEED_PROTOCOL_VERSION,
            }
        )

    def world_sampling_seed(self) -> str:
        """The single seed the hidden-world sampler consumes.

        One seed for the whole indexed set, not one per world: the Phase 5B
        sampler is already an indexed deterministic stream, so re-seeding per
        index would discard its prefix-stability guarantee - the property that
        makes a larger budget reuse a smaller one's worlds exactly.
        """

        return self.derive(SeedDomain.HIDDEN_WORLD_SAMPLING)

    def identity_data(self) -> dict[str, object]:
        return {
            "decision_seed": self.decision_seed,
            "information_state": self.information_state,
            "pimc_protocol": self.pimc_protocol,
            "protocol_version": self.protocol_version,
        }


def stable_text_digest(text: str) -> str:
    """Digest a string without Python's per-process salted ``hash()``."""

    if not isinstance(text, str):
        raise SeedError("stable_text_digest requires a string")
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
