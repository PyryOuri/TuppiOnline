"""Where does the heuristic lose? Disagreement mining of partner_aware_lead_v2 against VRPO3.

The heuristic plays all four seats in the authoritative engine (project_target_v3,
random dealer and starting score). A native deal is kept in lockstep with the
engine (as in tests/test_differential_v2.py), so every decision has its exact
full state. At every showing and trick-play decision with more than one legal
action this records:

* the heuristic's action and the reason codes and rule ids of the selected
  candidate (`decide(..., diagnostics=True)`);
* the greedy action of the teacher (VRPO3, `models/vrpo3_final.pt`) and of the
  heuristic's behaviour clone (`runs/bc_small.pt`, a fidelity check);
* situation features a player can see (contract, role, position in the
  trick, tricks left, the cards' rank among the legal ones, ...).

Pricing. For every disagreement (and a control sample of agreements), every
legal action is played out natively from the full state with the clone on all
seats (`native.branch_values`): the value of changing only this decision while
the heuristic, as modelled by its clone, plays the rest. gain = q[teacher] -
q[heuristic] is the acting team's match-equity gain of the switch on that deal;
averaged over many deals of a situation it estimates the one-step improvement
available to the heuristic there.

    python tools/heuristic_mining.py --deals 20000 --workers 4 --out runs/heuristic/mine1.pkl
"""

from __future__ import annotations

import argparse
import ctypes as C
import gzip
import pickle
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEACHER = ROOT / "models" / "vrpo3_final.pt"
CLONE = ROOT.parent / "TuppiAI" / "runs" / "bc_small.pt"
_W: dict = {}


def _init(teacher: str, clone: str, control: float, seed: str) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_agents.sooli import SooliFallbackAgent

    from tuppi_ai import model as qmodel
    from tuppi_ai import native
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    from tuppi_ai.incumbent import incumbent_agents
    from tuppi_ai.offer_screen import load as load_offer

    native.set_parallel(False)  # one core per worker process
    agents = incumbent_agents()
    _W["agents"] = agents
    _W["wrapped"] = {s: SooliFallbackAgent(a) for s, a in agents.items()}
    t, c = qmodel.load(teacher, "cpu"), qmodel.load(clone, "cpu")
    if t.encoder != c.encoder:
        raise ValueError("teacher and clone must share an encoder")
    _W["encoder"] = t.encoder
    _W["teacher"], _W["clone"] = native.Mlp(t), native.Mlp(c)
    om, _ = load_offer(ROOT / "models" / "offer_model_selfplay.pt")
    _W["offer"] = native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)
    native.set_offer_model(_W["offer"])
    _W["env"] = native.Env(4096, 11, Equity.load(EQUITY).table, single_deal=True, encoder=c.encoder)
    _W["env"].set_sooli(0, False, False, 0.0)
    _W["control"], _W["seed"] = control, seed


def _score(rng: random.Random) -> tuple[int, int]:
    level = rng.randrange(13)
    if level == 0:
        return (0, 0)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


SUITS = ("hearts", "diamonds", "clubs", "spades")


