"""Named policy factories, call recording, ReplayFork, snapshots and NativeFork (C0.03).

`Env.set_state` / `tc_env_clone_from` copy deal state, not a search
controller (evidence E003/E004). A controller's decisions depend on its
construction and its whole call history (NumPy and scalar RNGs, the native
environment's sooli settings), so:

- `ReplayFork` constructs the same agent afresh from its named factory and
  replays the seat's recorded legal observations, checking every action. It
  needs no native memory access.
- `native_fork` (NativeFork) constructs cold and then imports the mutable
  state explicitly: the Python RNGs and, through the research library, the
  environment configuration. Slot deal states and slot RNGs are scratch for
  search (search overwrites every slot it uses and never reads a slot RNG; see
  tuppi_env.c `search_core`/`new_match`), which `snapshot` still records as a
  digest.

Diagnostics run on forks only; a live agent is never asked a counterfactual.

Lifecycle labels (IMPLEMENTATION_SPEC.md 1.3) name what a comparison measures:
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .identity import digest

LIFECYCLES = {
    "historical_worker_reuse": "old evaluator order: agents persist across bundles/rotations/arms (continuity only)",
    "independent_cold_bundle": "fresh agents per base bundle, rotation and assignment, matched seat seeds",
    "retained_match_leg": "agents built at leg start and kept through every deal of the leg",
    "cold_reset_per_deal": "fresh agents at every deal (a different, separately named instrument)",
}

FACTORIES: dict = {}


def factory(name: str):
    def register(fn):
        FACTORIES[name] = fn
        return fn
    return register


@factory("best")
def _best(seat: int, worlds: int = 128, seed: int = 0):
    """The live factory itself (`tuppi_ai.best.best_agents`), one seat."""
    from ..best import best_agents

    return best_agents(seats=[seat], worlds=worlds, seed=seed, team_rollout=False)[seat]  # B0: the audited configuration (clone rollouts on every seat)


@factory("clone")
def _clone(seat: int, tie_order: str = "native_id", sooli_seed: int = 0):
    from .clone_policy import CloneGreedyAgent

    return CloneGreedyAgent(seat, tie_order=tie_order, sooli_seed=sooli_seed)


@factory("incumbent")
def _incumbent(seat: int, profile: str = "partner_aware_lead_v2"):
    from tuppi_agents.sooli import SooliFallbackAgent

    from ..incumbent import incumbent_agents

    agent = incumbent_agents(profile)[seat]
    return agent if getattr(agent, "handles_sooli", False) else SooliFallbackAgent(agent)


@factory("first_legal")
def _first_legal(seat: int):
    from tuppi_engine import FirstLegalActionAgent

    return FirstLegalActionAgent()


class RandomLegalAgent:
    """A cheap stateful test policy: uniform legal action from its own RNG."""

    handles_sooli = True

    def __init__(self, seat: int, seed: int = 0):
        from .streams import python_stream

        self.seat = seat
        self.rng = python_stream("agent", "random_legal", seed, seat)
        self.calls = 0

    def choose_action(self, observation):
        self.calls += 1
        legal = observation.legal_actions
        return legal[self.rng.randrange(len(legal))] if len(legal) > 1 else legal[0]


@factory("random_legal")
def _random_legal(seat: int, seed: int = 0):
    return RandomLegalAgent(seat, seed)


@factory("c1")
def _c1(seat: int, beta: float, m_cheap: int, n_expensive: int, run_id: str, advancement: str = "shadow",
        worlds: int = 128, seed: int = 0):
    """A best-factory seat wrapped by the C1 candidate (needs the research build in this process)."""
    from .c1_dispatch import C1Candidate, C1Config
    from .native_api import ResearchLibrary

    base = _best(seat, worlds=worlds, seed=seed)
    return C1Candidate(base, C1Config(beta, m_cheap, n_expensive, run_id, advancement), ResearchLibrary())


class ScriptedAgent:
    """Plays a fixed rule: `rule(observation) -> index into legal_actions`."""

    handles_sooli = True

    def __init__(self, seat: int, rule):
        self.seat, self.rule = seat, rule

    def choose_action(self, observation):
        return observation.legal_actions[self.rule(observation)]


@dataclass(frozen=True)
class AgentSpec:
    """A named, fully specified construction for one seat."""

    factory: str
    seat: int
    params: tuple = ()

    @classmethod
    def of(cls, factory: str, seat: int, **params) -> "AgentSpec":
        if factory not in FACTORIES:
            raise KeyError(f"unknown factory {factory}")
        return cls(factory, seat, tuple(sorted(params.items())))

    def construct(self):
        return FACTORIES[self.factory](seat=self.seat, **dict(self.params))

    @property
    def spec_id(self) -> str:
        return f"{self.factory}:" + digest({"factory": self.factory, "seat": self.seat,
                                            "params": [list(p) for p in self.params]})[:16]


class RecordingAgent:
    """Delegates to one agent and records each call's legal input and output."""

    def __init__(self, spec: AgentSpec, agent=None):
        self.spec = spec
        self.agent = agent if agent is not None else spec.construct()
        self.history: list[dict] = []

    @property
    def handles_sooli(self) -> bool:
        return getattr(self.agent, "handles_sooli", False)

    def choose_action(self, observation):
        from tuppi_engine import action_to_data, observation_to_data

        c0, t0 = time.process_time(), time.perf_counter()
        action = self.agent.choose_action(observation)
        self.history.append({"observation": observation_to_data(observation), "action": action_to_data(action),
                             "wall_ms": 1000 * (time.perf_counter() - t0),
                             "cpu_ms": 1000 * (time.process_time() - c0)})
        return action


