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
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import threading
import resource
import sys
import time

LEVELS = ("lite", "full")
_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()
_agents = None


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


def hosted_agents(seats) -> dict:
    kind = HostedLiteAgent if level() == "lite" else HostedSearchAgent
    return {seat: kind(seat) for seat in seats}


def warm() -> None:
    if level() == "lite":
        from tuppi_ai.lite import shared_mlp
        shared_mlp()
        return
    if not pool().submit(_warm).result(timeout=120):
        raise RuntimeError("hosted bot did not initialise")


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=True, cancel_futures=True)
        _pool = None


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

    def __init__(self, seat: int) -> None:
        from tuppi_ai.lite import LiteAgent
        self.seat = seat
        self._agent = LiteAgent(seat)

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
        return {"schema": "tuppi.hosted.controller.lite.v1", "rng": self.rng_state}

    def restore(self, record) -> None:
        if (type(record) is not dict or set(record) != {"schema", "rng"}
                or record["schema"] != "tuppi.hosted.controller.lite.v1"
                or type(record["rng"]) is not int or not 0 <= record["rng"] < 2**64):
            raise ValueError("invalid hosted controller checkpoint")
        self.rng_state = record["rng"]
