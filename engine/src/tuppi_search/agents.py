"""The deployable PIMC agent.

``UniformFeasiblePimcAgent`` satisfies the engine's ``Agent`` protocol - an
``identity`` and a ``choose_action(observation)`` - and receives nothing else. Its
constructor takes an immutable agent identity, an immutable PIMC configuration, and
an explicit policy seed. It has no parameter through which the true engine state,
the real deal, a hidden-state-derived identifier, an evaluator fixture identity, a
research result, or sealed-bank metadata could be passed, which is how the
information boundary is enforced rather than merely intended.

Per-decision seeds
------------------

The agent is deterministic. Its per-decision seed is derived from its policy seed
and the *information state*, so two different real deals that present the same
observation get the same seed and therefore the same worlds - the property
:mod:`tests.search.test_information_set_invariance` checks. The seat is included so
that two seats of the same partnership facing structurally similar positions do not
share a world stream by accident.
"""

from __future__ import annotations

from tuppi_engine import Action, PlayerObservation
from tuppi_eval.identities import AgentSpecification
from tuppi_eval.serialization import content_digest

from .config import PimcConfiguration
from .diagnostics import PimcDecisionDiagnostics
from .errors import PimcDecisionError
from .pimc import PimcDecision, decide
from .random import information_state_digest
from .rollout import SeatPolicies


DEFAULT_POLICY_SEED = "tuppi-phase5c-policy-seed-v1"


class UniformFeasiblePimcAgent:
    """One seat's deployable uniform-feasible PIMC agent."""

    __slots__ = (
        "_agent_id",
        "_configuration",
        "_seat",
        "_policy_seed",
        "_workers",
    )

    def __init__(
        self,
        *,
        agent_id: str,
        configuration: PimcConfiguration,
        seat: int,
        policy_seed: str = DEFAULT_POLICY_SEED,
        workers: int = 1,
    ) -> None:
        if not isinstance(agent_id, str) or not agent_id.startswith("agent:"):
            raise PimcDecisionError("a PIMC agent requires a canonical agent id")
        if not isinstance(configuration, PimcConfiguration):
            raise PimcDecisionError("a PIMC agent requires a PimcConfiguration")
        if type(seat) is not int or seat not in range(4):
            raise PimcDecisionError("seat must be an integer in 0..3")
        if not isinstance(policy_seed, str) or not policy_seed:
            raise PimcDecisionError("policy_seed must be a nonempty string")
        if type(workers) is not int or workers < 1:
            raise PimcDecisionError("workers must be an integer of at least 1")
        self._agent_id = agent_id
        self._configuration = configuration
        self._seat = seat
        self._policy_seed = policy_seed
        # Runtime only. It is absent from `agent_id` and from `configuration_id`
        # by design: `config`'s docstring lists worker count among the things
        # that cannot change what the agent plays, and the parallel decision is
        # required to be identical, so two agents differing only here are the
        # same agent.
        self._workers = workers

    @property
    def identity(self) -> str:
        return self._agent_id

    @property
    def workers(self) -> int:
        """How many processes one decision may use. Not part of the identity."""

        return self._workers

    @property
    def configuration(self) -> PimcConfiguration:
        return self._configuration

    @property
    def seat(self) -> int:
        return self._seat

    def decision_seed(self, observation: PlayerObservation) -> str:
        """Derive this decision's seed from the policy seed and information state."""

        return content_digest(
            {
                "agent_id": self._agent_id,
                "configuration_id": self._configuration.configuration_id,
                "information_state": information_state_digest(observation),
                "policy_seed": self._policy_seed,
                "schema_version": "tuppi.search.decision_seed.v1",
                "seat": self._seat,
            }
        )

    def choose_action(self, observation: PlayerObservation) -> Action:
        """The engine-facing method. Returns only the action."""

        return self.decide(observation).selected_action

    def decide(self, observation: PlayerObservation) -> PimcDecision:
        """Return the complete decision, including candidate summaries."""

        if not isinstance(observation, PlayerObservation):
            raise PimcDecisionError("a PIMC agent requires a PlayerObservation")
        if observation.observing_seat != self._seat:
            raise PimcDecisionError(
                f"agent for seat {self._seat} received an observation for seat "
                f"{observation.observing_seat}"
            )
        return decide(
            observation,
            configuration=self._configuration,
            decision_seed=self.decision_seed(observation),
            workers=self._workers,
        )

    def explain(self, observation: PlayerObservation) -> PimcDecisionDiagnostics:
        """Return privacy-safe diagnostics for one decision.

        Computes the identical ranking as :meth:`choose_action`, so asking for an
        explanation cannot change what would have been played.
        """

        decision = self.decide(observation)
        policies = SeatPolicies(
            configuration=self._configuration, root_seat=self._seat
        )
        return PimcDecisionDiagnostics(
            agent_id=self._agent_id,
            decision=decision,
            rollout_policy_agent_ids=policies.policy_agent_ids,
        )


def construct_pimc_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    configuration: PimcConfiguration,
    policy_seed: str = DEFAULT_POLICY_SEED,
) -> UniformFeasiblePimcAgent:
    """Construct a PIMC agent from its immutable specification.

    The specification's recorded configuration must match the configuration handed
    in. A mismatch means the agent would play differently from what its identity
    claims, which is the one failure mode an identity system exists to prevent.
    """

    if not isinstance(specification, AgentSpecification):
        raise PimcDecisionError("construct_pimc_agent requires an AgentSpecification")
    recorded = specification.configuration.get("pimc_configuration_id")
    if recorded != configuration.configuration_id:
        raise PimcDecisionError(
            "the specification records PIMC configuration "
            f"{recorded!r} but was handed {configuration.configuration_id!r}"
        )
    return UniformFeasiblePimcAgent(
        agent_id=specification.agent_id,
        configuration=configuration,
        seat=seat,
        policy_seed=policy_seed,
    )
