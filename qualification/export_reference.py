#!/usr/bin/env python3
"""Export deterministic synthetic rule and controller oracles from Python."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ai', type=Path, required=True)
parser.add_argument('--engine', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--worlds', type=int, default=128)
parser.add_argument('--trace-options', action='store_true', help='Include exact retained sooli setter state for differential checks')
parser.add_argument('--controller-scores', default='0,0;0,0', help='Two fixed input score cells, e.g. 24,0;40,0')
parser.add_argument('--timing-output', type=Path, help='Separate finite decision timings; never included in the reference trace')
args = parser.parse_args()
scores = [tuple(map(int, pair.split(','))) for pair in args.controller_scores.split(';')]
assert len(scores) == 2 and all(len(s) == 2 and all(0 <= x < 52 and x % 4 == 0 for x in s) and not all(s) for s in scores)
sys.path[:0] = [str(args.ai.resolve()), str(args.engine.resolve() / 'src')]
import numpy as np
import torch
torch.set_num_threads(1)
from tuppi_ai import native, model
from tuppi_ai.best import best_agents
from tuppi_ai.bridge import action_id, engine_action, obs_from_player_observation
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore, RulesetId, FULL_DECK, card_to_index

phase_ids = {'SHOWING': 0, 'TRICK_PLAY': 1, 'SOOLI_OFFER': 3, 'SOOLI_GIVE': 4, 'SOOLI_RETURN': 5, 'SOOLI_PLAY': 6}
counts = {}
rule_cases = []
inference_features = []
with trusted_transitions():
    for index in range(12):
        rng = random.Random(f'browser-rule-oracle-{index}')
        cards = list(FULL_DECK); rng.shuffle(cards)
        hands = tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))
        score = (4 * (index % 12), 0) if index % 2 else (0, 4 * (index % 12))
        state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=index % 4,
            match_ref=f'browser-rule-{index}', ruleset_id=RulesetId.PROJECT_TARGET_V3),
            ExplicitDeal(dealer=index % 4, hands=hands))
        case = {'cards': [card_to_index(c) for c in cards], 'dealer': index % 4, 'score': score, 'steps': []}
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            observation = match_observation_for(state, seat)
            phase = observation.phase.value
            counts[phase] = counts.get(phase, 0) + 1
            views = [obs_from_player_observation(match_observation_for(state, s)) for s in range(4)]
            features = [native.encode(view, encoder=2) for view in views]
            if len(inference_features) < 32:
                inference_features.extend(features[:min(4, 32 - len(inference_features))])
            legal = list(observation.legal_actions)
            nolo = [a for a in legal if phase == 'SHOWING' and action_id(a) < 104]
            if phase == 'SHOWING' and nolo and rng.random() < 0.55:
                action = rng.choice(nolo)
            elif phase == 'SOOLI_OFFER':
                action = legal[1] if rng.random() < 0.8 else legal[0]
            else:
                action = rng.choice(legal)
            case['steps'].append({'seat': seat, 'phase': phase_ids[phase], 'legal': [action_id(a) for a in legal],
                'features_sha256': [hashlib.sha256(f.tobytes()).hexdigest() for f in features], 'action': action_id(action)})
            state = apply_match_action(state, action)
        result = state.completed_deals[-1].public_result
        case['result'] = {'contract': 1 if result.contract.value == 'RAMI' else 0,
            'declarer': -1 if result.declarer is None else result.declarer,
            'tricks0': result.team_tricks[0], 'tricks1': result.team_tricks[1],
            'points': result.deal_score.points, 'winnerTeam': result.deal_score.winner_team.value,
            'score0': result.score_after.team0, 'score1': result.score_after.team1,
            'terminal': int(result.match_terminal)}
        rule_cases.append(case)
assert all(counts.get(phase, 0) for phase in phase_ids), counts

features = np.stack(inference_features)
inference = []
for filename in ['vrpo1_actor_0504.pt', 'vrpo3_final.pt']:
    net = model.load(args.ai / 'models' / filename, 'cpu')
    with torch.no_grad(): outputs = net(torch.from_numpy(features)).numpy()
    inference.append({'file': filename, 'outputs': outputs.tolist()})

spec = importlib.util.spec_from_file_location('reference_profile', args.ai / 'tools/profile_search.py')
profile = importlib.util.module_from_spec(spec); spec.loader.exec_module(profile)
agents = best_agents(worlds=args.worlds, seed=0)
if args.trace_options:
    for agent in agents.values():
        for searcher in (agent.searcher, agent.show_searcher):
            if searcher is None:
                continue
            env = searcher.env
            env.trace_sooli = [0, False, False, 0.0]
            original = env.set_sooli
            def traced(belief=0, return_pi=False, play_heur=False, lam=0.0, *, _env=env, _original=original):
                _original(belief, return_pi, play_heur, lam)
                _env.trace_sooli = [int(belief), bool(return_pi), bool(play_heur), float(lam)]
            env.set_sooli = traced

def options_snapshot():
    return [[None if sr is None else list(sr.env.trace_sooli) for sr in (agent.searcher, agent.show_searcher)]
            for agent in agents.values()]

timing_rows = []
def choose_action(seat, observation):
    if args.timing_output is None:
        return agents[seat].choose_action(observation)
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    action = agents[seat].choose_action(observation)
    timing_rows.append({'phase': observation.phase.value, 'cpu_ns': time.process_time_ns()-cpu,
                        'wall_ns': time.perf_counter_ns()-wall})
    return action
controller_cases = []
with trusted_transitions():
    for index in range(2):
        rng = random.Random(f'browser-controller-oracle-{index}')
        cards = list(FULL_DECK); rng.shuffle(cards)
        hands = tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))
        dealer = index % 4
        state = begin_explicit_deal(create_match(initial_score=MatchScore(*scores[index]), initial_dealer=dealer,
            match_ref=f'browser-bot-{index}', ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=dealer, hands=hands))
        profile.reseed(agents, index)
        seeds = [[agent.searcher.rng.value & 0xffffffff, agent.searcher.rng.value >> 32, 0]
                 for _, agent in sorted(agents.items())]
        case = {'cards': [card_to_index(c) for c in cards], 'dealer': dealer, 'score': list(scores[index]), 'context': seeds, 'steps': []}
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor; observation = match_observation_for(state, seat)
            action = choose_action(seat, observation)
            value = agents[seat].searcher.rng.value
            case['steps'].append({'seat': seat, 'phase': phase_ids[observation.phase.value], 'action': action_id(action),
                'values': agents[seat].last_values, 'rng': [value & 0xffffffff, value >> 32]})
            if args.trace_options:
                case['steps'][-1]['sooli_options'] = options_snapshot()
            state = apply_match_action(state, action)
        controller_cases.append(case)

forced_cases = []
test = next(case for case in rule_cases if sum(step['phase'] == 6 for step in case['steps']) >= 3)
by_index = {card_to_index(card): card for card in FULL_DECK}
hands = tuple(tuple(by_index[c] for c in test['cards'][s*13:(s+1)*13]) for s in range(4))
state = begin_explicit_deal(create_match(initial_score=MatchScore(*test['score']), initial_dealer=test['dealer'],
    match_ref='browser-forced-sooli', ruleset_id=RulesetId.PROJECT_TARGET_V3),
    ExplicitDeal(dealer=test['dealer'], hands=hands))
profile.reseed(agents, 100)
context = [[agent.searcher.rng.value & 0xffffffff, agent.searcher.rng.value >> 32, 0]
           for _, agent in sorted(agents.items())]
case = {'cards': test['cards'], 'dealer': test['dealer'], 'score': test['score'], 'context': context, 'steps': []}
probed = {4: 0, 5: 0, 6: 0}
with trusted_transitions():
    for original in test['steps']:
        observation = match_observation_for(state, state.current_actor)
        phase = phase_ids[observation.phase.value]
        step = {'seat': state.current_actor, 'phase': phase, 'apply_action': original['action']}
        if phase in probed and probed[phase] < (3 if phase == 6 else 1):
            seat = state.current_actor; action = choose_action(seat, observation)
            rng_state = agents[seat].searcher.rng.value
            step['probe'] = {'action': action_id(action), 'values': agents[seat].last_values,
                             'rng': [rng_state & 0xffffffff, rng_state >> 32]}
            if args.trace_options:
                step['probe']['sooli_options'] = options_snapshot()
            probed[phase] += 1
        case['steps'].append(step)
        state = apply_match_action(state, engine_action(original['action'], state.current_actor))
assert all(probed.values()), probed
forced_cases.append(case)

record = {'schema': 'tuppi.browser.reference.v1', 'ruleset': 'project_target_v3', 'worlds': args.worlds,
          'rule_cases': rule_cases, 'phase_counts': counts, 'controller_cases': controller_cases,
          'forced_controller_cases': forced_cases,
          'inference': {'rows': len(features), 'features_base64': base64.b64encode(features.tobytes()).decode(), 'models': inference},
          'acceptance': {'exact_rules_and_features': True, 'inference_abs_tolerance': 0.0001,
                         'controller_prices_abs_tolerance': 0.00000001, 'exact_root_actions_and_rng': True},
          'scope': 'Synthetic deterministic v3 reference cases; no personal saved games or training.'}
args.out.write_text(json.dumps(record) + '\n')
if args.timing_output is not None:
    args.timing_output.write_text(json.dumps({'worlds': args.worlds, 'controller_scores': scores,
        'decisions': timing_rows, 'scope': 'Finite fixed-input timing, not a strength or device benchmark'})+'\n')
print(json.dumps({'output': str(args.out), 'rules': len(rule_cases), 'phase_counts': counts,
                  'controller_decisions': sum(len(c['steps']) for c in controller_cases)}))
