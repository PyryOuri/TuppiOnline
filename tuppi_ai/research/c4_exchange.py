"""C4: stage-specific, information-legal sooli exchange scorers, payoff tables and four-arm replay.

IMPLEMENTATION_SPEC.md section 7. Nothing here touches the 156-action
network head: exchange scorers output one score per physical card (52) and a
card c maps to the engine's SooliExchangeAction / native id 158 + c.

Features are built from the actor's OWN engine observation only:

- giver (SOOLI_GIVE, the soolaaja): its original 13 cards H;
- receiver (SOOLI_RETURN, the partner): its original 13 cards, reconstructed
  as its legal 14-card hand minus the given card g (which the partner legally
  sees), and g itself;
- both: public showing history (seat, card, contract, verbal, order), the
  sooli decisions, declarer/dealer/seat identities, score, ruleset, stage;
  explicit ace-low ranks (sooli trick order) and suit counts.

Physical suits are kept (bidding legality depends on colour); no suit
augmentation. The feature schema is versioned and its width asserted.
"""

from __future__ import annotations

import ctypes as C
import time
from dataclasses import dataclass, field

import numpy as np

FEATURE_SCHEMA = "c4.exchange_features.v1"
# layout: stage(2) | own 52 | own ace-low 52 | suit counts 4x14 | given 52 | shows 4x(4+52+2+1+1)
#         | decisions 2x(4+1+1) | declarer rel 4 | dealer rel 4 | score 2x13 | ruleset 3
FEATURE_WIDTH = 2 + 52 + 52 + 56 + 52 + 4 * 60 + 2 * 6 + 4 + 4 + 26 + 3
EXCHANGE = 158


class IllegalExchangeInput(ValueError):
    pass


def _card_index(card) -> int:
    from tuppi_rules.cards import card_to_index

    return card_to_index(card)


def ace_low_index(c: int) -> int:
    """Suit-major index with ace lowest: A=0, 2=1, ..., K=12 (tc_sooli_rank)."""
    s, r = divmod(c, 13)
    return 13 * s + (0 if r == 12 else r + 1)


