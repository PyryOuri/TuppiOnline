"""Play test: what bidding by a readable rule costs against the full bot.

Duplicate protocol of `tuppi_ai.evaluate` (4 rotations x 2 team assignments
per base deal, project_target_v3): one partnership bids by the rule
(`tuppi_ai.rule_bidder.RuleBidder`, card play and the shown card by the bot),
the other is the bot itself. The bot against itself scores exactly zero, so
the rule's equity per deal is its cost (negative) relative to the bot.

    python tools/bid_rule_eval.py --model runs/bidding/pilot/model_point_count_4.json --deals 256
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def _init(model_path: str) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import native

    native.set_rollout_chunk(128)  # several processes run: least total work, same moves
    from tuppi_ai import evaluate as ev
    from tuppi_ai.best import best_agents
    from tuppi_ai.equity import Equity
    from tuppi_ai.rule_bidder import RuleBidder

    if model_path == "old_rule":
        from bid_explain import OldRule
        model = OldRule()
    else:
        from tuppi_ai import bid_models as bm
        model = bm.load(model_path)
    ev._W["equity"] = Equity.load(ROOT / "models" / "equity_incumbent.json")
    ev._W["ruleset"] = "v3"
    ev._W["candidate"] = {s: RuleBidder(a, model) for s, a in best_agents().items()}
    ev._W["opponent"] = best_agents()


def _measure(index: int, seed: str, scores: str) -> dict:
    from tuppi_ai import evaluate as ev
    return ev.measure(index, seed, scores)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, help="a model_*.json from bid_explain.py, or old_rule")
    p.add_argument("--deals", type=int, default=256)
    p.add_argument("--seed", default="bid-rule-eval-v1")
    p.add_argument("--scores", choices=("zero", "uniform"), default="uniform")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    from tuppi_ai.evaluate import summarise

    t0 = time.time()
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(str(args.model),)) as pool:
        rows = list(pool.map(_measure, range(args.deals), [args.seed] * args.deals,
                             [args.scores] * args.deals, chunksize=4))
    summary = summarise(rows)
    summary.update({"model": str(args.model), "opponent": "best (TuppiAI)", "seed": args.seed,
                    "scores": args.scores, "ruleset": "project_target_v3",
                    "seconds": round(time.time() - t0, 1), "values": [r["value"] for r in rows]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "values"}, indent=1))


if __name__ == "__main__":
    main()
