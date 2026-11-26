"""Conversion check for the suit-symmetry student (audit_deliverables/tuppi_sym_student_20261126).

Plays a few ordinary deals with Nelli 1.1's lite bot (VRPO4, C1H) through the release engine,
records every decision the network makes (encoded features and legal network ids), and on
those rows compares:
  - the student's lite network (models/vrpo4sym_v1.lite.npz, native) with the same student in
    PyTorch (models/vrpo4sym_v1.pt): largest Q difference and greedy agreement;
  - the lite network with native.Mlp built directly from the PyTorch weights (must be identical);
  - the student's greedy action with VRPO4's on the same rows (how often the bots differ).

    python tools/sym_student_check.py --deals 64 --out <json>
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tuppi_ai import lite, model as qmodel, native  # noqa: E402


def collect(deals: int, seed: str):
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    rows, legal = [], []
    orig = lite.LiteAgent.greedy_action

    def spy(self, obs, ids):
        a = orig(self, obs, ids)
        rows.append(self._feat[0].copy())
        legal.append(list(ids))
        return a

    lite.LiteAgent.greedy_action = spy
    try:
        mlp = lite.load_mlp(ROOT / "models" / "vrpo4_final.lite.npz")
        agents = {s: lite.LiteAgent(s, mlp=mlp, options=lite.C1H) for s in range(4)}
        for k in range(deals):
            rng = random.Random(f"{seed}|{k}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            score = MatchScore(*rng.choice([(0, 0), (20, 0), (0, 32), (44, 0)]))
            state = create_match(initial_score=score, initial_dealer=k % 4, match_ref="sym-check",
                                 ruleset_id=RulesetId("project_target_v3"))
            with trusted_transitions():
                state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands))
                while state.active_deal is not None and not state.active_deal.complete:
                    seat = state.current_actor
                    state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
    finally:
        lite.LiteAgent.greedy_action = orig
    return np.stack(rows), legal


def greedy(q: np.ndarray, legal: list[list[int]]) -> np.ndarray:
    return np.array([max(ids, key=lambda a: (q[i, a], -a)) for i, ids in enumerate(legal)])


def main() -> None:
    import torch
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=64)
    p.add_argument("--seed", default="sym-student-check-v1")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    feats, legal = collect(a.deals, a.seed)
    unforced = np.array([len(ids) > 1 for ids in legal])

    student_pt = qmodel.load(ROOT / "models" / "vrpo4sym_v1.pt", "cpu").eval()
    student_lite = lite.load_mlp(ROOT / "models" / "vrpo4sym_v1.lite.npz")
    student_direct = native.Mlp(student_pt)
    vrpo4_lite = lite.load_mlp(ROOT / "models" / "vrpo4_final.lite.npz")

    q_lite = student_lite.forward(feats)
    q_direct = student_direct.forward(feats)
    with torch.no_grad():
        q_torch = student_pt(torch.from_numpy(feats.astype(np.float32))).numpy()
    q_v4 = vrpo4_lite.forward(feats)

    g_lite, g_torch, g_v4 = greedy(q_lite, legal), greedy(q_torch, legal), greedy(q_v4, legal)
    legal_mask = np.zeros_like(q_lite, dtype=bool)
    for i, ids in enumerate(legal):
        legal_mask[i, ids] = True
    res = {
        "deals": a.deals, "seed": a.seed, "decisions": int(len(legal)), "unforced": int(unforced.sum()),
        "lite_equals_direct_native_bitwise": bool(np.array_equal(q_lite, q_direct)),
        "lite_vs_torch_max_abs_q_diff_legal": float(np.abs(q_lite - q_torch)[legal_mask].max()),
        "lite_vs_torch_greedy_agreement_unforced": float((g_lite == g_torch)[unforced].mean()),
        "student_vs_vrpo4_greedy_agreement_unforced": float((g_lite == g_v4)[unforced].mean()),
        "student_vs_vrpo4_differing_unforced_decisions": int((g_lite != g_v4)[unforced].sum()),
    }
    print(json.dumps(res, indent=1))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