class ReplayMismatch(RuntimeError):
    def __init__(self, index: int, expected: dict, got: dict):
        super().__init__(f"replay diverged at call {index}: expected {expected}, got {got}")
        self.index = index


def replay_fork(spec: AgentSpec, history: list[dict], upto: int | None = None) -> RecordingAgent:
    """A fresh agent replayed through `history[:upto]`, every action checked (A06)."""
    from tuppi_engine import action_to_data

    from .observation import observation_from_data

    fork = RecordingAgent(spec)
    for i, call in enumerate(history[:upto]):
        got = action_to_data(fork.choose_action(observation_from_data(call["observation"])))
        if got != call["action"]:
            raise ReplayMismatch(i, call["action"], got)
    return fork


def _unwrap(agent):
    """A C1Candidate's persistent controller is its base SearchAgent."""
    return getattr(agent, "base", agent) if type(agent).__name__ == "C1Candidate" else agent


def _searchers(agent):
    agent = _unwrap(agent)
    seen, out = set(), []
    for name in ("searcher", "show_searcher"):
        sr = getattr(agent, name, None)
        if sr is not None and id(sr) not in seen:
            seen.add(id(sr))
            out.append((name, sr))
    return out


def snapshot(agent, research_lib=None) -> dict:
    """Decision-relevant mutable state of one agent (A06/A07/A10).

    For a SearchAgent: every searcher's scalar and NumPy RNG and, when the
    process runs the research library, its environment configuration and slot
    digest. `last_values` is diagnostic output and excluded. The native
    configuration is None (not inferred) when only B0 libraries are loaded.
    """
    agent = getattr(agent, "agent", agent)
    if type(agent).__name__ == "C1Candidate":
        return {"type": "C1Candidate", "candidate_id": agent.config.candidate_id, "calls": agent.calls,
                "fallbacks": agent.fallbacks, "base": snapshot(agent.base, research_lib)}
    snap: dict = {"type": type(agent).__name__}
    searchers = _searchers(agent)
    if searchers:
        snap["seat"] = agent.seat
        snap["sooli"] = dict(agent.sooli)
        for name, sr in searchers:
            entry = {"worlds": sr.worlds, "dd_left": sr.dd_left, "scalar_rng": sr.rng.value,
                     "numpy_rng": sr.np_rng.bit_generator.state, "env_slots": sr.env.n,
                     "native_config": research_lib.env_config(sr.env) if research_lib is not None else None}
            snap[name] = entry
    elif hasattr(agent, "sooli_rng"):
        snap["sooli_rng"] = agent.sooli_rng.value
    elif isinstance(agent, RandomLegalAgent):
        snap["rng"] = repr(agent.rng.getstate())
        snap["calls"] = agent.calls
    return snap


def snapshot_id(snap: dict) -> str:
    return "snap:" + digest(snap)[:24]


def native_fork(source: RecordingAgent, research_lib) -> RecordingAgent:
    """NativeFork: cold construction plus explicit import of every mutable field (A07)."""
    fork = RecordingAgent(source.spec)
    src, dst = source.agent, fork.agent
    pairs = dict(_searchers(src))
    for name, sr in _searchers(dst):
        other = pairs[name]
        sr.rng.value = other.rng.value
        sr.np_rng.bit_generator.state = other.np_rng.bit_generator.state
        research_lib.import_config(sr.env, research_lib.env_config(other.env))
    if type(src).__name__ == "C1Candidate":
        dst.calls, dst.fallbacks = src.calls, src.fallbacks
    if hasattr(src, "sooli_rng"):
        dst.sooli_rng.value = src.sooli_rng.value
    if isinstance(src, RandomLegalAgent):
        dst.rng.setstate(src.rng.getstate())
        dst.calls = src.calls
    fork.history = list(source.history)
    return fork


@dataclass
class ModeTracker:
    """The deduced sooli-setting mode of one SearchAgent from its call history (K05).

    C = cold (0, 0, 0, 0); O = after an offer (17, 0, 1, 0.3); P = after a
    searched give/play (17, 0, 0, 0.3). A deduction to be validated against the
    research build's actual configuration, not an assumed theorem.
    """

    mode: str = "C"
    transitions: list = field(default_factory=list)

    SETTINGS = {"C": (0, 0, 0, 0.0), "O": (17, 0, 1, 0.3), "P": (17, 0, 0, 0.3)}

    def observe_call(self, observation, n_legal: int, sooli_cfg: dict) -> str:
        from tuppi_engine.state import EnginePhase

        phase = observation.phase
        before = self.mode
        if n_legal <= 1:
            pass  # forced: choose_action returns before touching settings
        elif phase is EnginePhase.SOOLI_OFFER:
            self.mode = "O"
        elif phase in (EnginePhase.SOOLI_GIVE, EnginePhase.SOOLI_PLAY):
            key = "give" if phase is EnginePhase.SOOLI_GIVE else "play"
            if sooli_cfg[key] == "search":
                self.mode = "P"
        elif phase is EnginePhase.SOOLI_RETURN:
            if sooli_cfg["return"] == "search":
                self.mode = "P"
        elif observation.ruleset_id.value == "project_target_v2":
            self.mode = "O" if sooli_cfg["offer_play_heur"] else "P"
        self.transitions.append((before, phase.value, self.mode))
        return self.mode
