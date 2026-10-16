"""C5: an actual-root, information-consistent three-card continuation option (section 8).

Eligibility (v1): an ordinary trick about to be LED by the real actor, ten
tricks complete, every seat holding exactly three cards, at least two legal
leads. The option chooses the lead now and one card at each later root
information set; the last card is forced.

Model: the complete hard-feasible support under the native constraint law,
counted before it is enumerated (cap 100 worlds) and accepted only if the
strict engine constraint model (tuppi_exact show-tier exclusions) gives the
same set; otherwise CONSTRAINT_MODEL_MISMATCH and fallback. The other three
seats (partner included) are the deterministic native clone, each from its
own projected observation, ascending-id ties. Uniform prior mass over the
support unless weights are given; deterministic others give 0/1 likelihoods.
Utility: the frozen float32 equity change, root's sign.

Q(a) = sum over root information groups o after a of mass(o) * max_b E[U | o, b]:
ONE b per group (never one per hidden world). The chosen lead's key -> action
map is the stored option; an unexpected key, a support/model failure, a node
cap or a deadline discards it and falls back, with the reason recorded.
"""

from __future__ import annotations

import ctypes as C
import time
from dataclasses import dataclass, field
from itertools import combinations

MODEL_ID = "c5.three_card_option.fixed_native_clone_others.uniform_complete_support.v1"
SUPPORT_CAP = 100
NODE_CAP = 100_000


class KeyCollision(RuntimeError):
    """Two different root observations were given one information key."""


class NodeCapExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------- the pure group optimiser


def optimise_groups(histories: list) -> tuple[float, dict]:
    """histories: (key, mass, {b: utility}) per surviving history of one first action.

    For every key, choose ONE b maximising the mass-weighted mean utility over
    the key's histories (declared tie order: smallest b). Returns (value, plan);
    `value` is sum_keys mass(key) * max_b E[U | key, b]. Histories whose legal
    sets differ under one key are a key collision.
    """
    groups: dict = {}
    for key, mass, util in histories:
        groups.setdefault(key, []).append((mass, util))
    value, plan = 0.0, {}
    for key, members in groups.items():
        actions = set(members[0][1])
        if any(set(u) != actions for _m, u in members):
            raise KeyCollision(f"histories under key {key!r} have different legal actions")
        total = sum(m for m, _u in members)
        best, best_v = None, None
        for b in sorted(actions):
            v = sum(m * u[b] for m, u in members) / total
            if best_v is None or v > best_v:
                best, best_v = b, v
        plan[key] = best
        value += total * best_v
    return value, plan


# ---------------------------------------------------------------- support


@dataclass
class Support:
    status: str
    native_count: int
    strict_count: int | None = None
    worlds: list = field(default_factory=list)   # four hand masks each (evaluator-only)
    cap: int = SUPPORT_CAP


def eligible(obs) -> bool:
    if obs.phase.value != "TRICK_PLAY" or obs.soolaaja is not None or obs.contract is None:
        return False
    if obs.current_trick or len(obs.completed_tricks) != 10 or len(obs.legal_actions) < 2:
        return False
    return len(obs.own_hand) == 3 and obs.current_actor == obs.observing_seat


def _constraints(tobs):
    me = tobs.seat
    played_by, voids, played = [0] * 4, [set() for _ in range(4)], 0
    n = tobs.n_played
    for t in range(0, n, 4):
        led = tobs.play_card[t] // 13
        for i in range(t, min(n, t + 4)):
            c, s = tobs.play_card[i], tobs.play_seat[i]
            played_by[s] += 1
            played |= 1 << c
            if c // 13 != led:
                voids[s].add(led)
    known = {s: 0 for s in range(4)}
    for i in range(tobs.n_shows):
        c, s = tobs.show_card[i], tobs.show_seat[i]
        if s != me and not played >> c & 1:
            known[s] |= 1 << c
    free = ((1 << 52) - 1) & ~tobs.hand & ~played & ~(known[0] | known[1] | known[2] | known[3])
    others = [s for s in range(4) if s != me]
    cap = {s: 13 - played_by[s] - bin(known[s]).count("1") for s in others}
    return others, [c for c in range(52) if free >> c & 1], cap, voids, known


