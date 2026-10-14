"""Bounded, spawned bot process. Only trusted server observations enter it.

Four reusable native controllers are kept in one process. Each room owns its
per-seat RNG cursor, restored before every decision, so controllers are never
shared logically between rooms and a process restart can repeat a decision.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import threading
import resource
import sys
import time

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


def warm() -> None:
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
