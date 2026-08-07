"""Nested-budget convergence analysis over the frozen decision corpus.

Phase 5C found the four-world budget unconverged: one decision in six changed when
the budget doubled to eight. This module measures that properly, across five
budgets, on a stratified corpus, using **nested sample prefixes** so a change of
action is a change of opinion rather than a different sample.

Why nesting matters
-------------------

The Phase 5B sampler is an indexed deterministic stream and Phase 5C always consumes
its contiguous prefix, so the first N worlds of a 32-world budget *are* the N-world
budget's worlds. A world set is therefore built once at the largest budget and every
smaller budget re-evaluates its prefix. Without that, "the action changed" would be
confounded with "the worlds changed", and no amount of extra sampling would separate
them.

This is a convergence diagnostic, not a strength evaluation. An agent whose action
stops changing has stopped changing its mind; that says nothing about whether the
mind it has settled on is any good. Phase 5C already showed those are different
questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time

from tuppi_engine import EnginePhase

from .config import PimcConfiguration
from .corpus import CorpusPosition, DecisionCorpus
from .errors import SearchError
from .pimc import decide
from .random import (
    SearchSeedHierarchy,
    canonical_action_id,
    information_state_digest,
)
from .worlds import build_world_set


CONVERGENCE_SCHEMA_VERSION = "tuppi.search.budget_convergence.v1"

DEFAULT_BUDGETS: tuple[int, ...] = (2, 4, 8, 16, 32)
CONVERGENCE_DECISION_SEED = "tuppi-phase5d-a-convergence-v1"


@dataclass(frozen=True, slots=True)
class BudgetEvaluation:
    """One position evaluated at one budget."""

    world_count: int
    action_id: str
    mean_utility: float
    selection_gap: float
    unique_worlds: int
    duplicate_fraction: float
    seconds: float
    declared_contract: str | None
    action_ranking: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PositionConvergence:
    """Every budget's verdict on one position."""

    position: CorpusPosition
    evaluations: tuple[BudgetEvaluation, ...]

    @property
    def largest(self) -> BudgetEvaluation:
        return self.evaluations[-1]

    def agrees_with_largest(self, world_count: int) -> bool:
        for item in self.evaluations:
            if item.world_count == world_count:
                return item.action_id == self.largest.action_id
        raise SearchError(f"no evaluation at {world_count} worlds")


def _spearman(left: tuple[str, ...], right: tuple[str, ...]) -> float | None:
    """Rank correlation between two orderings of the same action set.

    Returns ``None`` when the ordering has fewer than two elements, where a rank
    correlation is undefined rather than zero.
    """

    if len(left) < 2 or set(left) != set(right):
        return None
    rank_right = {action: index for index, action in enumerate(right)}
    n = len(left)
    total = math.fsum(
        (index - rank_right[action]) ** 2 for index, action in enumerate(left)
    )
    return 1.0 - (6.0 * total) / (n * (n * n - 1))


