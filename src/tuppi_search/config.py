"""The immutable, content-addressed PIMC configuration.

Everything that can change what the agent plays lives in this object and is
digested into its ``configuration_id``. Everything that cannot - worker count,
output paths, whether diagnostics were requested - lives outside it. That split is
the reason a Phase 5C result can be attributed to a specific agent: two runs with
the same ``configuration_id`` played the same way, and a run that played
differently has a different identifier.

Deterministic budgets, not wall-clock
-------------------------------------

The semantic definition of a Phase 5C agent is a *fixed amount of work*: a world
count, a replica count, and an exact-tail threshold. Wall-clock stopping is
deliberately not part of the agent definition. A time-limited agent plays
differently on a loaded machine, so its results would not be reproducible and its
identity would be a fiction. Timing is measured separately, as operational data.

Replicas and deterministic policies
-----------------------------------

Phase 4 rollout policies are deterministic, so replaying the same world with the
same policies produces the identical rollout. The configuration therefore
*rejects* ``rollout_replicas > 1`` while every configured policy is deterministic,
rather than silently spending N times the compute to average N identical numbers.
The field exists because a later stochastic policy will need it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_eval.serialization import content_digest
from tuppi_exact import DEFAULT_NODE_BUDGET, SOLVER_ALGORITHM_ID
from tuppi_exact.sampling import SAMPLER_ALGORITHM_ID

from .errors import SearchConfigurationError
from .random import SEED_PROTOCOL_VERSION
from .utilities import UtilityId, is_registerable


PIMC_PROTOCOL_VERSION = "tuppi.search.pimc.v1"
PIMC_CONFIGURATION_SCHEMA_VERSION = "tuppi.search.pimc_configuration.v1"

#: The Phase 5B sampler produces an indexed stream; Phase 5C always consumes the
#: contiguous prefix, so a larger budget strictly extends a smaller one's worlds.
SAMPLE_INDEX_PROTOCOL = "contiguous_prefix_from_zero_v1"

ACTION_ORDERING_ID = "tuppi.engine.legal_action_order.v1"
TIE_BREAK_ID = "highest_mean_utility_then_lowest_legal_action_index_v1"

#: Rollout policies Phase 5C may use. All are frozen Phase 4 profiles, all are
#: deterministic, and all are observation-only.
SUPPORTED_ROLLOUT_POLICIES: tuple[str, ...] = (
    "reactive_contract_v1",
    "public_counting_v1",
    "partner_aware_v1",
)

#: Phase 5A designated ``partner_aware_v1`` as ``development_reference_v1``: the
#: strongest rung the complete-match data supports. It is the natural default
#: rollout policy and the natural evaluation opponent.
DEVELOPMENT_REFERENCE_POLICY = "partner_aware_v1"

#: Chosen from the Phase 5B solver benchmark: a 4-trick solve costs 0.86 ms mean
#: and 4.4 ms worst case, while a 5-trick solve costs 5.6 ms mean and 30 ms worst
#: case. At tens of solver calls per decision, 5 is roughly 6.5x the cost of 4 for
#: one extra trick of exactness, so 4 is the supported threshold.
DEFAULT_EXACT_TAIL_MAX_TRICKS_REMAINING = 4

#: The largest threshold Phase 5B measured as exact. Above this the solver refuses.
MAXIMUM_EXACT_TAIL_TRICKS_REMAINING = 5


class RootContinuation(StrEnum):
    """What the root seat does on its *later* turns inside a rollout."""

    #: Standard one-ply PIMC: after the forced root action every seat, including
    #: the root's own future turns, uses the configured rollout policy. This is
    #: what keeps Phase 5C from silently becoming recursive search.
    ROLLOUT_POLICY = "rollout_policy"

    #: The root seat's later turns use a separately configured policy. A distinct
    #: mode with a distinct agent identity; never the default.
    ALTERNATE_ROLLOUT_POLICY = "alternate_rollout_policy"


class FailurePolicy(StrEnum):
    """What to do when a world or rollout fails."""

    #: Any internal correctness failure invalidates the whole decision. This is
    #: the only policy a registered Phase 5C agent may use: dropping worlds would
    #: reweight the sample, and failures that correlate with the position would
    #: bias the average in an unknown direction.
    STRICT = "strict"


class ExactTailFailurePolicy(StrEnum):
    """What to do when the exact solver refuses or exceeds its budget."""

    STRICT = "strict"
    FALLBACK_ROLLOUT = "fallback_rollout"


@dataclass(frozen=True, slots=True)
class PimcConfiguration:
    """One complete, immutable PIMC agent definition."""

    configuration_id: str
    world_count: int
    rollout_replicas: int
    rollout_policy_key: str
    root_continuation: RootContinuation
    root_rollout_policy_key: str | None
    utility_id: UtilityId
    exact_tail_enabled: bool
    exact_tail_max_tricks_remaining: int | None
    exact_tail_node_budget: int | None
    exact_tail_failure_policy: ExactTailFailurePolicy
    showing_search_enabled: bool
    failure_policy: FailurePolicy
    pimc_protocol_version: str = field(default=PIMC_PROTOCOL_VERSION, init=False)
    sampler_algorithm_id: str = field(default=SAMPLER_ALGORITHM_ID, init=False)
    sample_index_protocol: str = field(default=SAMPLE_INDEX_PROTOCOL, init=False)
    solver_algorithm_id: str = field(default=SOLVER_ALGORITHM_ID, init=False)
    action_ordering_id: str = field(default=ACTION_ORDERING_ID, init=False)
    tie_break_id: str = field(default=TIE_BREAK_ID, init=False)
    seed_protocol: str = field(default=SEED_PROTOCOL_VERSION, init=False)
    schema_version: str = field(
        default=PIMC_CONFIGURATION_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        if type(self.world_count) is not int or not 1 <= self.world_count <= 4096:
            raise SearchConfigurationError("world_count must be an integer in 1..4096")
        if type(self.rollout_replicas) is not int or not (
            1 <= self.rollout_replicas <= 64
        ):
            raise SearchConfigurationError(
                "rollout_replicas must be an integer in 1..64"
            )
        if self.rollout_policy_key not in SUPPORTED_ROLLOUT_POLICIES:
            raise SearchConfigurationError(
                f"unsupported rollout policy {self.rollout_policy_key!r}"
            )
        if not isinstance(self.root_continuation, RootContinuation):
            raise SearchConfigurationError(
                "root_continuation must be a RootContinuation value"
            )
        if self.root_continuation is RootContinuation.ROLLOUT_POLICY:
            if self.root_rollout_policy_key is not None:
                raise SearchConfigurationError(
                    "standard one-ply PIMC has no separate root rollout policy"
                )
        elif self.root_rollout_policy_key not in SUPPORTED_ROLLOUT_POLICIES:
            raise SearchConfigurationError(
                "the alternate root mode requires a supported root rollout policy"
            )
        if not isinstance(self.utility_id, UtilityId):
            raise SearchConfigurationError("utility_id must be a UtilityId value")
        if type(self.exact_tail_enabled) is not bool:
            raise SearchConfigurationError("exact_tail_enabled must be a boolean")
        if self.exact_tail_enabled:
            if (
                type(self.exact_tail_max_tricks_remaining) is not int
                or not 1
                <= self.exact_tail_max_tricks_remaining
                <= MAXIMUM_EXACT_TAIL_TRICKS_REMAINING
            ):
                raise SearchConfigurationError(
                    "the exact-tail threshold must be an integer in 1.."
                    f"{MAXIMUM_EXACT_TAIL_TRICKS_REMAINING}"
                )
            if (
                type(self.exact_tail_node_budget) is not int
                or self.exact_tail_node_budget <= 0
            ):
                raise SearchConfigurationError(
                    "an enabled exact tail requires a positive node budget"
                )
        else:
            if self.exact_tail_max_tricks_remaining is not None:
                raise SearchConfigurationError(
                    "a disabled exact tail must not carry a threshold"
                )
            if self.exact_tail_node_budget is not None:
                raise SearchConfigurationError(
                    "a disabled exact tail must not carry a node budget"
                )
        if not isinstance(self.exact_tail_failure_policy, ExactTailFailurePolicy):
            raise SearchConfigurationError(
                "exact_tail_failure_policy must be an ExactTailFailurePolicy"
            )
        if type(self.showing_search_enabled) is not bool:
            raise SearchConfigurationError("showing_search_enabled must be a boolean")
        if not isinstance(self.failure_policy, FailurePolicy):
            raise SearchConfigurationError("failure_policy must be a FailurePolicy")
        if self.rollout_replicas > 1 and self.all_policies_deterministic:
            raise SearchConfigurationError(
                "every configured rollout policy is deterministic, so replicas "
                "beyond the first would reproduce the first exactly; use "
                "rollout_replicas=1 and raise world_count instead"
            )
        expected = f"pimcfg:{content_digest(self.identity_data())}"
        if self.configuration_id != expected:
            raise SearchConfigurationError(
                "configuration_id disagrees with the behavioural content"
            )

    @property
    def all_policies_deterministic(self) -> bool:
        """True while every configured rollout policy is a frozen Phase 4 agent.

        Phase 4 agents are deterministic by construction and their specifications
        record it, so this is a fact about the configuration rather than a hope.
        """

        return True

    @property
    def rollout_policy_for_seat_keys(self) -> tuple[str, str, str, str]:
        """The rollout policy key used at each seat, for reporting.

        The root seat's *first* action is forced by the candidate, so this
        describes only later turns. In standard one-ply PIMC every seat shares one
        policy, which is what makes the value an estimate of "this action followed
        by reference play" rather than of recursive search.
        """

        return (
            self.rollout_policy_key,
            self.rollout_policy_key,
            self.rollout_policy_key,
            self.rollout_policy_key,
        )

    @property
    def total_rollouts_per_candidate(self) -> int:
        return self.world_count * self.rollout_replicas

    def identity_data(self) -> dict[str, object]:
        """Behaviourally material content only."""

        return {
            "action_ordering_id": ACTION_ORDERING_ID,
            "exact_tail_enabled": self.exact_tail_enabled,
            "exact_tail_failure_policy": self.exact_tail_failure_policy.value,
            "exact_tail_max_tricks_remaining": self.exact_tail_max_tricks_remaining,
            "exact_tail_node_budget": self.exact_tail_node_budget,
            "failure_policy": self.failure_policy.value,
            "pimc_protocol_version": PIMC_PROTOCOL_VERSION,
            "root_continuation": self.root_continuation.value,
            "root_rollout_policy_key": self.root_rollout_policy_key,
            "rollout_policy_key": self.rollout_policy_key,
            "rollout_replicas": self.rollout_replicas,
            "sample_index_protocol": SAMPLE_INDEX_PROTOCOL,
            "sampler_algorithm_id": SAMPLER_ALGORITHM_ID,
            "schema_version": PIMC_CONFIGURATION_SCHEMA_VERSION,
            "seed_protocol": SEED_PROTOCOL_VERSION,
            "showing_search_enabled": self.showing_search_enabled,
            "solver_algorithm_id": SOLVER_ALGORITHM_ID,
            "tie_break_id": TIE_BREAK_ID,
            "utility_id": self.utility_id.value,
            "world_count": self.world_count,
        }

    def to_data(self) -> dict[str, object]:
        payload = dict(self.identity_data())
        payload["configuration_id"] = self.configuration_id
        payload["semantic_work_budget"] = {
            "rollout_replicas": self.rollout_replicas,
            "rollouts_per_candidate": self.total_rollouts_per_candidate,
            "stopping_rule": "deterministic_work_budget",
            "world_count": self.world_count,
        }
        return payload

    @classmethod
    def build(
        cls,
        *,
        world_count: int,
        rollout_policy_key: str = DEVELOPMENT_REFERENCE_POLICY,
        rollout_replicas: int = 1,
        root_continuation: RootContinuation = RootContinuation.ROLLOUT_POLICY,
        root_rollout_policy_key: str | None = None,
        utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
        exact_tail_enabled: bool = False,
        exact_tail_max_tricks_remaining: int | None = None,
        exact_tail_node_budget: int | None = None,
        exact_tail_failure_policy: ExactTailFailurePolicy = (
            ExactTailFailurePolicy.STRICT
        ),
        showing_search_enabled: bool = True,
        failure_policy: FailurePolicy = FailurePolicy.STRICT,
    ) -> "PimcConfiguration":
        if exact_tail_enabled and exact_tail_max_tricks_remaining is None:
            exact_tail_max_tricks_remaining = (
                DEFAULT_EXACT_TAIL_MAX_TRICKS_REMAINING
            )
        if exact_tail_enabled and exact_tail_node_budget is None:
            exact_tail_node_budget = DEFAULT_NODE_BUDGET
        values = {
            "world_count": world_count,
            "rollout_replicas": rollout_replicas,
            "rollout_policy_key": rollout_policy_key,
            "root_continuation": root_continuation,
            "root_rollout_policy_key": root_rollout_policy_key,
            "utility_id": utility_id,
            "exact_tail_enabled": exact_tail_enabled,
            "exact_tail_max_tricks_remaining": exact_tail_max_tricks_remaining,
            "exact_tail_node_budget": exact_tail_node_budget,
            "exact_tail_failure_policy": exact_tail_failure_policy,
            "showing_search_enabled": showing_search_enabled,
            "failure_policy": failure_policy,
        }
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        for name, value in (
            ("pimc_protocol_version", PIMC_PROTOCOL_VERSION),
            ("sampler_algorithm_id", SAMPLER_ALGORITHM_ID),
            ("sample_index_protocol", SAMPLE_INDEX_PROTOCOL),
            ("solver_algorithm_id", SOLVER_ALGORITHM_ID),
            ("action_ordering_id", ACTION_ORDERING_ID),
            ("tie_break_id", TIE_BREAK_ID),
            ("seed_protocol", SEED_PROTOCOL_VERSION),
            ("schema_version", PIMC_CONFIGURATION_SCHEMA_VERSION),
        ):
            object.__setattr__(provisional, name, value)
        computed = f"pimcfg:{content_digest(provisional.identity_data())}"
        return cls(configuration_id=computed, **values)

    def require_registerable_utility(self) -> None:
        if not is_registerable(self.utility_id):
            raise SearchConfigurationError(
                f"{self.utility_id.value} is a diagnostic adapter and may not be "
                "the utility of a registered agent"
            )
