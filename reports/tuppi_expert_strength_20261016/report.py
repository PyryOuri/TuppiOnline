"""Summarise the local expert review after the predeclared analysis completes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median

root = Path(__file__).resolve().parent
source = json.loads((root / 'SOURCE.json').read_text())
save_bytes = Path(source['expert_source']).read_bytes()
assert hashlib.sha256(save_bytes).hexdigest() == source['expert_sha256']
save = json.loads(save_bytes)['save']
analysis = json.loads((root / 'ANALYSIS.json').read_text())
assert analysis['completedDeals'] == len(save['completed']) == 36
decisions = [d for p in sorted((root / 'deals').glob('deal-*.json'))
             for d in json.loads(p.read_text())['decisions']]
assert len(decisions) == analysis['analysisChoices']
assert analysis['sourceUnchanged']
for name, expected in source['baseline_files'].items():
    assert hashlib.sha256((root / 'baseline' / name).read_bytes()).hexdigest() == expected


def card(value):
    return f"{['2','3','4','5','6','7','8','9','10','J','Q','K','A'][value % 13]}{'♥♦♣♠'[value // 13]}"


def action(value):
    if value == 156:
        return 'Decline sooli'
    if value == 157:
        return 'Accept sooli'
    if value >= 158:
        return 'Exchange ' + card(value - 158)
    if value >= 52:
        return ('RAMI ' if value >= 104 else 'NOLO ') + card(value % 52)
    return card(value)


def where(d):
    if d['phase'] == 0:
        return 'Bidding'
    if d['phase'] == 3:
        return 'Sooli offer'
    if d['phase'] in (4, 5):
        return 'Sooli exchange'
    return f"{'RAMI' if d['contract'] else 'NOLO'} trick {d['played'] // d['trickSize'] + 1}"


def pct(n, denominator):
    return f'{100 * n / denominator:.1f}%' if denominator else 'n/a'


contracts = Counter('SOOLI' if d['result']['soolaaja'] >= 0 else
                    'RAMI' if d['result']['contract'] else 'NOLO'
                    for d in save['completed'])
wins = Counter('human_team' if d['result']['winnerTeam'] == 0 else 'opponents'
               for d in save['completed'])
rows = ['| Contract | Deals | Human + bot won | Two bots won |', '|---|---:|---:|---:|']
for contract, count in contracts.items():
    ds = [d for d in save['completed'] if ('SOOLI' if d['result']['soolaaja'] >= 0 else
          'RAMI' if d['result']['contract'] else 'NOLO') == contract]
    won = sum(d['result']['winnerTeam'] == 0 for d in ds)
    rows.append(f'| {contract} | {count} | {won} | {count - won} |')

comparison = ['| Decisions | Choices | Exact recommendation | Gap <0.01 | Gap 0.01–<0.04 | Gap ≥0.04 | Unscored |',
              '|---|---:|---:|---:|---:|---:|---:|']
for label, key in [('All', 'overall'), ('Recorded bids', 'bidding'), ('Ordinary card play', 'normalPlay'),
                   ('NOLO card play', 'noloPlay'), ('RAMI card play', 'ramiPlay'), ('Leading', 'leading'),
                   ('Following/discarding', 'following'), ('Sooli', 'sooli')]:
    a = analysis[key]
    g = a['grades']
    comparison.append(f"| {label} | {a['choices']} | {a['exactAgreement']} | {g['withinNoise']} | "
                      f"{g['moderateDisagreement']} | {g['largeDisagreement']} | {g['unscored']} |")

examples = ['| Deal | Decision | Expert played | Bot recommended | Initial gap | Second-seed gap |',
            '|---|---|---|---|---:|---:|']
for d in analysis['largestDisagreements']:
    repeat = d['repeat']
    examples.append(f"| {d['deal']} | {where(d)} | {action(d['human'])} | {action(d['recommended'])} | "
                    f"{d['recommendationGap']:.4f} | {repeat['recommendationGap']:.4f} |")

stable_moderate = sum(d['recommendationGap'] >= .01 and d['repeat']['recommendationGap'] >= .01
                      for d in analysis['largestDisagreements'])
stable_large = sum(d['recommendationGap'] >= .04 and d['repeat']['recommendationGap'] >= .04
                   for d in analysis['largestDisagreements'])
bid_decisions = analysis['bidding']['choices']
overall = analysis['overall']
known = overall['scored']
scored_decisions = [d for d in decisions if d['humanValue'] is not None]
human_above_anchor = sum(d['humanValue'] > d['recommendedValue'] for d in scored_decisions)
signed_gap = sum(d['recommendedValue'] - d['humanValue'] for d in scored_decisions) / len(scored_decisions)
contract_disagreements = [d for d in decisions if d['phase'] == 0 and (d['human'] >= 104) != (d['recommended'] >= 104)]
text = f'''# Expert Tuppi save: strength review

The human's team won **{wins['human_team']} of 36 completed deals
({pct(wins['human_team'], 36)})**, with a 1024-world bot partner against two
1024-world bots. This is a competitive result in this record. It does not
establish whether the human or the bot is stronger overall.

The file contains **one unfinished match**, not 36 completed matches. Neither
side reached 52; both had 0 points after deal 36, and the 37th deal is under
way. The human's team reached 48 earlier, and the opponents 44. Rising-score
resets explain why 21 deal wins do not mean a match win.

The bot level here is offline full search (1024 worlds). Hosted lite play
needs its own human-game records before making the same comparison.

## Recorded outcomes

{chr(10).join(rows)}

These are descriptive results on the dealt cards. The human's bot partner
contributes to them, and there are no duplicated/swapped-hand trials. Raw
tricks or adding deal points is not the match objective.

## Decision review with the original full-search bot

All 36 deals and the current position passed backup-digest and exact replay
checks. The frozen browser source is `9f28aa9`; the original WASM, models,
rules and runtime identity match the save. Every non-forced recorded human
choice was evaluated at **1024 worlds**, from the human's own information at
that turn. No other player's hidden hand or unrevealed bid entered the
decision. The 37th deal was excluded from the strength aggregates.

{chr(10).join(comparison)}

Of {known} scored choices, **{overall['grades']['withinNoise']} ({pct(overall['grades']['withinNoise'], known)})**
were less than 0.01 below the incumbent bot's recommendation. Exact card
agreement was {overall['exactAgreement']} of {overall['choices']} choices
({pct(overall['exactAgreement'], overall['choices'])}). Different cards often
have the same value, so agreement alone understates how often their decisions
were effectively equivalent under this search.

The mean recommendation gap was {overall['meanRecommendationGap']:.5f}; the
median was {overall['medianRecommendationGap']:.5f}. These are **model-estimated
match-value differences**, not observed lost wins, Elo, or an additive
estimate of the player's match win probability.

The policy anchor sometimes deliberately keeps a card below the maximum
searched value. `ANALYSIS.json` also records gaps from that maximum, rather
than disguising all such cases as perfect searched play. The recommendation
gap categories above are the app's existing cutoffs, not newly validated
human-strength thresholds. Small estimates have sampling noise.

Search selects from noisy estimates and models the continuations with its
rollout policies. A repeated disagreement can reflect a human error or a
limitation of those assumptions. It must be reviewed in its game context.

In {human_above_anchor} decisions, the expert's card actually had a higher
searched value than the anchored recommendation. The signed mean difference
(recommendation minus human, allowing negative values) was {signed_gap:.5f}.
That does not prove the anchor was wrong either: it intentionally trades off
the sampled search against the learned policy.

Only **{bid_decisions} recorded bids** could be evaluated. Bids locked by the
human but never revealed after an earlier RAMI are not retained as actions
in this save. It cannot establish the human's overall RAMI bidding rate or
judge all their bid decisions.

Among the recorded bids, {len(contract_disagreements)} recommendations
disagreed on NOLO versus RAMI; other bid disagreements concerned the shown
card within the same contract. These should be reviewed separately.

## Largest disagreements and a second search seed

The 12 largest initial recommendation gaps were selected before repeating
them with a second deterministic seed. They are deliberately selected cases,
not an independent strength sample.

{chr(10).join(examples)}

Among these selected cases, {stable_moderate} remained at least 0.01 below
the second seed's recommendation; {stable_large} were at least 0.04 below
in both searches. The second seed can recommend a different card; its gap is
always measured from that seed's own recommended card.

## What this supports

- The expert can compete with this bot configuration in the recorded game.
  The win count does not show the bots dominating the human's partnership.
- Use recurring, seed-stable decision disagreements as positions for expert
  review. The bot is a comparator, not ground truth about expert strategy.
- Do not weaken or retrain the bot, or define human conventions, from these
  outcomes alone. They do not isolate partner coordination from card quality,
  card-play strength, bidding, or the rollout model's assumptions.
- To compare overall strength, collect multiple completed matches, retain the
  bot/runtime identity and level, distinguish solo-human and two-human teams,
  and report whole-match outcomes. More records from other expert players
  would help avoid learning one person's style.

The analysis uses the unchanged original bot. No training, deployment or
upload was performed, and the original file is unchanged. Partner-convention
development remains paused for discussion of this analysis; its uncommitted,
unqualified prototype is in the separate `TuppiBrowser-pre-round` worktree
and was never used to evaluate this save.

## Reproduce

```sh
/Users/pyryouri/Developer/toolchains/emsdk/node/24.19.0_64bit/bin/node audit_deliverables/tuppi_expert_strength_20261016/analyse.mjs
python3 audit_deliverables/tuppi_expert_strength_20261016/report.py
```

The analysis resumes from per-deal checkpoints. `RUN_PLAN.md` records the
scope fixed before searching; `SOURCE.json` records hashes; `ANALYSIS.json`
and `deals/` retain all evaluated choices and search values locally.
'''
(root / 'REPORT.md').write_text(text)
positions = ['# Positions for expert review', '',
             'These are the 12 largest initial model disagreements, selected before the second search seed.',
             'Only the human hand and information public at that turn are shown. Model preferences are not proof of errors.', '']
names = ['Human', 'Left opponent', 'Bot partner', 'Right opponent']
for d in analysis['largestDisagreements']:
    deal = save['completed'][d['deal'] - 1]
    positions += [f"## Deal {d['deal']}: {where(d)}", '',
                  f"Score before the deal, human team–opponents: {deal['score'][0]}–{deal['score'][1]}.",
                  f"Expert chose **{action(d['human'])}**; first search recommended **{action(d['recommended'])}** "
                  f"(estimated gap {d['recommendationGap']:.4f}). Second seed recommended "
                  f"**{action(d['repeat']['recommended'])}** (gap {d['repeat']['recommendationGap']:.4f}).", '',
                  'Human remaining hand:', '']
    for suit in range(4):
        cards = sorted((c for c in d['hand'] if c // 13 == suit), reverse=True)
        positions.append(f"- {'♥♦♣♠'[suit]}: " + (' '.join(card(c) for c in cards) or 'void'))
    if d['phase'] == 0:
        positions += ['', 'Bids are locked: no other bid is visible when choosing.']
    else:
        declarer = deal['result']['declarer']
        positions += ['', 'Contract: ' + ('RAMI, declared by ' + names[declarer] if d['contract'] else 'NOLO') + '.']
        size = d['trickSize']
        history = deal['history'][:d['played']]
        positions += ['', 'Public play before the decision (no later cards):', '']
        for start in range(0, len(history), size):
            plays = history[start:start + size]
            positions.append(f"- Trick {start // size + 1}: " + ', '.join(f"{names[p['seat']]} {card(p['card'])}" for p in plays))
        if not history:
            positions.append('- No cards played yet.')
    legal = sorted(d['legal'], key=lambda a: (-d['values'].get(str(a), float('-inf')), a))
    positions += ['', 'First-seed estimates for the legal choices:', '', '| Choice | Estimated match value |', '|---|---:|']
    positions.extend(f"| {action(a)} | {d['values'][str(a)]:.5f} |" for a in legal)
    positions += ['', 'Review question: does the expert prefer this move because of tactics, the score, '
                  'a partnership expectation, or an assumption about how the bots play?', '']
(root / 'POSITIONS.md').write_text('\n'.join(positions) + '\n')
print(json.dumps({'report': str(root / 'REPORT.md'), 'choices': len(decisions),
                  'seed_stable_at_least_001': stable_moderate,
                  'seed_stable_at_least_004': stable_large}, indent=2))