def _context(obs, out: np.ndarray, at: int) -> int:
    seat = obs.observing_seat
    rel = lambda x: (x - seat) % 4  # noqa: E731
    for i, show in enumerate(obs.show_actions[:4]):
        base = at + 60 * i
        out[base + rel(show.seat)] = 1
        out[base + 4 + _card_index(show.shown_card)] = 1
        out[base + 56 + (0 if show.declared_contract.value == "NOLO" else 1)] = 1
        out[base + 58] = int(show.verbal_required)
        out[base + 59] = 1
    at += 240
    for i, (s, accept) in enumerate(obs.sooli_decisions[:2]):
        out[at + 6 * i + rel(s)] = 1
        out[at + 6 * i + 4] = int(accept)
        out[at + 6 * i + 5] = 1
    at += 12
    if obs.declarer is not None:
        out[at + rel(obs.declarer)] = 1
    at += 4
    out[at + rel(obs.dealer)] = 1
    at += 4
    own, other = seat % 2, 1 - seat % 2
    sc = (obs.match_score.team0, obs.match_score.team1)
    out[at + min(sc[own] // 4, 12)] = 1
    out[at + 13 + min(sc[other] // 4, 12)] = 1
    at += 26
    out[at + {"project_target_v1": 0, "project_target_v2": 1, "project_target_v3": 2}[obs.ruleset_id.value]] = 1
    return at + 3


def _hand_block(cards: list[int], out: np.ndarray, at: int) -> int:
    for c in cards:
        out[at + c] = 1
        out[at + 52 + ace_low_index(c)] = 1
    for s in range(4):
        out[at + 104 + 14 * s + sum(1 for c in cards if c // 13 == s)] = 1
    return at + 160


def give_features(obs) -> tuple[np.ndarray, list[int]]:
    """(features, legal card ids) for the soolaaja's give; reads the observation only."""
    if obs.phase.value != "SOOLI_GIVE" or obs.observing_seat != obs.soolaaja or not obs.legal_actions:
        raise IllegalExchangeInput("not the soolaaja's give decision")
    hand = sorted(_card_index(c) for c in obs.own_hand)
    if len(hand) != 13:
        raise IllegalExchangeInput("the giver must hold its original 13 cards")
    out = np.zeros(FEATURE_WIDTH, dtype=np.float32)
    out[0] = 1
    at = _hand_block(hand, out, 2)
    at += 52  # no given card for the giver
    _context(obs, out, at)
    legal = sorted(_card_index(a.card) for a in obs.legal_actions)
    if legal != hand:
        raise IllegalExchangeInput("give mask must be exactly the own 13 cards")
    return out, legal


def receiver_original_hand(obs) -> list[int]:
    """P = the partner's legal 14 cards minus the given card (never read from truth)."""
    g = _card_index(obs.sooli_given_card)
    hand = sorted(_card_index(c) for c in obs.own_hand)
    if len(hand) != 14 or g not in hand:
        raise IllegalExchangeInput("the receiver must hold 14 cards including the given card")
    return [c for c in hand if c != g]


def return_features(obs) -> tuple[np.ndarray, list[int]]:
    if (obs.phase.value != "SOOLI_RETURN" or obs.soolaaja is None
            or obs.observing_seat != (obs.soolaaja + 2) % 4 or obs.sooli_given_card is None):
        raise IllegalExchangeInput("not the partner's return decision")
    original = receiver_original_hand(obs)
    out = np.zeros(FEATURE_WIDTH, dtype=np.float32)
    out[1] = 1
    at = _hand_block(original, out, 2)
    out[at + _card_index(obs.sooli_given_card)] = 1
    _context(obs, out, at + 52)
    legal = sorted(_card_index(a.card) for a in obs.legal_actions)
    if legal != original:
        raise IllegalExchangeInput("return mask must be the original 13 cards (the given card excluded)")
    return out, legal


def exchange_scorer(seed: int):
    """Two hidden layers of 128 with GELU, 52 outputs; initialisation recorded by its seed."""
    import torch
    from torch import nn

    gen = torch.Generator().manual_seed(seed)
    net = nn.Sequential(nn.Linear(FEATURE_WIDTH, 128), nn.GELU(), nn.Linear(128, 128), nn.GELU(), nn.Linear(128, 52))
    with torch.no_grad():
        for p in net.parameters():
            p.copy_(torch.randn(p.shape, generator=gen) * (0.05 if p.dim() > 1 else 0.0))
    net.schema, net.init_seed = FEATURE_SCHEMA, seed
    return net


def scores(net, feat: np.ndarray) -> np.ndarray:
    import torch

    if feat.shape != (FEATURE_WIDTH,) or getattr(net, "schema", None) != FEATURE_SCHEMA:
        raise IllegalExchangeInput("feature schema/width mismatch")
    with torch.no_grad():
        return net(torch.from_numpy(feat[None]))[0].numpy().astype(np.float64)


def masked_distribution(s: np.ndarray, legal: list[int], temperature: float = 1.0) -> dict[int, float]:
    z = np.array([s[c] for c in legal]) / temperature
    z -= z.max()
    p = np.exp(z)
    p /= p.sum()
    return dict(zip(legal, p.tolist()))


def greedy(s: np.ndarray, legal: list[int]) -> int:
    """First maximum in ascending card order."""
    return max(legal, key=lambda c: (s[c], -c))


class ExchangePolicyAgent:
    """Switch-on/off wrapper: scorer-chosen give/return; everything else (and disabled stages) delegated."""

    handles_sooli = True

    def __init__(self, base, give_net=None, return_net=None):
        self.base, self.give_net, self.return_net = base, give_net, return_net
        self.decisions = []

    def choose_action(self, obs):
        phase = obs.phase.value
        if phase == "SOOLI_GIVE" and self.give_net is not None and len(obs.legal_actions) > 1:
            feat, legal = give_features(obs)
            c = greedy(scores(self.give_net, feat), legal)
        elif phase == "SOOLI_RETURN" and self.return_net is not None and len(obs.legal_actions) > 1:
            feat, legal = return_features(obs)
            c = greedy(scores(self.return_net, feat), legal)
        else:
            return self.base.choose_action(obs)
        self.decisions.append((phase, c))
        return next(a for a in obs.legal_actions if _card_index(a.card) == c)


# ---------------------------------------------------------------- payoff tables (evaluator-private)


def heuristic_continuation(deal) -> int:
    """Frozen masked controllers: every active seat plays tc_sooli_policy from its own observation.
    Returns 1 if the soolaaja survives (took no trick)."""
    from .. import native

    d = native.TcDeal()
    C.pointer(d)[0] = deal
    rng = C.c_uint64(0x5EED)
    while d.phase == native.PH_SOOLI_PLAY:
        seat = d.cur
        if seat == (d.soolaaja + 2) % 4:
            raise RuntimeError("the dead partner was asked to play")
        a = native.sooli_policy(native.observe(d, seat), rng)
        if native.lib.tc_apply(C.byref(d), a) != 0:
            raise RuntimeError("frozen controller chose an illegal card")
    if d.phase != native.PH_DONE:
        raise RuntimeError("sooli continuation did not finish")
    return int(d.sooli_won)


@dataclass
class PayoffTable:
    gives: list
    returns: dict                                      # g -> ordered legal returns
    survival: np.ndarray                               # [13, 13] actual outcome under frozen heuristics
    pi_proxy: np.ndarray                               # [13, 13] perfect-information survival (labelled proxy)
    cost: dict = field(default_factory=dict)
    labels: dict = field(default_factory=lambda: {
        "survival": "actual sooli outcome under frozen masked heuristic controllers (contract fixture)",
        "pi_proxy": "perfect-information survival: a labelled development proxy, never the primary outcome"})


def payoff_table(pre_give) -> PayoffTable:
    """T[g, r] over every legal (give, return) pair of one accepted pre-give state (169 continuations)."""
    from .. import native

    if pre_give.phase != native.PH_SOOLI_GIVE:
        raise IllegalExchangeInput("payoff tables start at an accepted pre-give state")
    s = pre_give.soolaaja
    gives = [c for c in range(52) if pre_give.hand[s] >> c & 1]
    surv = np.full((len(gives), 13), -1, dtype=np.int8)
    proxy = np.full((len(gives), 13), -1, dtype=np.int8)
    returns = {}
    c0, t0 = time.process_time(), time.perf_counter()
    for i, g in enumerate(gives):
        after_give = native.TcDeal()
        C.pointer(after_give)[0] = pre_give
        if native.lib.tc_apply(C.byref(after_give), EXCHANGE + g) != 0:
            raise RuntimeError("illegal give")
        legal = [a - EXCHANGE for a in native.legal(after_give)]
        if len(legal) != 13 or g in legal:
            raise RuntimeError("return mask is not 13 cards excluding the given card")
        returns[g] = legal
        for j, r in enumerate(legal):
            d = native.TcDeal()
            C.pointer(d)[0] = after_give
            if native.lib.tc_apply(C.byref(d), EXCHANGE + r) != 0:
                raise RuntimeError("illegal return")
            counts = [bin(d.hand[x]).count("1") for x in range(4)]
            if counts != [13, 13, 13, 13]:
                raise RuntimeError(f"hand sizes after the exchange {counts}")
            proxy[i, j] = native.sooli_solve(d)
            surv[i, j] = heuristic_continuation(d)
    cost = {"continuations": int(surv.size), "cpu_s": time.process_time() - c0, "wall_s": time.perf_counter() - t0}
    cost["cpu_s_per_continuation"] = cost["cpu_s"] / cost["continuations"]
    return PayoffTable(gives, returns, surv, proxy, cost)


# ---------------------------------------------------------------- populations (X10)


def check_confirmation_source(meta: dict) -> None:
    """Only fresh v3 pre-give states accepted by the frozen offer policy may confirm (E030/E037)."""
    if meta.get("ruleset") != "project_target_v3":
        raise ValueError("a non-v3 bank cannot serve as fresh v3 confirmation")
    if meta.get("generator") in ("tools/sooli_bank.py",) or meta.get("selection") == "prefilter+searched_gain":
        raise ValueError("the legacy selected sooli bank is development material, not confirmation")
    for key in ("source_deal_ids", "offers_made", "offers_accepted", "offers_rejected", "offer_policy_id", "split"):
        if key not in meta:
            raise ValueError(f"missing population field {key}")
    if meta["offers_made"] != meta["offers_accepted"] + meta["offers_rejected"]:
        raise ValueError("accepted/rejected denominators do not add up")


def accepted_population(source_records: list[dict], offer_policy_id: str, split: str) -> dict:
    """Population metadata from per-source-deal offer records {deal_id, offers: [(seat, accepted)]}."""
    made = sum(len(r["offers"]) for r in source_records)
    acc = sum(1 for r in source_records for _s, a in r["offers"] if a)
    return {"ruleset": "project_target_v3", "generator": "tuppi_ai.research.runner_v3", "split": split,
            "offer_policy_id": offer_policy_id, "source_deal_ids": [r["deal_id"] for r in source_records],
            "source_deals": len(source_records), "offers_made": made, "offers_accepted": acc,
            "offers_rejected": made - acc,
            "accepted_states": [r["deal_id"] for r in source_records if any(a for _s, a in r["offers"])]}
