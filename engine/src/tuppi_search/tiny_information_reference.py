"""Independent tiny information-set reference and strategy-fusion diagnostic.

This module is intentionally independent of the production engine and UCT tree.
It is a finite two-world decision problem with an exact enumerator.  Its purpose is
to catch the specific error that ordinary PIMC can look excellent by choosing a
different future action in each hidden world even when those worlds are
observationally indistinguishable.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math


TINY_REFERENCE_SCHEMA_VERSION = "tuppi.search.tiny_exact_information_reference.v1"


@dataclass(frozen=True, slots=True)
class TinyWorld:
    name: str
    future_payoff: tuple[float, float]


@dataclass(frozen=True, slots=True)
class TinyInformationSetReference:
    """A complete exact reference for one constructed two-stage game."""

    worlds: tuple[TinyWorld, ...]
    action_b_payoff: float
    future_actions: tuple[str, str] = ("X", "Y")

    def __post_init__(self) -> None:
        if len(self.worlds) != 2:
            raise ValueError("the tiny reference intentionally has two worlds")
        if any(len(world.future_payoff) != 2 for world in self.worlds):
            raise ValueError("each tiny world needs two future payoffs")
        if not 0.0 <= self.action_b_payoff <= 1.0:
            raise ValueError("the fixed B payoff must be bounded")

    @classmethod
    def strategy_fusion_counterexample(cls) -> "TinyInformationSetReference":
        """Return the preregistered A-versus-B strategy-fusion example.

        After initial action A, both hidden worlds yield the same future root
        observation.  World 0 rewards X and world 1 rewards Y.  B pays 0.65 in
        both worlds.  Clairvoyant PIMC gets 1.0 from A by fusing X and Y; an exact
        information-set policy gets only 0.5 from A and therefore chooses B.
        """

        return cls(
            worlds=(
                TinyWorld("world-0", (1.0, 0.0)),
                TinyWorld("world-1", (0.0, 1.0)),
            ),
            action_b_payoff=0.65,
        )

    def exact_information_set_values(self) -> dict[str, float]:
        """Enumerate the one shared future action and return exact values."""

        candidates: dict[str, float] = {"B": self.action_b_payoff}
        candidates["A"] = max(
            sum(world.future_payoff[index] for world in self.worlds) / len(self.worlds)
            for index in range(len(self.future_actions))
        )
        return candidates

    def exact_best_action(self) -> str:
        values = self.exact_information_set_values()
        return max(values, key=lambda action: (values[action], -("A", "B").index(action)))

    def pimc_values(self) -> dict[str, float]:
        """Evaluate A with a separate future action in every hidden world."""

        clairvoyant_a = sum(max(world.future_payoff) for world in self.worlds) / len(self.worlds)
        return {"A": clairvoyant_a, "B": self.action_b_payoff}

    def pimc_best_action(self) -> str:
        values = self.pimc_values()
        return max(values, key=lambda action: (values[action], -("A", "B").index(action)))

    def uct_prefix(self, budget: int, *, exploration_constant: float = math.sqrt(2.0)) -> dict[str, object]:
        """Run an independent deterministic UCT implementation on the tiny game.

        The future node key is the literal observation ``after-A`` for both
        worlds.  No hidden world name enters that key.  This is a diagnostic
        oracle, not a call into :mod:`tuppi_search.root_info_uct`.
        """

        if type(budget) is not int or budget <= 0:
            raise ValueError("budget must be positive")
        root = {action: [0, 0.0] for action in ("A", "B")}
        future = {action: [0, 0.0] for action in self.future_actions}
        for simulation in range(budget):
            world = self.worlds[_deterministic_world_index(simulation)]
            root_action = _select(root, exploration_constant)
            if root_action == "A":
                future_action = _select(future, exploration_constant)
                payoff = world.future_payoff[self.future_actions.index(future_action)]
                future[future_action][0] += 1
                future[future_action][1] += payoff
            else:
                payoff = self.action_b_payoff
            root[root_action][0] += 1
            root[root_action][1] += payoff
        selected = max(
            root,
            key=lambda action: (root[action][0], _mean(root[action]), -("A", "B").index(action)),
        )
        return {
            "action": selected,
            "root_mean_utilities": {action: _mean(value) for action, value in root.items()},
            "root_visits": {action: value[0] for action, value in root.items()},
            "future_mean_utilities": {action: _mean(value) for action, value in future.items()},
            "future_visits": {action: value[0] for action, value in future.items()},
            "budget": budget,
            "schema_version": TINY_REFERENCE_SCHEMA_VERSION,
        }


def _deterministic_world_index(simulation: int) -> int:
    digest = hashlib.sha256(f"tiny-root-info-v1|{simulation}".encode()).digest()
    return int.from_bytes(digest, "big") % 2


def _mean(value: list[float | int]) -> float:
    return value[1] / value[0] if value[0] else 0.0


def _select(stats: dict[str, list[float | int]], exploration_constant: float) -> str:
    unvisited = [action for action, value in stats.items() if value[0] == 0]
    if unvisited:
        return unvisited[0]
    parent_visits = sum(value[0] for value in stats.values())
    return max(
        stats,
        key=lambda action: (
            _mean(stats[action])
            + exploration_constant * math.sqrt(math.log(max(1, parent_visits)) / stats[action][0]),
            -tuple(stats).index(action),
        ),
    )