def evaluate_position(
    position: CorpusPosition,
    *,
    budgets: tuple[int, ...] = DEFAULT_BUDGETS,
    base: PimcConfiguration | None = None,
) -> PositionConvergence:
    """Evaluate one position at every budget, reusing one nested world set."""

    from .registry import configuration_for

    if not budgets or sorted(budgets) != list(budgets):
        raise SearchError("budgets must be given in ascending order")
    template = base or configuration_for("uniform_feasible_pimc_small_v1")
    largest = max(budgets)
    biggest = PimcConfiguration.build(
        world_count=largest,
        rollout_policy_key=template.rollout_policy_key,
        utility_id=template.utility_id,
        exact_tail_enabled=template.exact_tail_enabled,
        exact_tail_max_tricks_remaining=template.exact_tail_max_tricks_remaining,
    )
    seeds = SearchSeedHierarchy(
        pimc_protocol=biggest.pimc_protocol_version,
        information_state=information_state_digest(position.observation),
        decision_seed=CONVERGENCE_DECISION_SEED,
    )
    full = build_world_set(
        position.observation, configuration=biggest, seeds=seeds
    )

    evaluations: list[BudgetEvaluation] = []
    for count in budgets:
        configuration = PimcConfiguration.build(
            world_count=count,
            rollout_policy_key=template.rollout_policy_key,
            utility_id=template.utility_id,
            exact_tail_enabled=template.exact_tail_enabled,
            exact_tail_max_tricks_remaining=(
                template.exact_tail_max_tricks_remaining
            ),
        )
        prefix = full.prefix(count)
        started = time.perf_counter()
        decision = decide(
            position.observation,
            configuration=configuration,
            decision_seed=CONVERGENCE_DECISION_SEED,
            reuse_world_set=prefix,
        )
        elapsed = time.perf_counter() - started
        ordering = tuple(
            item.action_id
            for item in sorted(
                decision.candidates,
                key=lambda candidate: (
                    -candidate.mean_utility,
                    candidate.action_order_index,
                ),
            )
        )
        declared = None
        if position.observation.phase is EnginePhase.SHOWING:
            declared = decision.selected_action.declared_contract.value
        evaluations.append(
            BudgetEvaluation(
                world_count=count,
                action_id=canonical_action_id(decision.selected_action),
                mean_utility=decision.selected_value,
                selection_gap=decision.selection_gap,
                unique_worlds=prefix.unique_world_count,
                duplicate_fraction=prefix.duplicate_fraction,
                seconds=elapsed,
                declared_contract=declared,
                action_ranking=ordering,
            )
        )
    return PositionConvergence(position=position, evaluations=tuple(evaluations))