def _assignments(tobs, exclusions=None):
    others, free, cap, voids, known = _constraints(tobs)
    a, b, c = others
    for first in combinations(free, cap[a]):
        rest = [x for x in free if x not in first]
        for second in combinations(rest, cap[b]):
            third = tuple(x for x in rest if x not in second)
            hand = {a: first, b: second, c: third}
            if any(x // 13 in voids[s] for s in others for x in hand[s]):
                continue
            if exclusions and any(x in exclusions.get(s, ()) for s in others for x in hand[s]):
                continue
            masks = [0, 0, 0, 0]
            masks[tobs.seat] = tobs.hand
            for s in others:
                masks[s] = known[s] | sum(1 << x for x in hand[s])
            yield masks


def strict_exclusions(obs) -> dict:
    """Per-seat card indices excluded by the engine's hard show-tier model (tuppi_exact, E027)."""
    from tuppi_exact.constraints import derive_show_exclusions
    from tuppi_rules.cards import card_to_index

    return {s: {card_to_index(c) for c in ex} for s, ex in enumerate(derive_show_exclusions(obs)) if ex}


def complete_support(obs, cap: int = SUPPORT_CAP, exclusions=None) -> Support:
    """Count first; enumerate only a complete support within the cap; require strict/native agreement."""
    from ..bridge import obs_from_player_observation

    tobs = obs_from_player_observation(obs)
    n = sum(1 for _ in _assignments(tobs))           # counting pass, nothing stored
    if n == 0:
        return Support("EMPTY", 0)
    if n > cap:
        return Support("TOO_LARGE", n)
    worlds = list(_assignments(tobs))
    ex = strict_exclusions(obs) if exclusions is None else exclusions
    strict = [w for w in _assignments(tobs, ex)] if ex else worlds
    if len(strict) != len(worlds):
        return Support("CONSTRAINT_MODEL_MISMATCH", n, len(strict))
    return Support("EXACT_COMPLETE", n, len(strict), worlds, cap)


# ---------------------------------------------------------------- native model


def root_key(tobs) -> tuple:
    """The root's complete information inside one deal: own cards and the whole public play order.

    The deal's constant public context (shows, contract, score, dealer, ruleset,
    sooli decisions) is checked separately as the option's scope.
    """
    n = tobs.n_played
    return (tobs.seat, tobs.hand, tuple(tobs.play_card[:n]), tuple(tobs.play_seat[:n]))


def scope_of(tobs) -> tuple:
    return (tobs.seat, tobs.dealer, tobs.contract, tobs.declarer, tobs.ruleset, tuple(tobs.score),
            tobs.n_shows, tuple(tobs.show_seat), tuple(tobs.show_card), tuple(tobs.show_contract),
            tobs.n_decisions, tuple(tobs.decision_seat), tuple(tobs.decision_accept))


class NativeModel:
    """Deterministic clone others + root forced moves over native deals, with a node budget."""

    def __init__(self, mlp, encoder: int, equity, node_cap: int = NODE_CAP, deadline_s: float | None = None):
        self.mlp, self.encoder, self.equity = mlp, encoder, equity
        self.node_cap, self.deadline_s = node_cap, deadline_s
        self.nodes = 0
        self.t0 = time.perf_counter()

    def _tick(self):
        self.nodes += 1
        if self.nodes > self.node_cap:
            raise NodeCapExceeded(f"node cap {self.node_cap}")
        if self.deadline_s is not None and time.perf_counter() - self.t0 > self.deadline_s:
            raise NodeCapExceeded("deadline")

    def world(self, tobs, masks):
        from .. import native

        d = native.TcDeal()
        C.pointer(d)[0] = native.sample_world(tobs, C.c_uint64(1))  # public fields from the observation
        for s in range(4):
            d.hand[s] = masks[s]
        return d

    def copy(self, d):
        from .. import native

        c = native.TcDeal()
        C.pointer(c)[0] = d
        return c

    def apply(self, d, a):
        from .. import native

        self._tick()
        if native.lib.tc_apply(C.byref(d), a) != 0:
            raise RuntimeError("illegal action in the option model")

    def advance_others(self, d, root: int):
        """Clone moves for every other seat (each from its own observation) until the root acts or the deal ends."""
        from .. import native
        from .clone_policy import clone_scores, preferred

        while d.phase != native.PH_DONE and d.cur != root:
            ids = native.legal(d)
            o = native.observe(d, d.cur)
            self.apply(d, ids[preferred(ids, clone_scores(o, self.mlp, self.encoder), "native_id")])
        return d

    def finish(self, d, root: int):
        """Plays the rest: others by clone, the root only where forced (one legal card)."""
        from .. import native

        while d.phase != native.PH_DONE:
            self.advance_others(d, root)
            if d.phase == native.PH_DONE:
                break
            ids = native.legal(d)
            if len(ids) != 1:
                raise RuntimeError("a root decision beyond the option horizon")
            self.apply(d, ids[0])
        return d

    def utility(self, d, root: int) -> float:
        from .c3_utility_stop import deal_utility

        v = deal_utility((d.score[0], d.score[1]), d.dealer, d.contract, None if d.contract == 0 else d.declarer,
                         d.team_tricks[0], self.equity)
        return v if root % 2 == 0 else -v


@dataclass
class OptionResult:
    status: str
    first_actions: list
    q: dict
    chosen: int | None
    plan: dict
    scope: tuple | None
    nodes: int
    support: int
    wall_s: float
    groups: dict = field(default_factory=dict)
    model_id: str = MODEL_ID


def solve_option(tobs, worlds, model: NativeModel, first_actions: list, weights=None, key_fn=root_key) -> OptionResult:
    """Q(a) for every legal lead and the chosen lead's contingent plan, on a complete support."""
    from .. import native

    root = tobs.seat
    mass = weights or [1.0 / len(worlds)] * len(worlds)
    t0 = time.perf_counter()
    q, plans, groups = {}, {}, {}
    for a in first_actions:
        terminal, histories, raw_obs, max_later = 0.0, [], {}, 0
        for m, masks in zip(mass, worlds):
            d = model.world(tobs, masks)
            model.apply(d, a)
            model.advance_others(d, root)
            if d.phase == native.PH_DONE:
                terminal += m * model.utility(d, root)
                continue
            o = native.observe(d, root)
            key = key_fn(o)
            full = bytes(o)
            if raw_obs.setdefault(key, full) != full:
                raise KeyCollision(f"key {key!r} merges different root observations")
            util = {}
            later = native.legal(d)
            max_later = max(max_later, len(later))
            for b in later:
                e = model.copy(d)
                model.apply(e, b)
                model.finish(e, root)
                util[b] = model.utility(e, root)
            histories.append((key, m, util))
        value, plan = optimise_groups(histories)
        q[a] = terminal + value
        plans[a] = plan
        groups[a] = {"groups": len(plan), "histories": len(histories), "max_later_actions": max_later}
    chosen = None
    for a in first_actions:  # declared root tie order: the given (engine legal) order
        if chosen is None or q[a] > q[chosen]:
            chosen = a
    return OptionResult("EXACT_OPTION", list(first_actions), q, chosen, plans[chosen], scope_of(tobs), model.nodes,
                        len(worlds), time.perf_counter() - t0, groups)


def root_clairvoyant_value(tobs, worlds, model: NativeModel, first_actions: list, weights=None) -> float:
    """Upper bound: the root alone sees the world (other policies unchanged) and picks (a, b) per world."""
    from .. import native

    root = tobs.seat
    mass = weights or [1.0 / len(worlds)] * len(worlds)
    total = 0.0
    for m, masks in zip(mass, worlds):
        best = None
        for a in first_actions:
            d = model.world(tobs, masks)
            model.apply(d, a)
            model.advance_others(d, root)
            if d.phase == native.PH_DONE:
                v = model.utility(d, root)
            else:
                v = max(model.utility(model.finish(_after(model, d, b), root), root) for b in native.legal(d))
            best = v if best is None else max(best, v)
        total += m * best
    return total


def _after(model, d, b):
    e = model.copy(d)
    model.apply(e, b)
    return e


def policy_value(tobs, worlds, model: NativeModel, first, later, weights=None) -> float:
    """Value of an arbitrary feasible root policy in the same model: `first` lead, `later(root_obs) -> b`."""
    from .. import native

    root = tobs.seat
    mass = weights or [1.0 / len(worlds)] * len(worlds)
    total = 0.0
    for m, masks in zip(mass, worlds):
        d = model.world(tobs, masks)
        model.apply(d, first)
        model.advance_others(d, root)
        if d.phase != native.PH_DONE:
            b = later(native.observe(d, root))
            model.apply(d, b)
            model.finish(d, root)
        total += m * model.utility(d, root)
    return total


# ---------------------------------------------------------------- the deployed option (C5.02)


class C5Agent:
    """Plays the stored option at the eligible boundary and after it; falls back and records otherwise."""

    handles_sooli = True

    def __init__(self, base, mlp, encoder: int, equity, node_cap: int = NODE_CAP, deadline_s: float | None = None):
        self.base, self.mlp, self.encoder, self.equity = base, mlp, encoder, equity
        self.node_cap, self.deadline_s = node_cap, deadline_s
        self.option: OptionResult | None = None
        self.option_deal: str | None = None
        self.log: list[dict] = []

    def choose_action(self, obs):
        from ..bridge import action_id, obs_from_player_observation

        tobs = obs_from_player_observation(obs)
        if len(obs.legal_actions) == 1:  # forced: outside every option by construction (the last card)
            if self.option is not None and self.option_deal == obs.deal_ref:
                self.log.append({"event": "forced"})
            return obs.legal_actions[0]
        if self.option is not None and self.option_deal == obs.deal_ref:
            key = root_key(tobs)
            if scope_of(tobs) == self.option.scope and key in self.option.plan:
                b = self.option.plan[key]
                self.log.append({"event": "option_followed", "key": repr(key)[:40]})
                return next(a for a in obs.legal_actions if action_id(a) == b)
            self.log.append({"event": "fallback", "reason": "unexpected information key (off-support)"})
            self.option = None
            return self.base.choose_action(obs)
        if not eligible(obs):
            return self.base.choose_action(obs)
        if self.option_deal == obs.deal_ref:  # one option per deal for this seat
            return self.base.choose_action(obs)
        support = complete_support(obs)
        if support.status != "EXACT_COMPLETE":
            self.log.append({"event": "fallback", "reason": support.status, "support": support.native_count})
            return self.base.choose_action(obs)
        model = NativeModel(self.mlp, self.encoder, self.equity, self.node_cap, self.deadline_s)
        ids = [action_id(a) for a in obs.legal_actions]
        try:
            res = solve_option(tobs, support.worlds, model, ids)
        except (NodeCapExceeded, KeyCollision) as exc:
            self.log.append({"event": "fallback", "reason": str(exc), "nodes": model.nodes})
            return self.base.choose_action(obs)
        self.option, self.option_deal = res, obs.deal_ref
        self.log.append({"event": "option_started", "support": support.native_count, "nodes": res.nodes,
                         "wall_s": res.wall_s, "q": res.q, "chosen": res.chosen})
        return next(a for a in obs.legal_actions if action_id(a) == res.chosen)
