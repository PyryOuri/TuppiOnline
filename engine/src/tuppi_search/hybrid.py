"""Phase-gated PIMC variants: search one phase, delegate the other.

Phase 5C measured full PIMC losing decisively. It could not say *which* decisions
lost the matches, because one agent made both the contract choice and every card
choice. These two variants split that apart:

``uniform_feasible_pimc_play_only_v1``
    The frozen ``partner_aware_v1`` policy chooses the show; PIMC chooses every
    card.
``uniform_feasible_pimc_show_only_v1``
    PIMC chooses the show; the frozen ``partner_aware_v1`` policy chooses every
    card.

Between them they partition the decisions of full PIMC, so comparing each against
the reference isolates the contribution of each phase.

Delegation is exact, not approximate
------------------------------------

The delegate is a real ``partner_aware_v1`` agent built by the frozen Phase 4
factory, and the gated agent forwards the observation to it untouched. So "uses the
frozen reference showing policy exactly" is not a claim to be re-verified against a
reimplementation - there is no reimplementation.
:mod:`tests.search.test_phase5d_hybrid` asserts action-by-action equality against a
directly constructed reference agent anyway, because the cheap check is worth having.

Identity by composition, not mutation
-------------------------------------

Adding a phase-gate field to :class:`PimcConfiguration` would change every Phase 5C
``configuration_id`` and therefore every Phase 5C ``agent_id``, silently
invalidating the committed Phase 5C registry digest and the negative baseline it
records. So the gate is a *separate* object that composes an unmodified
``PimcConfiguration``, and it carries its own content address. Phase 5C's identities
are untouched, which :mod:`tests.search.test_phase5d_identities` verifies.

Still one ply
-------------

Neither variant introduces recursion. PIMC's rollouts continue to use the frozen
rollout policy at every seat, including the root seat's later turns, so no search is
ever invoked inside a rollout at any depth.
:func:`tuppi_search.validation.recursive_search_problems` enforces that structurally:
the modules a rollout executes may not construct a search agent at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_agents import construct_agent
from tuppi_engine import Action, EnginePhase, PlayerObservation
from tuppi_eval.identities import AgentSpecification
from tuppi_eval.serialization import content_digest

from .agents import DEFAULT_POLICY_SEED, UniformFeasiblePimcAgent
from .config import (
    DEVELOPMENT_REFERENCE_POLICY,
    ExactTailFailurePolicy,
    FailurePolicy,
    PimcConfiguration,
    RootContinuation,
    policy_specifications,
)
from .errors import PimcDecisionError, SearchConfigurationError
from .pimc import PimcDecision
from .utilities import UtilityId


PHASE_GATE_SCHEMA_VERSION = "tuppi.search.phase_gated_configuration.v1"

class SearchedPhase(StrEnum):
    """Which decisions the search owns. Everything else is delegated."""

    #: PIMC chooses cards; the frozen policy chooses the show.
    TRICK_PLAY_ONLY = "trick_play_only"

    #: PIMC chooses the show; the frozen policy chooses every card.
    SHOWING_ONLY = "showing_only"

    #: PIMC chooses the opening lead and nothing else: the frozen policy chooses
    #: the show and every card after the first. This is the only scope that is
    #: not a whole phase, which is why the gate's predicate is over decisions
    #: rather than phases - see :meth:`PhaseGatedConfiguration.searches_decision`.
    OPENING_LEAD_ONLY = "opening_lead_only"


#: What each scope hands to the frozen delegate. Reporting only, but *not*
#: cosmetic: ``phase5d_a_specification`` records this string in its configuration
#: payload, so it is digested into those agents' identities. The two phase-scoped
#: entries are therefore built from ``EnginePhase`` exactly as before, and a test
#: pins the committed identities against any drift here.
_DELEGATED_DESCRIPTION: dict[SearchedPhase, str] = {
    SearchedPhase.TRICK_PLAY_ONLY: EnginePhase.SHOWING.value,
    SearchedPhase.SHOWING_ONLY: EnginePhase.TRICK_PLAY.value,
    # Neither phase is wholly delegated, so neither phase value would be true.
    SearchedPhase.OPENING_LEAD_ONLY: (
        f"{EnginePhase.SHOWING.value} and {EnginePhase.TRICK_PLAY.value} "
        "after the opening lead"
    ),
}


def is_opening_lead(observation: PlayerObservation) -> bool:
    """Whether this observation is the first card decision of the deal.

    Defined on the public observation alone: trick play, no completed trick, and
    no card yet played into the current one. Exactly one decision per deal
    satisfies it, and only ``first_leader`` ever faces it — a seat that is not
    the opening leader never searches under an opening-lead gate. That is what
    "opening lead" means, and it is deliberately narrower than "each seat's first
    card", which would be four decisions with three different information states.
    """

    if not isinstance(observation, PlayerObservation):
        raise SearchConfigurationError("is_opening_lead requires a PlayerObservation")
    return (
        observation.phase is EnginePhase.TRICK_PLAY
        and not observation.completed_tricks
        and not observation.current_trick
    )


@dataclass(frozen=True, slots=True)
class PhaseGatedConfiguration:
    """A PIMC configuration restricted to one decision phase.

    Composes an unmodified :class:`PimcConfiguration` so that Phase 5C's content
    addresses stay exactly as committed.
    """

    gate_id: str
    searched_phase: SearchedPhase
    delegate_policy_key: str
    pimc: PimcConfiguration
    schema_version: str = field(default=PHASE_GATE_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.searched_phase, SearchedPhase):
            raise SearchConfigurationError(
                "searched_phase must be a SearchedPhase value"
            )
        if not isinstance(self.pimc, PimcConfiguration):
            raise SearchConfigurationError(
                "a phase gate composes a PimcConfiguration"
            )
        if self.delegate_policy_key not in policy_specifications():
            raise SearchConfigurationError(
                f"unknown delegate policy {self.delegate_policy_key!r}"
            )
        if (
            self.searched_phase is SearchedPhase.SHOWING_ONLY
            and not self.pimc.showing_search_enabled
        ):
            raise SearchConfigurationError(
                "a show-only gate needs a PIMC configuration with showing search on"
            )
        expected = f"gate:{content_digest(self.identity_data())}"
        if self.gate_id != expected:
            raise SearchConfigurationError(
                "gate_id disagrees with the behavioural content"
            )

    def identity_data(self) -> dict[str, object]:
        return {
            "delegate_policy_key": self.delegate_policy_key,
            "pimc_configuration": self.pimc.identity_data(),
            "schema_version": PHASE_GATE_SCHEMA_VERSION,
            "searched_phase": self.searched_phase.value,
        }

    def to_data(self) -> dict[str, object]:
        payload = dict(self.identity_data())
        payload["gate_id"] = self.gate_id
        payload["pimc_configuration_id"] = self.pimc.configuration_id
        payload["delegated_phase"] = _DELEGATED_DESCRIPTION[self.searched_phase]
        return payload

    @classmethod
    def build(
        cls,
        *,
        searched_phase: SearchedPhase,
        pimc: PimcConfiguration,
        delegate_policy_key: str = DEVELOPMENT_REFERENCE_POLICY,
    ) -> "PhaseGatedConfiguration":
        # Validated here rather than only in ``__post_init__``: the content address
        # is computed from ``identity_data`` first, so a malformed argument would
        # otherwise surface as an AttributeError from inside the digest.
        if not isinstance(searched_phase, SearchedPhase):
            raise SearchConfigurationError(
                "searched_phase must be a SearchedPhase value"
            )
        if not isinstance(pimc, PimcConfiguration):
            raise SearchConfigurationError(
                "a phase gate composes a PimcConfiguration"
            )
        values = {
            "searched_phase": searched_phase,
            "delegate_policy_key": delegate_policy_key,
            "pimc": pimc,
        }
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "schema_version", PHASE_GATE_SCHEMA_VERSION)
        return cls(
            gate_id=f"gate:{content_digest(provisional.identity_data())}", **values
        )

    def searches(self, phase: EnginePhase) -> bool:
        """Whether this configuration searches at every decision in ``phase``.

        Defined only for the two phase-scoped values. An opening-lead gate has no
        yes/no answer for trick play — it searches one decision there and
        delegates the rest — so it raises rather than returning a misleading
        ``True``. Use :meth:`searches_decision`, which answers for every scope.
        """

        if self.searched_phase is SearchedPhase.OPENING_LEAD_ONLY:
            raise SearchConfigurationError(
                "an opening-lead gate is not phase-scoped, so whether it searches "
                "in a phase is not a well-formed question; ask searches_decision "
                "about a specific observation instead"
            )
        if phase is EnginePhase.SHOWING:
            return self.searched_phase is SearchedPhase.SHOWING_ONLY
        if phase is EnginePhase.TRICK_PLAY:
            return self.searched_phase is SearchedPhase.TRICK_PLAY_ONLY
        raise SearchConfigurationError(
            f"a decision cannot occur in phase {phase.value}"
        )

    def searches_decision(self, observation: PlayerObservation) -> bool:
        """Whether this configuration searches at *this* decision.

        The authoritative predicate. It reads only the public observation, so a
        gate cannot scope itself on anything a seat is not entitled to know —
        which is what keeps "search only the opening lead" from becoming a
        channel for private information.
        """

        if not isinstance(observation, PlayerObservation):
            raise SearchConfigurationError(
                "searches_decision requires a PlayerObservation"
            )
        phase = observation.phase
        if phase is EnginePhase.SHOWING:
            return self.searched_phase is SearchedPhase.SHOWING_ONLY
        if phase is EnginePhase.TRICK_PLAY:
            if self.searched_phase is SearchedPhase.TRICK_PLAY_ONLY:
                return True
            if self.searched_phase is SearchedPhase.OPENING_LEAD_ONLY:
                return is_opening_lead(observation)
            return False
        raise SearchConfigurationError(
            f"a decision cannot occur in phase {phase.value}"
        )


class PhaseGatedPimcAgent:
    """A deployable agent that searches one phase and delegates the other.

    Receives exactly what any Phase 5C agent receives: a formal observation, an
    immutable configuration, an explicit policy seed, and its seat. There is no
    parameter for engine state, real hands, deal identity, or fixture identity.
    """

    __slots__ = ("_agent_id", "_gate", "_seat", "_policy_seed", "_pimc", "_delegate")

    def __init__(
        self,
        *,
        agent_id: str,
        gate: PhaseGatedConfiguration,
        seat: int,
        policy_seed: str = DEFAULT_POLICY_SEED,
        workers: int = 1,
    ) -> None:
        if not isinstance(agent_id, str) or not agent_id.startswith("agent:"):
            raise PimcDecisionError("a gated agent requires a canonical agent id")
        if not isinstance(gate, PhaseGatedConfiguration):
            raise PimcDecisionError("a gated agent requires a PhaseGatedConfiguration")
        if type(seat) is not int or seat not in range(4):
            raise PimcDecisionError("seat must be an integer in 0..3")
        if not isinstance(policy_seed, str) or not policy_seed:
            raise PimcDecisionError("policy_seed must be a nonempty string")
        self._agent_id = agent_id
        self._gate = gate
        self._seat = seat
        self._policy_seed = policy_seed
        self._pimc = UniformFeasiblePimcAgent(
            agent_id=agent_id,
            configuration=gate.pimc,
            seat=seat,
            policy_seed=policy_seed,
            workers=workers,
        )
        # Resolved through the merged registry so the delegate may be the
        # production incumbent, not only a frozen Phase 4 profile.
        # `construct_agent` matches an improved specification by identity.
        specification = policy_specifications()[gate.delegate_policy_key]
        self._delegate = construct_agent(specification, seat=seat)

    @property
    def identity(self) -> str:
        return self._agent_id

    @property
    def gate(self) -> PhaseGatedConfiguration:
        return self._gate

    @property
    def seat(self) -> int:
        return self._seat

    @property
    def delegate_identity(self) -> str:
        return self._delegate.identity

    @property
    def workers(self) -> int:
        """Processes one searched decision may use. Not part of the identity.

        An opening-lead gate searches once per deal, so this buys latency on
        exactly the decision under the bound and costs nothing on the ~53 it
        delegates.
        """

        return self._pimc.workers

    def searches(self, observation: PlayerObservation) -> bool:
        return self._gate.searches_decision(observation)

    def choose_action(self, observation: PlayerObservation) -> Action:
        """Search this phase, or forward the observation to the frozen policy."""

        if not isinstance(observation, PlayerObservation):
            raise PimcDecisionError("a gated agent requires a PlayerObservation")
        if observation.observing_seat != self._seat:
            raise PimcDecisionError(
                f"agent for seat {self._seat} received an observation for seat "
                f"{observation.observing_seat}"
            )
        if self._gate.searches_decision(observation):
            return self._pimc.choose_action(observation)
        return self._delegate.choose_action(observation)

    def decide(self, observation: PlayerObservation) -> PimcDecision | None:
        """Return the PIMC decision, or ``None`` when this phase is delegated."""

        if not self._gate.searches_decision(observation):
            return None
        return self._pimc.decide(observation)

    def explain(self, observation: PlayerObservation):
        if not self._gate.searches_decision(observation):
            raise PimcDecisionError(
                f"this configuration delegates this {observation.phase.value} "
                f"decision to {self._gate.delegate_policy_key}; there is no "
                "search to explain"
            )
        return self._pimc.explain(observation)


#: Behavioural fields of a `PimcConfiguration`, with the enum each restores to.
#: The remaining entries in `identity_data` are protocol constants that `build`
#: fixes rather than accepts, so restoring them is neither needed nor possible.
_REBUILT_ENUMS = {
    "root_continuation": RootContinuation,
    "utility_id": UtilityId,
    "exact_tail_failure_policy": ExactTailFailurePolicy,
    "failure_policy": FailurePolicy,
}
_REBUILT_PLAIN = (
    "world_count",
    "rollout_replicas",
    "rollout_policy_key",
    "root_rollout_policy_key",
    "exact_tail_enabled",
    "exact_tail_max_tricks_remaining",
    "exact_tail_node_budget",
    "showing_search_enabled",
)


def gate_from_specification(
    specification: AgentSpecification,
) -> PhaseGatedConfiguration:
    """Rebuild the gate a gated specification describes.

    A gated agent needs a `PhaseGatedConfiguration`, which is a separate object
    from the specification precisely so that Phase 5C's content addresses stay
    untouched. The consequence was that any path holding only a specification —
    the arena, a campaign harness, anything reading a recorded artifact — could
    not construct the agent at all, and only registered gates had a construction
    route. An opening-lead selector is deliberately not registered, so it had
    none.

    This closes that. The specification payload carries every behavioural field
    of the composed `PimcConfiguration` plus the searched phase and the delegate,
    so the gate is fully recoverable from it. Nothing is trusted on the way: the
    rebuilt configuration must reproduce the recorded `pimc_configuration_id` and
    the rebuilt gate must reproduce the recorded `phase_gate_id`. A wrong mapping
    or an edited payload changes a digest and raises here rather than quietly
    constructing a different agent.
    """

    if not isinstance(specification, AgentSpecification):
        raise PimcDecisionError(
            "gate_from_specification requires an AgentSpecification"
        )
    payload = specification.configuration
    recorded_gate = payload.get("phase_gate_id")
    recorded_pimc = payload.get("pimc_configuration_id")
    if not isinstance(recorded_gate, str) or not isinstance(recorded_pimc, str):
        raise PimcDecisionError(
            "this specification records no phase gate; it is not a gated agent"
        )
    kwargs: dict = {name: payload[name] for name in _REBUILT_PLAIN}
    for name, enum in _REBUILT_ENUMS.items():
        kwargs[name] = enum(payload[name])
    pimc = PimcConfiguration.build(**kwargs)
    if pimc.configuration_id != recorded_pimc:
        raise PimcDecisionError(
            f"rebuilt PIMC configuration {pimc.configuration_id!r} disagrees with "
            f"the recorded {recorded_pimc!r}"
        )
    gate = PhaseGatedConfiguration.build(
        searched_phase=SearchedPhase(payload["searched_phase"]),
        pimc=pimc,
        delegate_policy_key=payload["frozen_delegate_policy_key"],
    )
    if gate.gate_id != recorded_gate:
        raise PimcDecisionError(
            f"rebuilt gate {gate.gate_id!r} disagrees with the recorded "
            f"{recorded_gate!r}"
        )
    return gate


def construct_gated_agent_from_specification(
    specification: AgentSpecification,
    *,
    seat: int,
    policy_seed: str = DEFAULT_POLICY_SEED,
    workers: int = 1,
) -> PhaseGatedPimcAgent:
    """Construct a gated agent from its specification alone.

    The entry point a harness wants: it needs no prior handle on the gate, and
    the gate it rebuilds is verified against the specification's own content
    addresses before anything is constructed.
    """

    return construct_gated_agent(
        specification,
        seat=seat,
        gate=gate_from_specification(specification),
        policy_seed=policy_seed,
        workers=workers,
    )


def construct_gated_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    gate: PhaseGatedConfiguration,
    policy_seed: str = DEFAULT_POLICY_SEED,
    workers: int = 1,
) -> PhaseGatedPimcAgent:
    """Construct a gated agent from its immutable specification."""

    if not isinstance(specification, AgentSpecification):
        raise PimcDecisionError("construct_gated_agent requires an AgentSpecification")
    recorded = specification.configuration.get("phase_gate_id")
    if recorded != gate.gate_id:
        raise PimcDecisionError(
            f"the specification records phase gate {recorded!r} but was handed "
            f"{gate.gate_id!r}"
        )
    return PhaseGatedPimcAgent(
        agent_id=specification.agent_id,
        gate=gate,
        seat=seat,
        policy_seed=policy_seed,
        workers=workers,
    )