def _situation(d, seat: int, legal: list[int], a_h: int, a_t: int) -> dict:
    """Visible situation features of a decision (native deal before the action)."""
    out = {"phase": "show" if d.phase == 0 else "play", "n_shows": int(d.n_shows)}
    if d.phase == 0:
        out["heur_contract"] = "RAMI" if a_h >= 104 else "NOLO"
        out["teacher_contract"] = "RAMI" if a_t >= 104 else "NOLO"
        return out
    n = int(d.n_played)
    pos = n % 4
    trick = [(int(d.play_seat[i]), int(d.play_card[i])) for i in range(n - pos, n)]
    out.update(contract="RAMI" if d.contract == 1 else "NOLO",
               role="declarer" if d.declarer >= 0 and d.declarer % 2 == seat % 2 else "defender",
               pos=pos, tricks_left=13 - n // 4)
    if pos:
        led = trick[0][1] // 13
        best_seat, best = max(((s, c) for s, c in trick if c // 13 == led), key=lambda x: x[1])
        out["led_suit_follow"] = any(c // 13 == led for c in legal)
        out["partner_winning"] = best_seat % 2 == seat % 2
    else:
        out["led_suit_follow"] = None
        out["partner_winning"] = None

    def rank_class(a: int) -> str:
        same = sorted(c for c in legal if c // 13 == a // 13)
        if len(same) == 1:
            return "only"
        return "highest" if a == same[-1] else "lowest" if a == same[0] else "middle"

    out["heur_rank"], out["teacher_rank"] = rank_class(a_h), rank_class(a_t)
    out["same_suit"] = a_h // 13 == a_t // 13
    hand = int(d.hand[seat])
    played = 0
    for i in range(n):
        played |= 1 << int(d.play_card[i])
    lens = [bin(hand >> (13 * s) & 0x1FFF).count("1") for s in range(4)]

    def card_facts(a: int, prefix: str) -> None:
        s = a // 13
        higher = sum(1 for c in range(a + 1, 13 * s + 13) if not (hand >> c) & 1 and not (played >> c) & 1)
        out[prefix + "_card"] = a % 13 + 2  # 2..14 (ace)
        out[prefix + "_suit_len"] = lens[s]
        out[prefix + "_higher_out"] = higher  # unplayed higher cards of the suit held by others
        out[prefix + "_longest"] = lens[s] == max(lens)

    card_facts(a_h, "heur")
    card_facts(a_t, "teacher")
    return out


def mine(indices: list[int]) -> list[dict]:
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    from tuppi_ai import native
    from tuppi_ai.bridge import action_id, mask_of

    agents, wrapped, enc = _W["agents"], _W["wrapped"], _W["encoder"]
    rows, states = [], []
    searched = (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY)
    with trusted_transitions():
        for index in indices:
            rng = random.Random(f"{_W['seed']}|mine|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), _score(rng)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="mine",
                             ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=dealer, hands=hands))
            deal = native.new_deal([mask_of(h) for h in hands], dealer, score[0], score[1], ruleset=3)
            step = 0
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                if state.phase in searched and len(obs.legal_actions) > 1:
                    dec = agents[seat].decide(obs, diagnostics=True)
                    action = dec.action
                    a_h = action_id(action)
                    legal = [action_id(x) for x in obs.legal_actions]
                    feat = native.encode(native.observe(deal, seat), encoder=enc)[None]
                    qt, qc = _W["teacher"].forward(feat)[0], _W["clone"].forward(feat)[0]
                    a_t, a_c = max(legal, key=lambda a: qt[a]), max(legal, key=lambda a: qc[a])
                    sel = next(c for c in dec.diagnostics.candidates if c.selected)
                    row = {"deal": index, "step": step, "seat": seat, "k": len(legal), "heur": a_h, "teacher": a_t,
                           "clone": a_c, "reasons": "|".join(sorted(sel.reason_codes)),
                           "rules": "|".join(sorted(r for r in sel.rule_ids if not r.startswith("common."))),
                           **_situation(deal, seat, legal, a_h, a_t)}
                    row["priced"] = a_h != a_t or rng.random() < _W["control"]
                    if row["priced"]:
                        row["state"] = len(states)
                        states.append(bytes(deal))
                    rows.append(row)
                else:
                    action = wrapped[seat].choose_action(obs)
                    a_h = action_id(action)
                if native.lib.tc_apply(C.byref(deal), a_h) != 0:
                    raise RuntimeError(f"native engine rejected {a_h} at deal {index} step {step}")
                state = apply_match_action(state, action)
                step += 1
    _price(rows, states)
    for r in rows:
        r.pop("state", None)
    return rows


def _price(rows: list[dict], blobs: list[bytes]) -> None:
    """q of the heuristic's, the teacher's and the clone's action for each priced row."""
    from tuppi_ai import native

    if not blobs:
        return
    priced = [r for r in rows if r["priced"]]
    env, rng = _W["env"], C.c_uint64(hash((_W["seed"], priced[0]["deal"])) & 0xFFFFFFFFFFFF)
    start = 0
    while start < len(blobs):
        stop, games = start, 0
        while stop < len(blobs) and games + priced[stop]["k"] <= env.n:
            games += priced[stop]["k"]
            stop += 1
        states = (native.TcDeal * (stop - start))(*[native.TcDeal.from_buffer_copy(b) for b in blobs[start:stop]])
        acts, kk, q = native.branch_values(env, _W["clone"], states, stop - start, 0, rng)
        for j in range(stop - start):
            r = priced[start + j]
            qa = {int(acts[j, i]): float(q[j, i]) for i in range(kk[j])}
            r["q_heur"], r["q_teacher"], r["q_clone"] = qa[r["heur"]], qa[r["teacher"]], qa[r["clone"]]
            r["q_best"] = max(qa.values())
        start = stop


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=20000)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--chunk", type=int, default=50)
    p.add_argument("--control", type=float, default=0.1, help="share of agreements priced as a control")
    p.add_argument("--seed", default="mine-v1")
    p.add_argument("--teacher", default=str(TEACHER))
    p.add_argument("--clone", default=str(CLONE))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    chunks = [list(range(i, min(i + a.chunk, a.start + a.deals))) for i in range(a.start, a.start + a.deals, a.chunk)]
    t0 = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.teacher, a.clone, a.control, a.seed)) as pool:
        for i, part in enumerate(pool.map(mine, chunks)):
            rows.extend(part)
            if (i + 1) % 20 == 0:
                done = (i + 1) * a.chunk
                print(f"{done} deals, {len(rows)} decisions, {done / (time.time() - t0):.1f} deals/s", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wb") as f:
        pickle.dump({"rows": rows, "args": vars(a), "seconds": time.time() - t0}, f)
    print(f"{a.deals} deals, {len(rows)} decisions in {time.time() - t0:.0f} s -> {a.out}")


if __name__ == "__main__":
    main()
