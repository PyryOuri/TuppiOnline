"""Restricted perfect-information diagnostics. **Not an agent.**

Everything in this module reads the *real* hidden hands, which is exactly what a
deployable agent must never do. It exists to answer questions about the search that
cannot be asked from inside the information set:

* how often does PIMC's choice agree with the full-information optimum?
* what is the value of perfect hidden-state knowledge at this position?
* did the sampled world set contain the true world at all?

Every answer is labelled a **perfect-information diagnostic**. None is a strength
claim, and none may be attributed to the deployable agent.

Why the class is deliberately awkward
-------------------------------------

``OracleDiagnostic`` has no ``identity`` property and no ``choose_action`` method,
so it does not satisfy the engine's ``Agent`` protocol and cannot be handed to the
engine, the arena, or the complete-match protocol even by accident. It is not
registerable, it never appears in cross-play, and it can never hold a promotion
role. :mod:`tests.search.test_oracle` asserts the protocol mismatch rather than
trusting the comment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import DealState, EnginePhase, PlayerObservation, observation_for
from tuppi_exact import solve_late_game
from tuppi_exact.errors import SolverBudgetError
from tuppi_rules import card_to_code

from .config import PimcConfiguration
from .errors import OracleError
from .pimc import PimcDecision, decide
from .worlds import world_identity


ORACLE_SCHEMA_VERSION = "tuppi.search.perfect_information_diagnostic.v1"


@dataclass(frozen=True, slots=True)
class OracleComparison:
    """One perfect-information comparison at a single real position."""

    root_seat: int
    phase: str
    tricks_remaining: int
    legal_action_count: int
    pimc_action: str
    perfect_information_optimal_actions: tuple[str, ...]
    pimc_action_is_optimal: bool
    true_world_in_sample: bool
    sampled_world_count: int
    unique_world_count: int
    exact_feasible_assignment_count: int
    label: str = field(default="perfect_information_diagnostic", init=False)
    schema_version: str = field(default=ORACLE_SCHEMA_VERSION, init=False)

    def to_data(self) -> dict[str, object]:
        return {
            "exact_feasible_assignment_count": (
                self.exact_feasible_assignment_count
            ),
            "label": self.label,
            "legal_action_count": self.legal_action_count,
            "perfect_information_optimal_actions": list(
                self.perfect_information_optimal_actions
            ),
            "phase": self.phase,
            "pimc_action": self.pimc_action,
            "pimc_action_is_optimal": self.pimc_action_is_optimal,
            "root_seat": self.root_seat,
            "sampled_world_count": self.sampled_world_count,
            "schema_version": ORACLE_SCHEMA_VERSION,
            "tricks_remaining": self.tricks_remaining,
            "true_world_in_sample": self.true_world_in_sample,
            "unique_world_count": self.unique_world_count,
        }


class OracleDiagnostic:
    """A restricted diagnostic that may read the real state.

    Intentionally *not* an ``Agent``: no ``identity``, no ``choose_action``.
    """

    __slots__ = ("_configuration", "_decision_seed", "_maximum_tricks_remaining")

    def __init__(
        self,
        *,
        configuration: PimcConfiguration,
        decision_seed: str,
        maximum_tricks_remaining: int = 4,
    ) -> None:
        if not isinstance(configuration, PimcConfiguration):
            raise OracleError("the oracle requires a PimcConfiguration")
        if not isinstance(decision_seed, str) or not decision_seed:
            raise OracleError("the oracle requires a nonempty decision seed")
        self._configuration = configuration
        self._decision_seed = decision_seed
        self._maximum_tricks_remaining = maximum_tricks_remaining

    def compare(self, state: DealState) -> OracleComparison | None:
        """Compare PIMC's choice with the full-information optimum at one position.

        Returns ``None`` when the position is outside the exact solver's range, so
        a caller cannot silently receive a heuristic answer dressed as an oracle.
        """

        if not isinstance(state, DealState):
            raise OracleError("the oracle compares against a real DealState")
        if state.phase is not EnginePhase.TRICK_PLAY:
            return None
        actor = state.current_actor
        if actor is None:
            return None
        observation = observation_for(state, actor)
        if len(observation.legal_actions) < 2:
            return None
        try:
            solution = solve_late_game(
                state, maximum_tricks_remaining=self._maximum_tricks_remaining
            )
        except SolverBudgetError:
            return None

        decision = decide(
            observation,
            configuration=self._configuration,
            decision_seed=self._decision_seed,
        )
        optimal = tuple(
            f"play:{actor}:{card_to_code(card)}" for card in solution.optimal_cards
        )
        pimc_label = _play_label(decision)
        return OracleComparison(
            root_seat=actor,
            phase=observation.phase.value,
            tricks_remaining=solution.tricks_remaining,
            legal_action_count=len(observation.legal_actions),
            pimc_action=pimc_label,
            perfect_information_optimal_actions=optimal,
            pimc_action_is_optimal=pimc_label in optimal,
            true_world_in_sample=_true_world_in_sample(decision, state, observation),
            sampled_world_count=(
                0 if decision.world_set is None else len(decision.world_set)
            ),
            unique_world_count=(
                0
                if decision.world_set is None
                else decision.world_set.unique_world_count
            ),
            exact_feasible_assignment_count=(
                1
                if decision.world_set is None
                else decision.world_set.feasible_assignment_count
            ),
        )


def _play_label(decision: PimcDecision) -> str:
    from tuppi_engine import PlayCardAction

    action = decision.selected_action
    if not isinstance(action, PlayCardAction):
        raise OracleError("the oracle compares trick-play decisions only")
    return f"play:{action.seat}:{card_to_code(action.card)}"


def _true_world_in_sample(
    decision: PimcDecision, state: DealState, observation: PlayerObservation
) -> bool:
    """Whether the sampled world set contained the real hidden allocation.

    This is the single quantity a deployable agent must never compute, which is why
    it lives here and why the agent's diagnostics record does not have a field for
    it. Sampler coverage is a property of the *experiment*, not information the
    player may act on.
    """

    from tuppi_exact.sampling import HiddenHandAssignment

    if decision.world_set is None:
        return False
    truth = HiddenHandAssignment(
        observing_seat=observation.observing_seat,
        hands=tuple(tuple(hand) for hand in state.hands),
        sampled_owner={},
        sample_index=0,
    )
    identity = world_identity(truth)
    return any(item.world_id == identity for item in decision.world_set.worlds)


def summarize_comparisons(
    comparisons: tuple[OracleComparison, ...],
) -> dict[str, object]:
    """Aggregate perfect-information diagnostics, labelled as such."""

    if not comparisons:
        raise OracleError("no comparisons to summarize")
    total = len(comparisons)
    agreements = sum(1 for item in comparisons if item.pimc_action_is_optimal)
    covered = sum(1 for item in comparisons if item.true_world_in_sample)
    return {
        "agreement_rate": round(agreements / total, 6),
        "agreements": agreements,
        "comparisons": total,
        "interpretation": (
            "Agreement with the full-information optimum is a perfect-information "
            "diagnostic. Disagreement is not necessarily an error: the "
            "full-information optimum is unavailable to a player inside the "
            "information set, and a policy that matched it would be clairvoyant."
        ),
        "label": "perfect_information_diagnostic",
        "schema_version": ORACLE_SCHEMA_VERSION,
        "true_world_coverage_rate": round(covered / total, 6),
        "true_world_covered": covered,
    }
