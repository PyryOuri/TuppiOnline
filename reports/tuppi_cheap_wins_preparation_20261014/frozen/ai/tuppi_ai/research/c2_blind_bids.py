"""C2: blind v3 bidding conditioned on its consequence, clone-predecessor model (section 4).

Model (a MODEL experiment, not the literal search-predecessor process): the
earlier seats at the focal seat's reveal position k are deterministic
encoder-2 clones (the rollout network, ascending-id ties, as the native
rollouts decide). The focal seat's commitment matters only in the event E that
every earlier seat bid NOLO, so under this fixed simultaneous model

    Q(a) - Q(b) = E[1(E) (U_a - U_b)]        (unconditional, per commitment)

and the reached-call (conditional) gap divides by P(E); the two have
different units and are always reported separately.

For each of W prior joint layouts (the native locked-bid sampler with the
focal hand fixed; the other 39 cards uniform):
1. each predecessor gets its OWN masked precommit observation (own original
   hand, public context, `bids_locked` = its reveal position; no bid content,
   no focal hand) and bids; stop at the first RAMI;
2. an unreached layout contributes an exactly zero contrast and stays in the
   denominator; batches are never resampled for more hits;
3. reached layouts keep the predecessors' actual chosen NOLO cards (RC) or the
   sampler's uniform eligible cards (F, R);
4. every focal action is evaluated on the same worlds by the explicit-world
   evaluator (the frozen continuation); the predecessors' bids do not change
   with the focal action.

Ablations: F = current forced-prefix reconstruction, all layouts weighted 1;
R = F's values weighted by 1(E); RC = 1(E) weighting AND the chosen cards.
"""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass, field

import numpy as np

VARIANTS = ("F", "R", "RC")


@dataclass
class C2Batch:
    ids: list
    ref_index: int
    focal_position: int
    event: np.ndarray                      # [W] bool: every predecessor passed
    schedule: list                         # [W] list of (seat, bid id) actually queried, in order
    y: dict = field(default_factory=dict)  # variant -> [W, K] values (observer's sign)
    gaps: dict = field(default_factory=dict)
    conditional_gaps: dict = field(default_factory=dict)
    work: dict = field(default_factory=dict)

    @property
    def hits(self) -> int:
        return int(self.event.sum())

    @property
    def reach_frequency(self) -> float:
        return float(self.event.mean())

    def summary(self) -> dict:
        return {"W": len(self.event), "hits": self.hits, "reach_frequency": self.reach_frequency,
                "unconditional_gap_per_commitment": {k: v.tolist() for k, v in self.gaps.items()},
                "conditional_gap_when_reached": {k: (None if v is None else v.tolist())
                                                 for k, v in self.conditional_gaps.items()},
                "units": {"unconditional": "equity per blind commitment (includes the reach factor)",
                          "conditional": "equity per reached call; NOT comparable to the unconditional unit"}}


class ClonePredecessor:
    """The deterministic rollout clone as a bidder, native forward, ascending-id ties."""

    def __init__(self, mlp, encoder: int, rule=None):
        self.mlp, self.encoder, self.rule = mlp, encoder, rule

    def bid(self, obs) -> int:
        from .. import native
        from .clone_policy import clone_scores, preferred

        ids = native.legal_obs(obs)
        if self.rule is not None:  # exact test policies: "always NOLO" / "always RAMI"
            return self.rule(ids)
        return ids[preferred(ids, clone_scores(obs, self.mlp, self.encoder), "native_id")]


