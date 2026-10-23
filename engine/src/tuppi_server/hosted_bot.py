"""Hosted bots. Only trusted server observations enter them.

TUPPI_HOSTED_BOT_LEVEL selects the bot:

- ``full``: the W1024 search bot in a bounded, spawned process. Four reusable
  native controllers are kept in that process. Each room owns its per-seat RNG
  cursor, restored before every decision, so controllers are never shared
  logically between rooms and a process restart can repeat a decision.
- ``lite``: the VRPO3 policy without search (tuppi_ai.lite), in the server
  process and without PyTorch. Each room's agents own their sooli cursor;
  the network is shared and immutable. About 1/11,000 of the full bot's CPU
  (audit_deliverables/tuppi_lite_bot_20261014).

TUPPI_HOSTED_LITE_OPTIONS (lite only) selects the lite bot's options:
``off`` (the default); ``c1``, the face-up safety net with play inference
(tuppi_ai.lite.C1, the research candidate); ``c1h``, c1 reading the moves of
seats played by people more loosely (tuppi_ai.lite.C1H; the runner names
those seats before each decision); or ``d1``, c1 plus sooli at 2 of 8
(audit_deliverables/tuppi_faceup_improvements_20261020). c1, c1h and d1 add
two cursors to each agent's checkpoint (schema lite.v2); off keeps the v1
checkpoint. Every setting restores both schemas.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import lru_cache
import multiprocessing
import os
import threading
import resource
import sys
import time

LEVELS = ("lite", "full")
LITE_OPTIONS = ("off", "c1", "c1h", "d1")
_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()
_agents = None
HEIDI_PROFILE = "tuppi_ai_heidi10_pib8_v1"
_heidi_pool: ProcessPoolExecutor | None = None
_heidi_pool_lock = threading.Lock()
_heidi_controller = None


def heidi_enabled() -> bool:
    value = os.environ.get("TUPPI_HOSTED_HEIDI10", "0")
    if value not in ("0", "1"):
        raise ValueError("TUPPI_HOSTED_HEIDI10 must be 0 or 1")
    return value == "1" and level() == "lite"


@lru_cache(maxsize=1)
def heidi_identity() -> str:
    from tuppi_ai.compact import model_identity
    return model_identity()["sha256"]


def _initialise_heidi() -> None:
    global _heidi_controller
    from tuppi_ai.compact import CompactController
    _heidi_controller = CompactController()


def heidi_pool() -> ProcessPoolExecutor:
    global _heidi_pool
    with _heidi_pool_lock:
        if _heidi_pool is None:
            _heidi_pool = ProcessPoolExecutor(max_workers=1,
                mp_context=multiprocessing.get_context("spawn"), initializer=_initialise_heidi)
        return _heidi_pool


def _stop_heidi_pool(expected=None) -> None:
    """Stop only our compact worker, including a search that exceeded its deadline."""
    global _heidi_pool
    with _heidi_pool_lock:
        current = _heidi_pool
        if current is None or (expected is not None and current is not expected):
            return
        _heidi_pool = None
        if hasattr(current, "terminate_workers"):
            current.terminate_workers()
        else:  # Python <3.14 development hosts; these are our own child processes.
            processes = list((current._processes or {}).values())
            for process in processes:
                process.terminate()
            current.shutdown(wait=False, cancel_futures=True)
            for process in processes:
                process.join(timeout=2)


def _warm_heidi() -> str:
    if 'torch' in sys.modules:
        raise RuntimeError('compact Heidi worker must not import PyTorch')
    return _heidi_controller.model_sha256


def _heidi_decision(observation, context, people):
    started, cpu = time.perf_counter(), time.process_time()
    action, cursor, _ = _heidi_controller.choose(observation, context, people)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return action, cursor, {"decision_seconds": time.perf_counter() - started,
        "decision_cpu_seconds": time.process_time() - cpu,
        "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024}


def _initialise() -> None:
    global _agents
    import torch
    torch.set_num_threads(1)
    from tuppi_ai.best import best_agents
    _agents = best_agents(worlds=1024)


def _decision(observation, rng_state):
    started = time.perf_counter()
    agent = _agents[observation.observing_seat]
    agent.searcher.rng.value = (
        (2 * observation.observing_seat) * 2654435761 + 1
        if rng_state is None else rng_state
    )
    action = agent.choose_action(observation)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return action, agent.searcher.rng.value, {"decision_seconds": time.perf_counter()-started,
        "process_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024}


def pool() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1,
                mp_context=multiprocessing.get_context("spawn"), initializer=_initialise)
        return _pool


def _warm() -> bool:
    return _agents is not None


def level() -> str:
    value = os.environ.get("TUPPI_HOSTED_BOT_LEVEL", "full")
    if value not in LEVELS:
        raise ValueError("TUPPI_HOSTED_BOT_LEVEL must be lite or full")
    return value


def lite_options() -> str:
    value = os.environ.get("TUPPI_HOSTED_LITE_OPTIONS", "off")
    if value not in LITE_OPTIONS:
        raise ValueError("TUPPI_HOSTED_LITE_OPTIONS must be off, c1, c1h or d1")
    return value


def hosted_agents(seats, *, options: str | None = None) -> dict:
    if options is not None:
        if level() != "lite" or options not in LITE_OPTIONS:
            raise ValueError("unsupported hosted bot option")
        return {seat: HostedLiteAgent(seat, options=options) for seat in seats}
    kind = HostedLiteAgent if level() == "lite" else HostedSearchAgent
    return {seat: kind(seat) for seat in seats}


def warm() -> None:
    if level() == "lite":
        from tuppi_ai.lite import shared_mlp
        shared_mlp()
        if heidi_enabled() and heidi_pool().submit(_warm_heidi).result(timeout=90) != heidi_identity():
            raise RuntimeError("compact Heidi model identity mismatch")
        return
    if not pool().submit(_warm).result(timeout=120):
        raise RuntimeError("hosted bot did not initialise")


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=True, cancel_futures=True)
        _pool = None
    _stop_heidi_pool()


class HostedHeidiAgent:
    """PIB8 is part of the saved profile; a missing worker is never a lite fallback."""
    handles_sooli = True

    def __init__(self, seat: int) -> None:
        if level() != "lite" or type(seat) is not int or seat not in range(4):
            raise ValueError("hosted Heidi 1.0 is unavailable")
        self.seat = seat
        rng = (2 * seat) * 2654435761 + 1
        self.context = [rng & 0xffffffff, rng >> 32, 0]
        self.people = frozenset()

    def set_human_seats(self, seats) -> None:
        seats = frozenset(seats)
        if any(type(s) is not int or s not in range(4) for s in seats):
            raise ValueError("invalid human seats")
        self.people = seats

    def choose_action(self, observation):
        if observation.observing_seat != self.seat:
            raise ValueError("bot observation seat mismatch")
        worker = heidi_pool()
        try:
            action, context, stats = worker.submit(_heidi_decision,
                observation, self.context, self.people).result(timeout=90)
        except (TimeoutError, BrokenProcessPool):
            _stop_heidi_pool(worker)
            raise
        if action not in observation.legal_actions:
            raise RuntimeError("hosted Heidi returned an illegal action")
        self.context, self.last_stats = context, stats
        return action

    def checkpoint(self):
        return {"schema": "tuppi.hosted.controller.heidi10.v1", "worlds": 1024,
                "inference": 8, "models": heidi_identity(), "context": list(self.context)}

    def restore(self, record) -> None:
        if (type(record) is not dict or set(record) != {"schema", "worlds", "inference", "models", "context"}
                or record["schema"] != "tuppi.hosted.controller.heidi10.v1"
                or type(record["worlds"]) is not int or record["worlds"] != 1024
                or type(record["inference"]) is not int or record["inference"] != 8
                or record["models"] != heidi_identity() or type(record["context"]) is not list
                or len(record["context"]) != 3
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in record["context"])
                or record["context"][2] > 2):
            raise ValueError("invalid hosted Heidi checkpoint")
        self.context = list(record["context"])


class HostedSearchAgent:
    handles_sooli = True

    def __init__(self, seat: int) -> None:
        self.seat = seat
        self.rng_state: int | None = None

    def choose_action(self, observation):
        if observation.observing_seat != self.seat:
            raise ValueError("bot observation seat mismatch")
        action, cursor, self.last_stats = pool().submit(_decision, observation, self.rng_state).result(timeout=90)
        if action not in observation.legal_actions:
            raise RuntimeError("hosted bot returned an illegal action")
        self.rng_state = cursor
        return action

    def checkpoint(self):
        return {"schema": "tuppi.hosted.controller.v1", "worlds": 1024, "rng": self.rng_state}

    def restore(self, record) -> None:
        if (type(record) is not dict or set(record) != {"schema", "worlds", "rng"}
                or record["schema"] != "tuppi.hosted.controller.v1" or record["worlds"] != 1024
                or (record["rng"] is not None and (type(record["rng"]) is not int
                    or not 0 <= record["rng"] < 2**64))):
            raise ValueError("invalid hosted controller checkpoint")
        self.rng_state = record["rng"]


class HostedLiteAgent:
    handles_sooli = True

    def __init__(self, seat: int, *, options: str | None = None) -> None:
        from tuppi_ai.lite import C1, C1H, D1, LiteAgent
        self.seat = seat
        self.options = lite_options() if options is None else options
        self._agent = LiteAgent(seat, options={"off": None, "c1": C1, "c1h": C1H, "d1": D1}[self.options])

    def set_human_seats(self, seats) -> None:
        """The seats people play now (the runner calls this before each decision; c1h reads their moves loosely)."""
        self._agent.set_human_seats(seats)

    @property
    def rng_state(self) -> int:
        return self._agent.rng.value

    @rng_state.setter
    def rng_state(self, value: int) -> None:
        self._agent.rng.value = value

    def choose_action(self, observation):
        if observation.observing_seat != self.seat:
            raise ValueError("bot observation seat mismatch")
        started = time.perf_counter()
        action = self._agent.choose_action(observation)
        if action not in observation.legal_actions:
            raise RuntimeError("hosted bot returned an illegal action")
        self.last_stats = {"decision_seconds": time.perf_counter() - started}
        return action

    def checkpoint(self):
        if self.options == "off":
            return {"schema": "tuppi.hosted.controller.lite.v1", "rng": self.rng_state}
        return {"schema": "tuppi.hosted.controller.lite.v2", "options": self.options, "rng": self.rng_state,
                "gate_rng": self._agent.gate_rng.value, "belief_rng": self._agent.belief_rng.value}

    def restore(self, record) -> None:
        """A v1 record (no net cursors) leaves them at their start values."""
        cursor = lambda v: type(v) is int and 0 <= v < 2**64
        v1 = type(record) is dict and record.get("schema") == "tuppi.hosted.controller.lite.v1"
        v2 = type(record) is dict and record.get("schema") == "tuppi.hosted.controller.lite.v2"
        if not ((v1 and set(record) == {"schema", "rng"} and cursor(record["rng"]))
                or (v2 and set(record) == {"schema", "options", "rng", "gate_rng", "belief_rng"}
                    and record["options"] in LITE_OPTIONS and all(cursor(record[k]) for k in ("rng", "gate_rng",
                                                                                                "belief_rng")))):
            raise ValueError("invalid hosted controller checkpoint")
        self.rng_state = record["rng"]
        if v2:
            self._agent.gate_rng.value, self._agent.belief_rng.value = record["gate_rng"], record["belief_rng"]
