"""Optional exact-tail continuation using the Phase 5B solver.

When the exact tail is enabled and a rollout reaches a trick-play position with at
most ``exact_tail_max_tricks_remaining`` tricks left, the rollout stops and the
Phase 5B solver supplies the position's exact double-dummy value instead. The
solver's answer is converted through the *same* utility adapter as a completed
rollout, because both reduce to the same :class:`DealOutcomeSummary` - so the tail
changes the continuation policy and never the currency.

What the tail is, honestly
--------------------------

The tail is **not** variance reduction for the same estimator. A rollout continues
with the configured Phase 4 policies; the solver continues with optimal play by all
four seats *in that sampled world*. Those are different continuations, so switching
one on changes what is being estimated:

* the rollout estimates "this action, then reference play by everyone";
* the tail estimates "this action, then reference play until the endgame, then
  perfect play by everyone who can see all the cards".

The second is more *accurate about the sampled world* and more *clairvoyant about
the real one*. Every seat in the tail knows every card, so the tail concentrates
exactly the perfect-information bias that makes PIMC suffer from strategy fusion.
It may well play worse. Phase 5C measures it rather than assuming either way; see
`docs/search/exact_tail_integration.md`.

Threshold
---------

The threshold is explicit configuration and behaviourally material. It is chosen
from the Phase 5B solver benchmark, not carried over from another game: a 4-trick
solve costs 0.86 ms on average and 4.4 ms at worst, a 5-trick solve 5.6 ms and
30 ms. At tens of solver calls per PIMC decision, 5 costs roughly 6.5x what 4 does
to buy one more exact trick, so 4 is the registered setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import DealState, EnginePhase
from tuppi_exact import SOLVER_ALGORITHM_ID, solve_late_game
from tuppi_exact.errors import SolverBudgetError, SolverError
from tuppi_rules import TRICKS_PER_DEAL

from .config import ExactTailFailurePolicy, PimcConfiguration
from .errors import ExactTailError
from .utilities import DealOutcomeSummary, exact_tail_summary


EXACT_TAIL_SCHEMA_VERSION = "tuppi.search.exact_tail.v1"


@dataclass(frozen=True, slots=True)
class TailVerdict:
    """The outcome of consulting the tail at one position.

    ``summary`` of ``None`` means "keep rolling out": either the threshold was not
    reached, or the solver refused and the configured policy is to fall back. The
    solver counters are reported either way so a refusal is never invisible.
    """

    summary: DealOutcomeSummary | None
    solver_calls: int
    solver_nodes: int
    refused: bool = False


@dataclass(frozen=True, slots=True)
class ExactTail:
    """The configured exact-tail continuation."""

    max_tricks_remaining: int
    node_budget: int
    failure_policy: ExactTailFailurePolicy
    solver_algorithm_id: str = field(default=SOLVER_ALGORITHM_ID, init=False)
    schema_version: str = field(default=EXACT_TAIL_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.max_tricks_remaining) is not int or not (
            1 <= self.max_tricks_remaining <= TRICKS_PER_DEAL
        ):
            raise ExactTailError("the tail threshold must be an integer in 1..13")
        if type(self.node_budget) is not int or self.node_budget <= 0:
            raise ExactTailError("the tail node budget must be a positive integer")
        if not isinstance(self.failure_policy, ExactTailFailurePolicy):
            raise ExactTailError(
                "failure_policy must be an ExactTailFailurePolicy value"
            )

    @classmethod
    def from_configuration(
        cls, configuration: PimcConfiguration
    ) -> "ExactTail | None":
        """Build the tail a configuration asks for, or ``None`` when disabled."""

        if not isinstance(configuration, PimcConfiguration):
            raise ExactTailError("from_configuration requires a PimcConfiguration")
        if not configuration.exact_tail_enabled:
            return None
        return cls(
            max_tricks_remaining=int(configuration.exact_tail_max_tricks_remaining),
            node_budget=int(configuration.exact_tail_node_budget),
            failure_policy=configuration.exact_tail_failure_policy,
        )

    def is_in_range(self, state: DealState) -> bool:
        """Whether this position is inside the configured exact range."""

        if not isinstance(state, DealState):
            raise ExactTailError("is_in_range requires a DealState")
        if state.phase is not EnginePhase.TRICK_PLAY:
            return False
        remaining = TRICKS_PER_DEAL - len(state.completed_tricks)
        return remaining <= self.max_tricks_remaining

    def consider(self, state: DealState, *, root_seat: int) -> TailVerdict | None:
        """Consult the tail at one trick-play position.

        Returns ``None`` when the threshold has not been reached, so the caller
        simply keeps rolling out. The tail is deliberately consulted *before* the
        acting seat chooses, which covers the case where the forced root action
        itself brought the position into range.
        """

        if state.phase is not EnginePhase.TRICK_PLAY:
            return None
        if not self.is_in_range(state):
            return None
        if state.contract is None:  # pragma: no cover - trick play implies a contract
            raise ExactTailError("trick play requires a resolved contract")
        completed = len(state.completed_tricks)
        try:
            solution = solve_late_game(
                state,
                maximum_tricks_remaining=self.max_tricks_remaining,
                node_budget=self.node_budget,
            )
        except (SolverBudgetError, SolverError) as exc:
            if self.failure_policy is ExactTailFailurePolicy.FALLBACK_ROLLOUT:
                return TailVerdict(
                    summary=None, solver_calls=1, solver_nodes=0, refused=True
                )
            raise ExactTailError(
                f"the exact tail refused at {TRICKS_PER_DEAL - completed} tricks "
                f"remaining and the failure policy is strict: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return TailVerdict(
            summary=exact_tail_summary(
                contract=state.contract,
                declarer=state.declarer,
                team0_tricks=solution.optimal_team0_tricks_final,
                starting_score=state.starting_score,
                root_seat=root_seat,
                tricks_simulated=completed,
                solver_nodes=solution.nodes_visited,
            ),
            solver_calls=1,
            solver_nodes=solution.nodes_visited,
        )

    def to_data(self) -> dict[str, object]:
        return {
            "failure_policy": self.failure_policy.value,
            "max_tricks_remaining": self.max_tricks_remaining,
            "node_budget": self.node_budget,
            "schema_version": EXACT_TAIL_SCHEMA_VERSION,
            "semantics": (
                "The tail replaces reference-policy continuation with exact "
                "double-dummy play in the sampled world. It changes the estimand, "
                "not the currency, and it concentrates perfect-information bias."
            ),
            "solver_algorithm_id": self.solver_algorithm_id,
        }