def always(contract: int):
    return lambda ids: next(i for i in ids if (i - 52) // 52 == contract)


def predecessor_seats(dealer: int, k: int) -> list[int]:
    return [(dealer + 1 + i) % 4 for i in range(k)]


def precommit_observation(world, seat: int, position: int):
    """A predecessor's own masked precommit observation from a joint layout (locked showing)."""
    from .. import native

    d = native.TcDeal()
    C.pointer(d)[0] = world
    d.n_shows, d.cur, d.phase = position, seat, native.PH_SHOW
    for i in range(4):
        d.show_seat[i] = d.show_card[i] = d.show_contract[i] = d.show_verbal[i] = 0
    return native.observe(d, seat)


def with_chosen_shows(world, shows) -> object:
    """RC reconstruction: the world with the predecessors' actual chosen NOLO cards."""
    from .. import native

    d = native.TcDeal()
    C.pointer(d)[0] = world
    for i, (seat, bid) in enumerate(shows):
        card = bid - 52
        d.show_seat[i], d.show_card[i], d.show_contract[i] = seat, card, native.NOLO
        d.show_verbal[i] = native.lib.tc_verbal_required(card, native.NOLO)
    return d


def evaluate(research, env, mlp, focal_obs, ids, worlds, *, predecessor: ClonePredecessor, dd_left: int = 6,
             cont_seed: int = 0, ref_index: int = 0, variants=VARIANTS) -> C2Batch:
    """F/R/RC unconditional and conditional gaps on one fixed batch of joint layouts."""
    k = focal_obs.n_shows
    if focal_obs.phase != 0 or focal_obs.ruleset != 3:
        raise ValueError("C2v1 is defined for a v3 locked-bid focal decision")
    seats = predecessor_seats(focal_obs.dealer, k)
    event = np.ones(len(worlds), dtype=bool)
    schedule, chosen = [], []
    for w in worlds:
        calls = []
        for pos, seat in enumerate(seats):
            bid = predecessor.bid(precommit_observation(w, seat, pos))
            calls.append((seat, bid))
            if (bid - 52) // 52 == 1:  # RAMI ends showing: later seats (and the focal seat) are never asked
                break
        reached = all((b - 52) // 52 == 0 for _s, b in calls) and len(calls) == len(seats)
        event[len(schedule)] = reached
        schedule.append(calls)
        chosen.append(calls if reached else None)
    batch = C2Batch(list(ids), ref_index, k, event, schedule)
    ev_f = research.evaluate_worlds(env, mlp, focal_obs, worlds, ids, dd_left, C.c_uint64(cont_seed))
    d_f = ev_f.per_world - ev_f.per_world[:, [ref_index]]
    batch.y["F"] = ev_f.per_world
    batch.work["F"] = ev_f.work
    W = len(worlds)
    if "F" in variants:
        batch.gaps["F"] = d_f.mean(axis=0)
        batch.conditional_gaps["F"] = d_f.mean(axis=0)  # F treats every layout as reached
    if "R" in variants:
        batch.gaps["R"] = (d_f * event[:, None]).sum(axis=0) / W
        batch.conditional_gaps["R"] = d_f[event].mean(axis=0) if event.any() else None
    if "RC" in variants:
        rc_worlds = [with_chosen_shows(w, c) if c is not None else w for w, c in zip(worlds, chosen)]
        ev_rc = research.evaluate_worlds(env, mlp, focal_obs, rc_worlds, ids, dd_left, C.c_uint64(cont_seed))
        d_rc = ev_rc.per_world - ev_rc.per_world[:, [ref_index]]
        batch.y["RC"] = ev_rc.per_world
        batch.work["RC"] = ev_rc.work
        batch.gaps["RC"] = (d_rc * event[:, None]).sum(axis=0) / W
        batch.conditional_gaps["RC"] = d_rc[event].mean(axis=0) if event.any() else None
    return batch


# ---------------------------------------------------------------- pure toys (B05)


def joint_vs_product_toy() -> dict:
    """Exact toy: two predecessors each pass iff they hold no ace, from one shared 6-card deck.

    Dealing two cards each from {A, A, x, x, x, x}, the joint probability that
    both pass differs from the product of the marginals, so a product-marginal
    (independent) model of predecessor passes is wrong; joint layouts are not.
    """
    from fractions import Fraction
    from itertools import permutations

    deck = ("A", "A", "x", "x", "x", "x")
    deals = set(permutations(range(6)))
    both = p1 = p2 = 0
    for perm in deals:
        h1 = {deck[perm[0]], deck[perm[1]]}
        h2 = {deck[perm[2]], deck[perm[3]]}
        pass1, pass2 = "A" not in h1, "A" not in h2
        both += pass1 and pass2
        p1 += pass1
        p2 += pass2
    n = len(deals)
    joint = Fraction(both, n)
    product = Fraction(p1, n) * Fraction(p2, n)
    return {"joint": joint, "product_of_marginals": product, "differ": joint != product}


# ---------------------------------------------------------------- C2.02: searching predecessors


class SearchPredecessor:
    """A searching predecessor modelled by side-effect-isolated forks of its live controller (C2.02).

    For each joint layout the predecessor's bid is the choice that a NativeFork of
    its LIVE agent makes on the predecessor's own engine observation (built by
    replaying placeholder earlier bids; byte-identical to the native precommit
    observation, test B02). The live agent is never called. Results are cached
    by (observation bytes, live controller snapshot id, legal order, config id)
    together with the fork's post-call snapshot, so a cache hit reproduces the
    call's state advancement exactly. Hypothetical hands use ascending card
    order (the engine tie order then follows it) - a declared model choice.

    This models the reached-call DECISION of a searching predecessor. It is not
    the literal process: there, only reached seats are ever called and each
    call advances that seat's controller (its later decisions in the deal
    change). `schedule` records every modelled query; the live process's
    reached-only schedule is untouched by construction.
    """

    def __init__(self, live, research, config_id: str, dealer: int, score: tuple[int, int]):
        self.live, self.research, self.config_id = live, research, config_id
        self.dealer, self.score = dealer, tuple(score)
        self.cache: dict = {}
        self.queries = 0
        self.searches = 0

    def _engine_observation(self, world, seat: int, position: int):
        from tuppi_engine import apply_match_action, match_observation_for

        from .fixtures import card, make_truth, nolo_first, replay

        hands = tuple(tuple(card(c) for c in range(52) if world.hand[s] >> c & 1) for s in range(4))
        state = replay(make_truth("c2-search", hands, [], dealer=self.dealer, score=self.score), 0)
        for _ in range(position):
            o = match_observation_for(state, state.current_actor)
            state = apply_match_action(state, o.legal_actions[nolo_first(o)])
        obs = match_observation_for(state, seat)
        if obs.bids_locked != position or state.current_actor != seat:
            raise RuntimeError("precommit reconstruction failed")
        return obs

    def bid_for(self, world, seat: int, position: int) -> int:
        from ..bridge import action_id, obs_from_player_observation
        from .lifecycle import native_fork, snapshot, snapshot_id

        self.queries += 1
        obs = self._engine_observation(world, seat, position)
        live_snap = snapshot(self.live.agent, self.research)
        key = (bytes(obs_from_player_observation(obs)), snapshot_id(live_snap),
               tuple(action_id(a) for a in obs.legal_actions), self.config_id)
        hit = self.cache.get(key)
        if hit is None:
            fork = native_fork(self.live, self.research)
            bid = action_id(fork.choose_action(obs))
            self.searches += 1
            hit = self.cache[key] = {"bid": bid, "post_call_snapshot": snapshot(fork.agent, self.research)}
        return hit["bid"]


def evaluate_with_search_predecessors(research, env, mlp, focal_obs, ids, worlds, predecessors: dict, **kw):
    """`evaluate` with each earlier seat's bid from its own SearchPredecessor (seat -> SearchPredecessor)."""

    k = focal_obs.n_shows
    seats = predecessor_seats(focal_obs.dealer, k)
    event = np.ones(len(worlds), dtype=bool)
    schedule, chosen = [], []
    for wi, w in enumerate(worlds):
        calls = []
        for pos, seat in enumerate(seats):
            bid = predecessors[seat].bid_for(w, seat, pos)
            calls.append((seat, bid))
            if (bid - 52) // 52 == 1:
                break
        reached = len(calls) == len(seats) and all((b - 52) // 52 == 0 for _s, b in calls)
        event[wi] = reached
        schedule.append(calls)
        chosen.append(calls if reached else None)
    batch = C2Batch(list(ids), kw.get("ref_index", 0), k, event, schedule)
    ev = research.evaluate_worlds(env, mlp, focal_obs, worlds, ids, kw.get("dd_left", 6), C.c_uint64(kw.get("cont_seed", 0)))
    d_f = ev.per_world - ev.per_world[:, [batch.ref_index]]
    W = len(worlds)
    batch.y["F"] = ev.per_world
    batch.gaps["F"] = d_f.mean(axis=0)
    batch.gaps["R"] = (d_f * event[:, None]).sum(axis=0) / W
    batch.conditional_gaps["R"] = d_f[event].mean(axis=0) if event.any() else None
    rc_worlds = [with_chosen_shows(w, c) if c is not None else w for w, c in zip(worlds, chosen)]
    ev_rc = research.evaluate_worlds(env, mlp, focal_obs, rc_worlds, ids, kw.get("dd_left", 6), C.c_uint64(kw.get("cont_seed", 0)))
    d_rc = ev_rc.per_world - ev_rc.per_world[:, [batch.ref_index]]
    batch.y["RC"] = ev_rc.per_world
    batch.gaps["RC"] = (d_rc * event[:, None]).sum(axis=0) / W
    batch.conditional_gaps["RC"] = d_rc[event].mean(axis=0) if event.any() else None
    batch.work = {"F": ev.work, "RC": ev_rc.work, "predecessor_queries": sum(p.queries for p in predecessors.values()),
                  "predecessor_searches": sum(p.searches for p in predecessors.values())}
    return batch
