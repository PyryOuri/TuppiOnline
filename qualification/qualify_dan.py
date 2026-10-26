"""Actual hosted Dan worker, accepted-action checkpoints and fixed NOLO parity."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'engine/src'), str(root / 'ai')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-torch', action='store_true')
    parser.add_argument('--require-host-limits', action='store_true')
    parser.add_argument('--reference', type=Path, default=root / 'qualification/dan-reference.json')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.no_torch:
        assert importlib.util.find_spec('torch') is None
    if args.require_host_limits:
        cgroup = Path('/sys/fs/cgroup')
        assert (cgroup / 'cpu.max').read_text().split() == ['50000', '100000']
        assert int((cgroup / 'memory.max').read_text()) == 512 * 2**20
        assert int((cgroup / 'memory.swap.max').read_text()) == 0
    from tuppi_server import hosted_bot
    from tuppi_ai.bridge import action_id
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_rules import Contract, MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK, card_to_index
    cards_by_id = {card_to_index(card): card for card in FULL_DECK}
    reference = json.loads(args.reference.read_text())
    rows = []
    try:
        for case in reference['cases']:
            state = begin_explicit_deal(create_match(initial_score=MatchScore(*case['score']),
                initial_dealer=case['dealer'], match_ref='dan-product-fixture', ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=case['dealer'], hands=tuple(tuple(cards_by_id[c] for c in case['cards'][s*13:(s+1)*13]) for s in range(4))))
            while state.phase.name == 'SHOWING':
                observation = match_observation_for(state, state.current_actor)
                state = apply_match_action(state, next(a for a in observation.legal_actions if a.declared_contract is Contract.NOLO))
            for action in case['actions']:
                observation = match_observation_for(state, state.current_actor)
                state = apply_match_action(state, next(a for a in observation.legal_actions if action_id(a) == action))
            observation = match_observation_for(state, case['seat'])
            agent = hosted_bot.HostedDanAgent(case['seat'])
            before = agent.checkpoint()
            action = agent.choose_action(observation)
            assert action_id(action) == case['action']
            assert agent.checkpoint() == before, 'proposal must not spend the ledger'
            assert agent.choose_action(observation) == action
            apply_match_action(state, action)
            agent.commit_accepted_action(action)
            saved = agent.checkpoint()
            actual = saved['controller']['state']
            for key in ('base_rng', 'eval_rng', 'remaining', 'revision'):
                assert actual[key] == case['after'][key], (key, actual, case['after'])
            restored = hosted_bot.HostedDanAgent(case['seat'])
            restored.restore(json.loads(json.dumps(saved)))
            assert restored.checkpoint() == saved
            assert restored.choose_action(observation) == action  # committed receipt is idempotent
            restored.commit_accepted_action(action)
            assert restored.checkpoint() == saved
            rows.append({'seed': case['seed'], 'action': case['action'], **agent.last_stats})
        assert 'torch' not in sys.modules
    finally:
        hosted_bot.shutdown()
    report = {'passed': True, 'cases': rows, 'accepted_action_only': True, 'restore_exact': True,
              'torch_imported': False, 'scope': 'fixed product correctness; no strength or provider claim'}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
