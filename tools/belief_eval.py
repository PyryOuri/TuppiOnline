"""Held-out test of card-location belief nets against the bots the owner plays.

Positions:

* **held-out self-play**: the games `tools/gen_belief_tuppi.py` held out
  (TuppiAI's best agent on all four seats, project_target_v3), replayed from
  their records; one observer per deal (rotating), at its own trick-play
  decisions that have a choice;
* **the owner's games**: the real-game deals in the server's saved rooms,
  from the human seat at its trick-play decisions (three TuppiAI bots), the
  exact use of the odds window.

Models: the exact odds the window shows, and each net as the window would
show it: exact draws from the tempered product of its card marginals over the
layouts consistent with the observation. Mean negative log-likelihood of every
unseen card's true holder, 95% intervals clustered by deal, paired against
the exact odds, and calibration.

    python tools/belief_eval.py --games runs/belief/tuppi_v3 \\
        --net old=runs/belief_v1.pt --net new=runs/belief_tuppi_v3.pt
"""

from __future__ import annotations

import argparse
import ctypes as C
import glob
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLIP = 1e-3
ALPHAS = tuple(float(a) for a in __import__("os").environ.get("BELIEF_EVAL_ALPHAS", "0.5,1.0").split(","))
_W: dict = {}


def _init(nets: dict[str, str], worlds: int) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import belief

    _W["nets"] = {name: belief.load(path) for name, path in nets.items()}
    _W["worlds"] = worlds
    _W["rng"] = C.c_uint64(987654321)


def _measure(obs, holder: dict, deal_key) -> dict:
    """NLL sums and calibration pairs for one position."""
    import torch

    from tuppi_ai import native
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_rules import card_from_code
    from tuppi_rules.cards import card_to_index
    from tuppi_server.training_analysis import generate_training_analysis

    exact = {e["card"]: e["seat_probabilities"]
             for e in generate_training_analysis(obs, with_assumptions=False)["card_locations"]}
    seat = obs.observing_seat
    tc = obs_from_player_observation(obs)
    models = {"exact": {code: probs for code, probs in exact.items()}}
    for name, net in _W["nets"].items():
        feat = native.encode(tc, encoder=net.encoder)[None]
        with torch.no_grad():
            p = torch.softmax(net(torch.from_numpy(feat)), dim=2)[0].numpy()
        for alpha in ALPHAS:
            counts = np.zeros((52, 4))
            for _ in range(_W["worlds"]):
                world = native.sample_world_weighted(tc, p ** alpha, _W["rng"])
                if world is None:
                    world = native.sample_world(tc, _W["rng"])
                for s in range(4):
                    mask = world.hand[s]
                    for i in range(52):
                        if mask >> i & 1:
                            counts[i, s] += 1
            counts /= _W["worlds"]
            models[f"{name} a={alpha}"] = {
                code: list(counts[card_to_index(card_from_code(code))]) for code in exact}
    row = {"deal": deal_key, "cards": len(exact), "nll": {}, "calib": {}}
    for name, probs_by_card in models.items():
        total, pairs = 0.0, []
        for code, probs in probs_by_card.items():
            owner = holder[code]
            total += -math.log(max(probs[owner], CLIP))
            for s in range(4):
                if s != seat:
                    pairs.append((float(probs[s]), int(owner == s)))
        row["nll"][name] = total
        row["calib"][name] = pairs
    return row


