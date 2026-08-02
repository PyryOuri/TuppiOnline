"""Simple evaluator-fixture agents constructed only from immutable specs."""

from __future__ import annotations

import hashlib

from tuppi_engine import (
    Action,
    Agent,
    FixedScriptAgent,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    action_from_data,
)
from tuppi_rules import Contract, card_to_index

from .errors import RegistryError
from .identities import AgentSpecification, SeedPolicy


class _IdentifiedAgent:
    def __init__(self, agent_id: str) -> None:
        self._identity = agent_id

    @property
    def identity(self) -> str:
        return self._identity


class FirstLegalAgent(_IdentifiedAgent):
    def choose_action(self, observation: PlayerObservation) -> Action:
        if not observation.legal_actions:
            raise RegistryError("first-legal agent received no legal action")
        return observation.legal_actions[0]


class OrderedLegalAgent(_IdentifiedAgent):
    def __init__(self, agent_id: str, *, highest: bool) -> None:
        super().__init__(agent_id)
        self._highest = highest

    def choose_action(self, observation: PlayerObservation) -> Action:
        actions = observation.legal_actions
        if not actions:
            raise RegistryError("ordered-legal agent received no legal action")
        plays = tuple(action for action in actions if isinstance(action, PlayCardAction))
        if plays:
            return sorted(
                plays,
                key=lambda action: card_to_index(action.card),
                reverse=self._highest,
            )[0]
        shows = tuple(action for action in actions if isinstance(action, ShowAction))
        if not shows:
            raise RegistryError("ordered-legal agent received an unknown action type")
        contract_rank = {Contract.NOLO: 0, Contract.RAMI: 1}
        return sorted(
            shows,
            key=lambda action: (
                contract_rank[action.declared_contract],
                -card_to_index(action.shown_card)
                if self._highest
                else card_to_index(action.shown_card),
            ),
        )[0]


class ShowSelectionAgent(_IdentifiedAgent):
    def __init__(
        self, agent_id: str, *, preferred_contract: Contract, highest: bool
    ) -> None:
        super().__init__(agent_id)
        self._preferred_contract = preferred_contract
        self._highest = highest

    def choose_action(self, observation: PlayerObservation) -> Action:
        if not observation.legal_actions:
            raise RegistryError("show-selection agent received no legal action")
        if isinstance(observation.legal_actions[0], PlayCardAction):
            plays = tuple(
                action
                for action in observation.legal_actions
                if isinstance(action, PlayCardAction)
            )
            return sorted(
                plays,
                key=lambda action: card_to_index(action.card),
                reverse=self._highest,
            )[0]
        shows = tuple(
            action
            for action in observation.legal_actions
            if isinstance(action, ShowAction)
        )
        preferred = tuple(
            action
            for action in shows
            if action.declared_contract is self._preferred_contract
        )
        candidates = preferred or shows
        return sorted(
            candidates,
            key=lambda action: card_to_index(action.shown_card),
            reverse=self._highest,
        )[0]


class SeededRandomLegalAgent(_IdentifiedAgent):
    """Digest-counter sampling avoids process-global or Python RNG state."""

    def __init__(self, agent_id: str, *, seed: str) -> None:
        super().__init__(agent_id)
        if not isinstance(seed, str) or not seed:
            raise RegistryError("seeded agent requires an explicit seed")
        self._seed = seed
        self._counter = 0

    def choose_action(self, observation: PlayerObservation) -> Action:
        actions = observation.legal_actions
        if not actions:
            raise RegistryError("seeded-random agent received no legal action")
        material = (
            f"tuppi.eval.agent_rng.v1\0{self._seed}\0{self._counter}\0"
            f"{observation.match_ref}\0{observation.deal_ref}\0"
            f"{observation.observing_seat}"
        ).encode("utf-8")
        self._counter += 1
        index = int.from_bytes(hashlib.sha256(material).digest(), "big") % len(actions)
        return actions[index]


class _FixedIdentifiedAgent(_IdentifiedAgent):
    def __init__(self, agent_id: str, actions: tuple[Action, ...]) -> None:
        super().__init__(agent_id)
        self._delegate = FixedScriptAgent(actions)

    def choose_action(self, observation: PlayerObservation) -> Action:
        return self._delegate.choose_action(observation)


def construct_agent(
    specification: AgentSpecification,
    *,
    seed: str | None,
    seat: int,
    scripted_actions: tuple[Action, ...] | None = None,
) -> Agent:
    """Construct a fresh runtime object for exactly one seat."""

    if not isinstance(specification, AgentSpecification):
        raise RegistryError("construct_agent requires an AgentSpecification")
    if type(seat) is not int or seat not in range(4):
        raise RegistryError("agent construction seat must be in 0..3")
    implementation = specification.implementation_reference
    configuration = specification.configuration
    if implementation.startswith("tuppi_agents."):
        # Phase 4 strategic policies live in their own package and receive only
        # the specification, the seat, and (never, for deterministic policies) a
        # seed. The import is local so that the evaluation package keeps no
        # module-level dependency on the strategic layer.
        from tuppi_agents.factory import construct_registered_agent

        if scripted_actions is not None:
            raise RegistryError(
                "a strategic specification does not consume scripted actions"
            )
        return construct_registered_agent(specification, seat=seat, seed=seed)
    if specification.seed_policy is SeedPolicy.NONE and seed is not None:
        raise RegistryError("deterministic specification must not receive a seed")
    if (
        specification.seed_policy is SeedPolicy.DERIVED_PER_ENTRY_SEAT
        and seed is None
    ):
        raise RegistryError("seeded specification requires a derived seed")
    if implementation == "tuppi_eval.agents:first_legal_v1":
        return FirstLegalAgent(specification.agent_id)
    if implementation == "tuppi_eval.agents:lowest_legal_v1":
        return OrderedLegalAgent(specification.agent_id, highest=False)
    if implementation == "tuppi_eval.agents:highest_legal_v1":
        return OrderedLegalAgent(specification.agent_id, highest=True)
    if implementation == "tuppi_eval.agents:seeded_random_legal_v1":
        return SeededRandomLegalAgent(specification.agent_id, seed=seed or "")
    if implementation == "tuppi_eval.agents:show_selection_v1":
        try:
            preferred = Contract(configuration["preferred_contract"])
            highest = configuration["card_order"].endswith("descending")
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RegistryError("invalid show-selection configuration") from exc
        return ShowSelectionAgent(
            specification.agent_id,
            preferred_contract=preferred,
            highest=highest,
        )
    if implementation == "tuppi_eval.agents:fixed_script_v1":
        actions = scripted_actions
        if actions is None:
            try:
                raw = configuration["actions"]
                if type(raw) is not list:
                    raise TypeError
                parsed = tuple(action_from_data(item) for item in raw)
                actions = tuple(action for action in parsed if action.seat == seat)
            except (KeyError, TypeError, ValueError) as exc:
                raise RegistryError("invalid fixed-script configuration") from exc
        return _FixedIdentifiedAgent(specification.agent_id, actions)
    raise RegistryError(f"unsupported implementation reference {implementation!r}")
