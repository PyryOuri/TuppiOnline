"""CPU per bot-seat-deal and decision latency for one arm (PLAN.md step 1).

Same 8 deals for every arm (seed lite-cost-v1, uniform scores), all four
seats the arm, one process, one BLAS/Torch thread, rollout chunk 128.
"""
from __future__ import annotations

import argparse
import json
import random
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lite_agents import TUPPIAI, make  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument('--arm', required=True); p.add_argument('--deals', type=int, default=8)
    p.add_argument('--out', type=Path, required=True); a = p.parse_args()
    import torch
    torch.set_num_threads(1)
    from tuppi_ai import evaluate as ev, native
    native.set_rollout_chunk(128)
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK
    c0 = time.process_time(); agents = ev._with_sooli(make(a.arm), 'v3'); setup_cpu = time.process_time() - c0
    rows = []
    with trusted_transitions():
        for i in range(a.deals):
            rng = random.Random(f'lite-cost-v1|deal|{i}'); cards = list(FULL_DECK); rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            score = ev._score_for(i, 'uniform', 'lite-cost-v1')
            match = create_match(initial_score=MatchScore(*score), initial_dealer=i % 4, match_ref='lite-cost',
                                 ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=i % 4, hands=hands))
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor; obs = match_observation_for(state, seat)
                t, c = time.perf_counter(), time.process_time()
                action = agents[seat].choose_action(obs)
                rows.append({'deal': i, 'phase': obs.phase.value, 'legal': len(obs.legal_actions),
                             'cpu': time.process_time() - c, 'wall': time.perf_counter() - t})
                state = apply_match_action(state, action)
    import numpy as np
    cpu = np.array([r['cpu'] for r in rows]); wall = np.array([r['wall'] for r in rows])
    by_phase = {}
    for ph in sorted({r['phase'] for r in rows}):
        x = np.array([r['wall'] for r in rows if r['phase'] == ph])
        by_phase[ph] = {'n': len(x), 'mean_wall': float(x.mean()), 'p95_wall': float(np.percentile(x, 95)), 'max_wall': float(x.max())}
    out = {'arm': a.arm, 'deals': a.deals, 'decisions': len(rows), 'setup_cpu_seconds': setup_cpu,
           'decision_cpu_seconds': float(cpu.sum()), 'cpu_per_seat_deal': float(cpu.sum()) / (4 * a.deals),
           'p50_wall': float(np.percentile(wall, 50)), 'p95_wall': float(np.percentile(wall, 95)), 'max_wall': float(wall.max()),
           'by_phase': by_phase, 'peak_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 'rows': rows}
    with a.out.open('x') as f: json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, indent=1))


if __name__ == '__main__':
    main()