def _selfplay_task(record: dict) -> list[dict]:
    from tuppi_engine import (EnginePhase, ExplicitDeal, action_from_data, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId, card_from_code, card_to_code

    hands = tuple(tuple(card_from_code(c) for c in h) for h in record["hands"])
    observer = (record["index"] // 10) % 4
    rows = []
    with trusted_transitions():
        match = create_match(initial_score=MatchScore(*record["score"]), initial_dealer=record["dealer"],
                             match_ref=f"belief-{record['index']}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
        state = begin_explicit_deal(match, ExplicitDeal(dealer=record["dealer"], hands=hands))
        for raw in record["actions"]:
            deal = state.active_deal
            if (state.phase in ACTIVE_PHASES and state.current_actor == observer
                    and deal.phase is EnginePhase.TRICK_PLAY and deal.soolaaja is None):
                obs = match_observation_for(state, observer)
                if len(obs.legal_actions) > 1:
                    holder = {card_to_code(c): s for s in range(4) for c in deal.hands[s]}
                    rows.append(_measure(obs, holder, f"selfplay-{record['index']}"))
            state = apply_match_action(state, action_from_data(raw))
    return rows


def _owner_task(job: tuple[str, int, int]) -> list[dict]:
    room_path, deal_number, seat = job
    from tuppi_engine import EnginePhase
    from tuppi_rules import card_to_code
    from tuppi_server import LiveMatchRunner
    from tuppi_server.deal_review import seat_decisions

    record = json.load(open(room_path))
    runner = LiveMatchRunner.from_persistence_record(record["runner"])
    research = runner.state.completed_deals[deal_number]
    rows = []
    for decision in seat_decisions(runner, deal_number=deal_number, seat=seat):
        obs = decision.observation
        if obs.phase is not EnginePhase.TRICK_PLAY or len(obs.legal_actions) < 2:
            continue
        played = {play.card for trick in obs.completed_tricks for play in trick.plays}
        played |= {play.card for play in obs.current_trick}
        holder = {card_to_code(c): s for s in range(4) for c in research.initial_hands[s] if c not in played}
        rows.append(_measure(obs, holder, f"owner-{record['room_code']}-{deal_number}"))
    return rows


def _owner_jobs(rooms_dir: Path) -> list[tuple[str, int, int]]:
    jobs = []
    for path in sorted(rooms_dir.glob("room-*.json")):
        record = json.load(open(path))
        runner = record.get("runner") or {}
        if runner.get("ruleset_id") not in ("project_target_v2", "project_target_v3"):
            continue
        humans = [s["seat"] for s in record.get("sessions", [])]
        if len(humans) != 1:
            continue
        from tuppi_server import LiveMatchRunner

        restored = LiveMatchRunner.from_persistence_record(runner)
        for number, research in enumerate(restored.state.completed_deals):
            if research.public_result.soolaaja is None:
                jobs.append((str(path), number, humans[0]))
    return jobs


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {}
    names = list(rows[0]["nll"])
    by_deal = defaultdict(lambda: {"cards": 0, **{n: 0.0 for n in names}})
    for row in rows:
        cell = by_deal[row["deal"]]
        cell["cards"] += row["cards"]
        for n in names:
            cell[n] += row["nll"][n]
    deals = list(by_deal.values())
    cards = sum(d["cards"] for d in deals)

    def ci(key, base=None):
        values = [(d[key] - (d[base] if base else 0.0), d["cards"]) for d in deals]
        mean = sum(v for v, _ in values) / cards
        k = len(values)
        var = k / (k - 1) * sum((v - mean * c) ** 2 for v, c in values) / cards ** 2 if k > 1 else float("nan")
        half = 1.96 * math.sqrt(var)
        return {"mean": round(mean, 4), "ci": [round(mean - half, 4), round(mean + half, 4)]}

    out = {"positions": len(rows), "deals": len(deals), "cards": cards, "nll": {}, "vs_exact": {}, "calibration": {}}
    for n in names:
        out["nll"][n] = ci(n)
        if n != "exact":
            out["vs_exact"][n] = ci(n, "exact")
        buckets = [[0, 0.0, 0] for _ in range(10)]
        for row in rows:
            for p, hit in row["calib"][n]:
                b = min(int(p * 10), 9)
                buckets[b][0] += 1
                buckets[b][1] += p
                buckets[b][2] += hit
        out["calibration"][n] = [
            {"bucket": f"{b / 10:.1f}", "n": c[0], "predicted": round(c[1] / c[0], 3) if c[0] else None,
             "observed": round(c[2] / c[0], 3) if c[0] else None} for b, c in enumerate(buckets)]
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=Path, required=True, help="a gen_belief_tuppi.py output directory")
    p.add_argument("--net", action="append", default=[], help="name=path, repeatable")
    p.add_argument("--owner-rooms", type=Path,
                   default=Path.home() / "Library" / "Application Support" / "Tuppi" / "server-current")
    p.add_argument("--worlds", type=int, default=400)
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--out", type=Path, default=ROOT / "runs" / "belief_eval.json")
    args = p.parse_args()
    nets = dict(item.split("=", 1) for item in args.net)
    records = [json.loads(line) for path in sorted(glob.glob(str(args.games / "games_*.jsonl")))
               for line in open(path)]
    held_out = [r for r in records if r["test"] and not r["sooli"]]
    owner = _owner_jobs(args.owner_rooms) if args.owner_rooms.exists() else []
    print(f"held-out self-play deals: {len(held_out)}; owner deals: {len(owner)}", flush=True)
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(nets, args.worlds)) as pool:
        selfplay_rows = [r for rows in pool.map(_selfplay_task, held_out) for r in rows]
        owner_rows = [r for rows in pool.map(_owner_task, owner) for r in rows]
    summary = {"nets": nets, "worlds": args.worlds, "alphas": ALPHAS,
               "held_out_selfplay": summarise(selfplay_rows), "owner_games": summarise(owner_rows)}
    args.out.write_text(json.dumps(summary, indent=1))
    for name in ("held_out_selfplay", "owner_games"):
        part = summary[name]
        if not part:
            continue
        print(f"== {name}: {part['positions']} positions, {part['deals']} deals, {part['cards']} cards")
        for model, v in part["nll"].items():
            diff = part["vs_exact"].get(model)
            extra = f"  vs exact {diff['mean']:+.4f} [{diff['ci'][0]:+.4f}, {diff['ci'][1]:+.4f}]" if diff else ""
            print(f"  {model:14s} {v['mean']:.4f} [{v['ci'][0]:.4f}, {v['ci'][1]:.4f}]{extra}")


if __name__ == "__main__":
    main()
