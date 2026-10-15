"""Independent finite multi-observer oracle for Phase 5E.

This toy game is intentionally separate from the production tree and engine. It
contains one hidden world bit, one partner information set shared across worlds,
and two opponent information sets separated by the opponent's private signal.
It catches whether an implementation can share a partner node while allowing an
observer-specific opponent node, without ever using the production search code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


TINY_MULTI_OBSERVER_SCHEMA_VERSION = "tuppi.search.tiny_multi_observer_reference.v1"


@dataclass(frozen=True, slots=True)
class TinyMultiObserverWorld:
    name: str
    opponent_signal: str
    payoff: tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True, slots=True)
class TinyMultiObserverReference:
    """Exact policy enumeration plus independent finite UCT prefixes."""

    worlds: tuple[TinyMultiObserverWorld, ...]
    action_b_payoff: float
    partner_actions: tuple[str, str] = ("X", "Y")
    opponent_actions: tuple[str, str] = ("L", "R")

    @classmethod
    def structural_counterexample(cls) -> "TinyMultiObserverReference":
        """Return the PIMC/root-only/multi-observer separation."""

        return cls(
            worlds=(
                TinyMultiObserverWorld(
                    "world-0", "opp0", ((1.0, 0.0), (0.0, 0.0))
                ),
                TinyMultiObserverWorld(
                    "world-1", "opp1", ((0.0, 0.0), (0.0, 1.0))
                ),
            ),
            action_b_payoff=0.6,
        )

    def pimc_values(self) -> dict[str, float]:
        return {
            "A": sum(max(max(row) for row in world.payoff) for world in self.worlds)
            / len(self.worlds),
            "B": self.action_b_payoff,
        }

    def root_only_fixed_values(self) -> dict[str, float]:
        # The frozen diagnostic policy chooses X and L from its observations.
        return {
            "A": sum(world.payoff[0][0] for world in self.worlds) / len(self.worlds),
            "B": self.action_b_payoff,
        }

    def exact_information_set_values(self) -> dict[str, float]:
        values = {"B": self.action_b_payoff}
        partner_values = []
        for partner_index in range(len(self.partner_actions)):
            total = 0.0
            for world in self.worlds:
                # The opponent's signal is observable to the opponent, so its
                # action may be selected independently for each signal class.
                total += max(world.payoff[partner_index])
            partner_values.append(total / len(self.worlds))
        values["A"] = max(partner_values)
        return values

    def exact_best_action(self) -> str:
        values = self.exact_information_set_values()
        return max(values, key=lambda action: (values[action], -("A", "B").index(action)))

    def pimc_best_action(self) -> str:
        values = self.pimc_values()
        return max(values, key=lambda action: (values[action], -("A", "B").index(action)))

    def root_only_prefix(self, budget: int) -> dict[str, object]:
        if type(budget) is not int or budget <= 0:
            raise ValueError("budget must be positive")
        stats = {action: [0, 0.0] for action in ("A", "B")}
        for _ in range(budget):
            action = _select(stats)
            payoff = self.root_only_fixed_values()[action]
            stats[action][0] += 1
            stats[action][1] += payoff
        return _result(stats, budget, algorithm="root_only_fixed_rollout_v1")

    def multi_observer_prefix(self, budget: int) -> dict[str, object]:
        if type(budget) is not int or budget <= 0:
            raise ValueError("budget must be positive")
        root = {action: [0, 0.0] for action in ("A", "B")}
        partner = {action: [0, 0.0] for action in self.partner_actions}
        opponent = {
            signal: {action: [0, 0.0] for action in self.opponent_actions}
            for signal in ("opp0", "opp1")
        }
        for simulation in range(budget):
            world = self.worlds[simulation % len(self.worlds)]
            action = _select(root)
            path = [(root, action)]
            if action == "A":
                partner_action = _select(partner)
                opponent_stats = opponent[world.opponent_signal]
                opponent_action = _select(opponent_stats)
                path.extend(((partner, partner_action), (opponent_stats, opponent_action)))
                payoff = world.payoff[
                    self.partner_actions.index(partner_action)
                ][self.opponent_actions.index(opponent_action)]
            else:
                payoff = self.action_b_payoff
            for stats, selected in path:
                stats[selected][0] += 1
                stats[selected][1] += payoff
        result = _result(root, budget, algorithm="redeterminizing_ismcts_v1")
        result["partner_visits"] = {key: value[0] for key, value in partner.items()}
        result["opponent_visits"] = {
            signal: {key: value[0] for key, value in stats.items()}
            for signal, stats in opponent.items()
        }
        return result


def _mean(value: list[float | int]) -> float:
    return value[1] / value[0] if value[0] else 0.0


def _select(
    stats: dict[str, list[float | int]], exploration_constant: float = math.sqrt(2.0)
) -> str:
    unvisited = [action for action, value in stats.items() if value[0] == 0]
    if unvisited:
        return unvisited[0]
    parent_visits = sum(value[0] for value in stats.values())
    return max(
        stats,
        key=lambda action: (
            _mean(stats[action])
            + exploration_constant
            * math.sqrt(math.log(max(1, parent_visits)) / stats[action][0]),
            -tuple(stats).index(action),
        ),
    )


def _result(
    stats: dict[str, list[float | int]], budget: int, *, algorithm: str
) -> dict[str, object]:
    selected = max(
        stats,
        key=lambda action: (
            stats[action][0],
            _mean(stats[action]),
            -tuple(stats).index(action),
        ),
    )
    return {
        "action": selected,
        "algorithm": algorithm,
        "budget": budget,
        "mean_utilities": {action: _mean(value) for action, value in stats.items()},
        "visits": {action: value[0] for action, value in stats.items()},
        "schema_version": TINY_MULTI_OBSERVER_SCHEMA_VERSION,
    }


__all__ = (
    "TINY_MULTI_OBSERVER_SCHEMA_VERSION",
    "TinyMultiObserverReference",
    "TinyMultiObserverWorld",
)