def run_convergence(
    corpus: DecisionCorpus,
    *,
    budgets: tuple[int, ...] = DEFAULT_BUDGETS,
    showing_limit: int | None = None,
    trick_play_limit: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Run the nested-budget analysis over a (sub)sample of the corpus.

    ``showing_limit`` and ``trick_play_limit`` subsample the corpus because the full
    analysis is quadratic in cost: five budgets summing to 62 world-evaluations per
    position, at roughly 0.3 s per world-evaluation for a mid-deal trick position.
    The subsample is a stratified prefix of the corpus, and the counts are reported.
    """

    # ``None`` means "take all"; ``0`` means "take none". The two must not be
    # conflated, or asking for zero positions would silently analyse every one.
    showing = corpus.showing[
        : len(corpus.showing) if showing_limit is None else showing_limit
    ]
    play = corpus.trick_play[
        : len(corpus.trick_play) if trick_play_limit is None else trick_play_limit
    ]
    if showing_limit is not None and showing_limit < 0:
        raise SearchError("showing_limit must be None or nonnegative")
    if trick_play_limit is not None and trick_play_limit < 0:
        raise SearchError("trick_play_limit must be None or nonnegative")
    selected = showing + play
    if not selected:
        raise SearchError("the convergence analysis selected no position")

    results: list[PositionConvergence] = []
    for index, position in enumerate(selected):
        results.append(evaluate_position(position, budgets=budgets))
        if progress is not None:
            progress(index + 1, len(selected))

    return {
        "adjacent_agreement": _adjacent(results, budgets),
        "agreement_with_largest": _with_largest(results, budgets),
        "budgets": list(budgets),
        "by_stratum": _by_stratum(results, budgets),
        "corpus_id": corpus.corpus_id,
        "declaration_shift": _declarations(results, budgets),
        "duplicate_fraction": _duplicates(results, budgets),
        "interpretation": (
            "A convergence diagnostic, not a strength evaluation. Prefixes nest "
            "exactly, so a changed action is a changed opinion rather than a "
            "different sample. An agent that stops changing its mind has not "
            "thereby become correct."
        ),
        "positions": {
            "showing": len(showing),
            "total": len(selected),
            "trick_play": len(play),
        },
        "rank_correlation": _rank_correlation(results, budgets),
        "schema_version": CONVERGENCE_SCHEMA_VERSION,
        "selection_gap": _gaps(results, budgets),
        "timing_seconds": _timing(results, budgets),
    }


def _pairs(budgets: tuple[int, ...]):
    return tuple(zip(budgets, budgets[1:]))


def _adjacent(results, budgets) -> list[dict[str, object]]:
    out = []
    for smaller, larger in _pairs(budgets):
        agree = total = 0
        for item in results:
            by = {value.world_count: value.action_id for value in item.evaluations}
            total += 1
            if by[smaller] == by[larger]:
                agree += 1
        out.append(
            {
                "agreement_rate": round(agree / total, 6) if total else None,
                "agreements": agree,
                "comparisons": total,
                "from_worlds": smaller,
                "to_worlds": larger,
            }
        )
    return out


def _with_largest(results, budgets) -> list[dict[str, object]]:
    largest = budgets[-1]
    out = []
    for count in budgets:
        agree = sum(1 for item in results if item.agrees_with_largest(count))
        out.append(
            {
                "agreement_rate": round(agree / len(results), 6),
                "agreements": agree,
                "comparisons": len(results),
                "largest_worlds": largest,
                "world_count": count,
            }
        )
    return out


def _rank_correlation(results, budgets) -> list[dict[str, object]]:
    out = []
    for smaller, larger in _pairs(budgets):
        values = []
        for item in results:
            by = {value.world_count: value.action_ranking for value in item.evaluations}
            rho = _spearman(by[smaller], by[larger])
            if rho is not None:
                values.append(rho)
        out.append(
            {
                "from_worlds": smaller,
                "mean_spearman": round(math.fsum(values) / len(values), 6)
                if values
                else None,
                "positions_with_defined_correlation": len(values),
                "to_worlds": larger,
            }
        )
    return out


def _gaps(results, budgets) -> list[dict[str, object]]:
    out = []
    for count in budgets:
        values = [
            value.selection_gap
            for item in results
            for value in item.evaluations
            if value.world_count == count
        ]
        zero = sum(1 for value in values if value == 0.0)
        out.append(
            {
                "mean_gap": round(math.fsum(values) / len(values), 9),
                "tie_broken_by_canonical_order": zero,
                "tie_rate": round(zero / len(values), 6),
                "world_count": count,
            }
        )
    return out


def _declarations(results, budgets) -> list[dict[str, object]]:
    out = []
    for count in budgets:
        rami = total = 0
        for item in results:
            for value in item.evaluations:
                if value.world_count != count or value.declared_contract is None:
                    continue
                total += 1
                if value.declared_contract == "RAMI":
                    rami += 1
        out.append(
            {
                "rami_declaration_rate": round(rami / total, 6) if total else None,
                "showing_decisions": total,
                "world_count": count,
            }
        )
    return out


def _duplicates(results, budgets) -> list[dict[str, object]]:
    out = []
    for count in budgets:
        values = [
            value.duplicate_fraction
            for item in results
            for value in item.evaluations
            if value.world_count == count
        ]
        out.append(
            {
                "mean_duplicate_fraction": round(
                    math.fsum(values) / len(values), 6
                ),
                "world_count": count,
            }
        )
    return out


def _timing(results, budgets) -> list[dict[str, object]]:
    out = []
    for count in budgets:
        values = sorted(
            value.seconds
            for item in results
            for value in item.evaluations
            if value.world_count == count
        )
        out.append(
            {
                "mean_seconds": round(math.fsum(values) / len(values), 6),
                "median_seconds": round(values[len(values) // 2], 6),
                "total_seconds": round(math.fsum(values), 3),
                "world_count": count,
            }
        )
    return out


def _by_stratum(results, budgets) -> dict[str, object]:
    """Adjacent-budget agreement broken down by each stratum label."""

    grouped: dict[str, dict[str, dict[str, int]]] = {}
    for item in results:
        by = {value.world_count: value.action_id for value in item.evaluations}
        stable = all(
            by[smaller] == by[larger] for smaller, larger in _pairs(budgets)
        )
        for name, value in item.position.strata():
            bucket = grouped.setdefault(name, {}).setdefault(
                value, {"positions": 0, "stable_across_all_budgets": 0}
            )
            bucket["positions"] += 1
            bucket["stable_across_all_budgets"] += int(stable)
    return {
        name: {
            value: {
                **counts,
                "stability_rate": round(
                    counts["stable_across_all_budgets"] / counts["positions"], 6
                ),
            }
            for value, counts in sorted(values.items())
        }
        for name, values in sorted(grouped.items())
    }
