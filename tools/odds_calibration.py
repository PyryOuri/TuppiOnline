"""How well the live odds tool's numbers match the bots the owner plays with.

The tool (TuppiProject ``tuppi_server.training_analysis``) shows, for every
unseen card, the chance that each other seat holds it: exact uniform odds
over the layouts consistent with what the seat has seen, and an "assumed"
view that adds four behavioural rules measured on the old reference bots
(``show_lowest``, ``duck_high``, ``win_high_last``, ``follow_low``). The owner
plays against TuppiAI's bots. This measures, on project_target_v3 deals with
TuppiAI's best agent on all four seats (the authoritative engine):

* the mean negative log-likelihood of each unseen card's true holder under
  (a) the exact odds, (b) the assumed view, (c) the card-location belief net
  (``runs/belief_v1.pt``, exact tempered draws, alpha 0.5 and 1.0), at the
  observed seat's trick-play decisions (sooli deals are counted, not measured);
* calibration of (a) and (c): predicted probability buckets against how often
  the card really was there;
* each behavioural rule's firings and violations against the true hands.

    python tools/odds_calibration.py --deals 200 --out runs/odds_calibration.json
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tuppi_ai import belief as belief_module  # noqa: E402
from tuppi_ai import native  # noqa: E402
from tuppi_ai.best import best_agents  # noqa: E402
from tuppi_ai.bridge import obs_from_player_observation  # noqa: E402

CLIP = 1e-3
BUCKETS = [(i / 10, (i + 1) / 10) for i in range(10)]


def stage_of(trick_number: int) -> str:
    return "tricks 1-3" if trick_number <= 3 else "tricks 4-7" if trick_number <= 7 else "tricks 8-13"


def nll(p: float) -> float:
    return -math.log(max(p, CLIP))


def belief_marginals(net, obs, alpha: float, worlds: int, rng) -> dict[int, np.ndarray]:
    """Empirical card -> seat frequencies from exact tempered draws (relative seats mapped back)."""
    tc = obs_from_player_observation(obs)
    feat = native.encode(tc, encoder=net.encoder)[None]
    with torch.no_grad():
        p = torch.softmax(net(torch.from_numpy(feat)), dim=2)[0].numpy()
    weights = p ** alpha
    counts = np.zeros((52, 4))
    for _ in range(worlds):
        world = native.sample_world_weighted(tc, weights, rng)
        if world is None:
            world = native.sample_world(tc, rng)
        for seat in range(4):
            mask = world.hand[seat]
            for index in range(52):
                if mask >> index & 1:
                    counts[index, seat] += 1
    return counts / worlds


def rule_checks(research, contract, tally):
    """Every behavioural-rule firing in a completed ordinary deal, checked against the true hands."""
    from tuppi_server.training_analysis import play_rule_firing, show_rule_firing

    result = research.public_result
    hands = [set(hand) for hand in research.initial_hands]
    for show in result.show_actions:
        firing = show_rule_firing(seat=show.seat, shown_card=show.shown_card,
                                  declared_contract=show.declared_contract,
                                  verbal_required=show.verbal_required)
        if firing is not None:
            tally[firing.rule]["firings"] += 1
            tally[firing.rule]["violations"] += bool(firing.excluded & hands[firing.seat])
    for trick in result.completed_tricks:
        plays = list(trick.plays)
        led = plays[0].card.suit
        highest = plays[0].card.rank.value
        hands[plays[0].seat].discard(plays[0].card)
        for index, play in enumerate(plays[1:], start=1):
            hands[play.seat].discard(play.card)
            firing = play_rule_firing(contract=contract, led=led, highest=highest, play=play,
                                      is_final=index == len(plays) - 1,
                                      wins_trick=trick.winner == play.seat)
            if firing is not None:
                tally[firing.rule]["firings"] += 1
                tally[firing.rule]["violations"] += bool(firing.excluded & hands[firing.seat])
            if play.card.suit is led:
                highest = max(highest, play.card.rank.value)


def run(args) -> dict:
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
                              create_match, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK, card_to_index
    from tuppi_server.training_analysis import generate_training_analysis

    agents = best_agents()
    net = belief_module.load(args.belief)
    rng_native = C.c_uint64(12345)
    positions = []  # one per measured decision
    calibration = {name: defaultdict(lambda: [0, 0.0, 0]) for name in ("exact", "belief_0.5", "belief_1.0")}
    tally = defaultdict(lambda: {"firings": 0, "violations": 0})
    sooli_deals = contracts = 0
    started = time.time()
    with trusted_transitions():
        for index in range(args.deals):
            rng = random.Random(f"{args.seed}|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, observed = index % 4, (index // 4) % 4
            match = create_match(initial_score=MatchScore(0, 0), initial_dealer=dealer,
                                 match_ref=f"calib-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            seen = 0
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                deal = state.active_deal
                if (seat == observed and obs.phase is EnginePhase.TRICK_PLAY and deal.soolaaja is None
                        and len(obs.legal_actions) > 1):
                    seen += 1
                    if (seen - 1) % args.every == 0:
                        truth = {card: s for s in range(4) for card in deal.hands[s]}
                        tool = generate_training_analysis(obs)
                        exact = {e["card"]: e["seat_probabilities"] for e in tool["card_locations"]}
                        assumed = tool["assumed"]
                        assumed_loc = None if assumed is None else {
                            e["card"]: e["seat_probabilities"] for e in assumed["card_locations"]}
                        beliefs = {a: belief_marginals(net, obs, a, args.belief_worlds, rng_native)
                                   for a in (0.5, 1.0)}
                        row = {"deal": index, "trick": len(obs.completed_tricks) + 1,
                               "contract": obs.contract.value, "cards": len(exact),
                               "exact": 0.0, "belief_0.5": 0.0, "belief_1.0": 0.0,
                               "assumed": None if assumed is None else 0.0,
                               "assumed_zero": 0,
                               "prior": None if assumed is None else assumed["prior_probability"]}
                        others = [s for s in range(4) if s != seat]
                        for code, probs in exact.items():
                            from tuppi_rules import card_from_code
                            card = card_from_code(code)
                            owner = truth[card]
                            row["exact"] += nll(probs[owner])
                            ci = card_to_index(card)
                            for name, a in (("belief_0.5", 0.5), ("belief_1.0", 1.0)):
                                row[name] += nll(float(beliefs[a][ci, owner]))
                            if assumed_loc is not None:
                                pa = assumed_loc[code][owner]
                                row["assumed"] += nll(pa)
                                row["assumed_zero"] += pa <= 0.0
                            for s in others:
                                hit = int(owner == s)
                                for name, value in (("exact", probs[s]),
                                                    ("belief_0.5", float(beliefs[0.5][ci, s])),
                                                    ("belief_1.0", float(beliefs[1.0][ci, s]))):
                                    bucket = min(int(value * 10), 9)
                                    cell = calibration[name][bucket]
                                    cell[0] += 1
                                    cell[1] += value
                                    cell[2] += hit
                        positions.append(row)
                state = apply_match_action(state, agents[seat].choose_action(obs))
            research = state.completed_deals[-1]
            if research.public_result.soolaaja is not None:
                sooli_deals += 1
            else:
                contracts += 1
                rule_checks(research, research.public_result.contract, tally)
            if (index + 1) % 10 == 0:
                print(f"{index + 1} deals, {len(positions)} positions, {time.time() - started:.0f} s", flush=True)
    return summarise(positions, calibration, tally, sooli_deals, contracts, args, time.time() - started)


def cluster_ci(rows, key, base=None):
    """Mean per-card NLL (or paired difference vs `base`) with a 95% interval clustered by deal."""
    by_deal = defaultdict(lambda: [0.0, 0])
    for row in rows:
        value = row[key] - (row[base] if base else 0.0)
        by_deal[row["deal"]][0] += value
        by_deal[row["deal"]][1] += row["cards"]
    cards = sum(n for _, n in by_deal.values())
    mean = sum(v for v, _ in by_deal.values()) / cards
    # ratio estimator: per-deal residuals
    k = len(by_deal)
    residuals = [(v - mean * n) for v, n in by_deal.values()]
    var = k / (k - 1) * sum(r * r for r in residuals) / (cards * cards) if k > 1 else float("nan")
    half = 1.96 * math.sqrt(var)
    return {"mean": round(mean, 4), "ci": [round(mean - half, 4), round(mean + half, 4)], "cards": cards,
            "positions": len(rows)}


def summarise(positions, calibration, tally, sooli_deals, contracts, args, seconds) -> dict:
    groups = {"all": positions}
    for row in positions:
        groups.setdefault(stage_of(row["trick"]), []).append(row)
        groups.setdefault(row["contract"], []).append(row)
    table = {}
    for name, rows in groups.items():
        if not rows:
            continue
        table[name] = {model: cluster_ci(rows, model) for model in ("exact", "belief_0.5", "belief_1.0")}
        table[name]["belief_0.5 - exact"] = cluster_ci(rows, "belief_0.5", "exact")
        table[name]["belief_1.0 - exact"] = cluster_ci(rows, "belief_1.0", "exact")
        with_assumed = [r for r in rows if r["assumed"] is not None]
        if with_assumed:
            table[name]["assumed (where shown)"] = cluster_ci(with_assumed, "assumed")
            table[name]["exact (same positions)"] = cluster_ci(with_assumed, "exact")
            table[name]["assumed - exact"] = cluster_ci(with_assumed, "assumed", "exact")
    assumed_rows = [r for r in positions if r["assumed"] is not None]
    calib = {
        name: [{"bucket": f"{lo:.1f}-{hi:.1f}", "n": cell[0],
                "predicted": round(cell[1] / cell[0], 3) if cell[0] else None,
                "observed": round(cell[2] / cell[0], 3) if cell[0] else None}
               for (lo, hi), cell in ((BUCKETS[b], cells[b]) for b in range(10))]
        for name, cells in calibration.items()
    }
    return {
        "deals": args.deals, "seed": args.seed, "every": args.every, "belief_worlds": args.belief_worlds,
        "ordinary_deals": contracts, "sooli_deals": sooli_deals, "positions": len(positions),
        "seconds": round(seconds),
        "nll_per_unseen_card": table,
        "assumed_available": round(len(assumed_rows) / max(1, len(positions)), 3),
        "assumed_true_holder_excluded_cards": sum(r["assumed_zero"] for r in assumed_rows),
        "assumed_cards": sum(r["cards"] for r in assumed_rows),
        "assumed_prior_median": statistics.median(r["prior"] for r in assumed_rows) if assumed_rows else None,
        "calibration": calib,
        "rules": {rule: dict(v) for rule, v in sorted(tally.items())},
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=200)
    p.add_argument("--seed", default="odds-calibration-v1")
    p.add_argument("--every", type=int, default=2, help="measure every n-th decision of the observed seat")
    p.add_argument("--belief", type=Path, default=ROOT / "runs" / "belief_v1.pt")
    p.add_argument("--belief-worlds", type=int, default=1000)
    p.add_argument("--out", type=Path, default=ROOT / "runs" / "odds_calibration.json")
    args = p.parse_args()
    summary = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary["nll_per_unseen_card"]["all"], indent=1))
    print(json.dumps(summary["rules"], indent=1))


if __name__ == "__main__":
    main()
