"""Action-trace parity: the evaluated L0 (lite_agents.py over TuppiAI) against the
hosted lite bot (TuppiAI-hosted tuppi_ai.lite, no PyTorch), all four seats, same deals.

    python parity.py run --impl evaluated|hosted --deals N --out f.json
    python parity.py compare a.json b.json
"""
import hashlib, json, random, sys
from pathlib import Path


def run(impl, deals, out):
    if impl == 'evaluated':
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lite_agents import make
        agents = make('L0')
        cursor = lambda a: a.rng.value
    else:
        from tuppi_ai.lite import lite_agents
        agents = lite_agents()
        cursor = lambda a: a.rng.value
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK
    from tuppi_ai.bridge import action_id
    import tuppi_engine, tuppi_ai
    rows = []
    with trusted_transitions():
        for i in range(deals):
            rng = random.Random(f'lite-parity-v1|{i}'); cards = list(FULL_DECK); rng.shuffle(cards)
            hands = tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))
            cell = rng.randrange(25); score = (4*cell, 0) if cell <= 12 else (0, 4*(cell-12))
            state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=i % 4, match_ref='lite-parity',
                ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=i % 4, hands=hands))
            trace = []
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor; obs = match_observation_for(state, seat)
                action = agents[seat].choose_action(obs)
                trace.append([obs.phase.value, action_id(action)]); state = apply_match_action(state, action)
            rows.append({'deal': i, 'trace': trace, 'cursors': [cursor(agents[s]) for s in range(4)]})
    Path(out).write_text(json.dumps({'impl': impl, 'torch_imported': 'torch' in sys.modules,
        'tuppi_ai': tuppi_ai.__file__, 'tuppi_engine': tuppi_engine.__file__, 'rows': rows}))


def compare(a, b):
    x, y = json.loads(Path(a).read_text()), json.loads(Path(b).read_text())
    diff = [r['deal'] for r, s in zip(x['rows'], y['rows']) if r != s]
    phases = {}
    for r in x['rows']:
        for p, _ in r['trace']: phases[p] = phases.get(p, 0) + 1
    out = {'deals': len(x['rows']), 'decisions': sum(len(r['trace']) for r in x['rows']), 'phases': phases,
           'differing_deals': diff, 'identical': not diff and len(x['rows']) == len(y['rows']),
           'implementations': [{k: d[k] for k in ('impl', 'torch_imported', 'tuppi_ai', 'tuppi_engine')} for d in (x, y)]}
    print(json.dumps(out, indent=1))
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'run':
        args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
        run(args['--impl'], int(args['--deals']), args['--out'])
    else:
        Path('results/parity.json').write_text(json.dumps(compare(sys.argv[2], sys.argv[3]), indent=1))
