"""C1 branch dispatcher with shadow advancement (C1.03; V06, V09, V10).

`C1Candidate` wraps one live best-factory SearchAgent. At an eligible
decision - ordinary TRICK_PLAY, NOLO, actor void in the led suit, at least two
legal cards - it replaces the W128 argmax by the fixed-beta control-variate
estimate; everywhere else it delegates unchanged. It needs the research build
(explicit-world evaluation) and never runs in a B0 process.

Streams (IMPLEMENTATION_SPEC.md 2.2):

- "shadow" (`C1-shadow-v1`): the cheap and expensive worlds come from
  experiment streams derived from a COPY of the agent's pre-call scalar RNG
  state (SHA-256 over the "cheap"/"expensive" namespace, a required run id,
  the seat and that 64-bit state). The label is actor-local controller state,
  never world or cluster data: a fork reproduces it, and distinct agents or
  calls get distinct streams. The persistent scalar RNG is then advanced
  exactly as the original W128 root loop would advance it, by drawing and
  discarding W root worlds, so on a matched history the post-call controller
  state equals the original's (V09). Shadow draws are sampling cost and are
  counted.
- "natural" (`C1-natural-v1`): the expensive then cheap worlds are drawn from
  the persistent RNG itself, which then differs from W128's. A different
  complete policy; reported separately, never mixed with the shadow variant.

Only project_target_v3 ordinary NOLO discards are eligible; everything else
(including every other ruleset) is delegated unchanged. A failure inside the
C1 branch falls back to the unchanged W128 call and is recorded on an
intention-to-run basis; in shadow mode the persistent state has not been
touched when the fallback runs, so its advancement is exactly the original's.

Reference action a0: the clone's preferred legal discard, one native forward
pass, engine legal-action tie order; its cost is counted. No adaptive
racing, early stopping or deviation margin (C1v1).
"""

from __future__ import annotations

import ctypes as C
import time
from dataclasses import dataclass, field

import numpy as np

from .c1_control_variate import ESTIMATOR_VERSION, PROXY_VERSION, estimate_gaps, proxy_matrix, select

ADVANCEMENT = ("shadow", "natural")


@dataclass(frozen=True)
class C1Config:
    beta: float
    m_cheap: int
    n_expensive: int
    run_id: str
    advancement: str = "shadow"

    def __post_init__(self):
        if self.advancement not in ADVANCEMENT:
            raise ValueError(self.advancement)
        if not self.run_id:
            raise ValueError("run_id is required (it domain-separates experiment streams between runs)")
        if self.n_expensive < 2 or self.m_cheap < (2 if self.beta else 0):
            raise ValueError("batch sizes too small: n >= 2, and M >= 2 whenever beta != 0")

    @property
    def candidate_id(self) -> str:
        return (f"C1-{self.advancement}-v1|beta={self.beta!r}|M={self.m_cheap}|n={self.n_expensive}"
                f"|{ESTIMATOR_VERSION}|{PROXY_VERSION}")


def eligible(observation) -> bool:
    if observation.ruleset_id.value != "project_target_v3":
        return False
    if observation.phase.value != "TRICK_PLAY" or observation.contract is None:
        return False
    if observation.contract.value != "NOLO" or observation.soolaaja is not None:
        return False
    if not observation.current_trick or len(observation.legal_actions) < 2:
        return False
    led = observation.current_trick[0].card.suit
    return all(a.card.suit != led for a in observation.legal_actions)


@dataclass
class C1Decision:
    candidate_id: str
    ids: list
    ref_index: int
    chosen_index: int
    gaps: list
    variance: list
    cost: dict = field(default_factory=dict)


class C1Candidate:
    handles_sooli = True

    def __init__(self, base, config: C1Config, research):
        if not getattr(base, "searcher", None) or base.searcher.mlp is None:
            raise TypeError("C1Candidate wraps a native-loop SearchAgent")
        self.base, self.config, self.research = base, config, research
        self.decisions: list[C1Decision] = []
        self.calls = 0
        self.fallbacks = 0
        self.failures: list[dict] = []

    @property
    def seat(self):
        return self.base.seat

    def choose_action(self, observation):
        self.calls += 1
        if not eligible(observation):
            return self.base.choose_action(observation)
        rng_before = self.base.searcher.rng.value
        try:
            return self._c1(observation)
        except Exception as exc:  # recorded, then the unchanged W128 decision
            if self.config.advancement == "shadow" and self.base.searcher.rng.value != rng_before:
                raise RuntimeError("shadow C1 failed after advancing the persistent RNG") from exc
            self.fallbacks += 1
            self.failures.append({"call": self.calls, "error": f"{type(exc).__name__}: {exc}",
                                  "rng_advanced_before_fallback": self.base.searcher.rng.value != rng_before})
            return self.base.choose_action(observation)

    # ------------------------------------------------------------------ C1 branch
    def _c1(self, observation):
        from .. import native
        from ..bridge import action_id, obs_from_player_observation
        from .clone_policy import clone_scores, preferred
        from .streams import scalar_stream

        cfg, sr, R = self.config, self.base.searcher, self.research
        cost = {}
        c0, t0 = time.process_time(), time.perf_counter()
        tobs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in observation.legal_actions]
        ref = preferred(ids, clone_scores(tobs, sr.mlp, self.base.net.encoder), "engine")
        cost["reference_cpu_s"] = time.process_time() - c0
        self.base.last_values = None  # diagnostics: no W128 action values exist for a C1 decision

        c1 = time.process_time()
        if cfg.advancement == "shadow":
            label = (cfg.run_id, "seat", self.seat, "pre-call-rng", sr.rng.value)  # actor-local state copy
            exp_rng, cheap_rng = scalar_stream("expensive", *label), scalar_stream("cheap", *label)
            expensive = R.sample_worlds(sr.env, tobs, cfg.n_expensive, exp_rng)
            cheap = R.sample_worlds(sr.env, tobs, cfg.m_cheap, cheap_rng) if cfg.m_cheap else []
        else:
            expensive = R.sample_worlds(sr.env, tobs, cfg.n_expensive, sr.rng)
            cheap = R.sample_worlds(sr.env, tobs, cfg.m_cheap, sr.rng) if cfg.m_cheap else []
        cost["sampling_cpu_s"] = time.process_time() - c1

        c2 = time.process_time()
        cont = C.c_uint64(0)
        ev = R.evaluate_worlds(sr.env, sr.mlp, tobs, expensive, ids, sr.dd_left, cont)
        cost["expensive_cpu_s"] = time.process_time() - c2
        if cont.value != 0 or not ev.valid.all():
            raise RuntimeError("ordinary NOLO continuation drew randomness or produced an invalid cell")
        d = ev.per_world - ev.per_world[:, [ref]]

        c3 = time.process_time()
        g_exp = proxy_matrix([[w.hand[s] for s in range(4)] for w in expensive], tobs.seat, ids, ref)
        g_cheap = (proxy_matrix([[w.hand[s] for s in range(4)] for w in cheap], tobs.seat, ids, ref)
                   if cheap else np.zeros((0, len(ids))))
        est = estimate_gaps(g_cheap, d, g_exp, cfg.beta, ref)
        best = select(est.gaps)
        cost["proxy_cpu_s"] = time.process_time() - c3

        if cfg.advancement == "shadow":
            c4 = time.process_time()
            R.sample_worlds(sr.env, tobs, sr.worlds, sr.rng)  # what W128's root loop would have drawn
            cost["shadow_cpu_s"] = time.process_time() - c4
        cost["total_cpu_s"] = time.process_time() - c0
        cost["total_wall_s"] = time.perf_counter() - t0
        cost["work"] = ev.work
        self.decisions.append(C1Decision(cfg.candidate_id, ids, ref, best, est.gaps.tolist(),
                                         est.variance.tolist(), cost))
        return observation.legal_actions[best]
