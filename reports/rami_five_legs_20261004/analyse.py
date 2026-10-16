"""Summarize frozen runs. Ratios/conditional outcomes cluster by original deal."""
from __future__ import annotations

import collections
import hashlib
import json
import math
import statistics as st
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def read(name): return json.loads((HERE/name).read_text())


def interval(values):
    x=list(map(float,values));n=len(x)
    if not n:return {"n":0}
    mu=st.mean(x);se=st.stdev(x)/math.sqrt(n) if n>1 else 0.
    return {"n":n,"mean":mu,"se":se,"ci95":[mu-1.96*se,mu+1.96*se]}


def clustered_ratio(rows,numerator,denominator=lambda r:1):
    counts=collections.defaultdict(lambda:[0.,0.])
    probability=True
    for r in rows:
        value=numerator(r);weight=denominator(r)
        probability &= isinstance(value,bool) and weight==1
        counts[r['deal']][0]+=float(value);counts[r['deal']][1]+=float(weight)
    n=len(counts);num=sum(x[0] for x in counts.values());den=sum(x[1] for x in counts.values())
    if not den:return {"n":0}
    mu=num/den;avg_den=den/n
    influences=[(a-mu*b)/avg_den for a,b in counts.values()]
    se=st.stdev(influences)/math.sqrt(n) if n>1 else 0.
    lo,hi=mu-1.96*se,mu+1.96*se
    if probability:
        # Conservative Wilson safeguard with one trial per independent deal.
        # Avoid zero-width intervals for small groups with all successes/failures.
        z2=1.96**2;center=(mu+z2/(2*n))/(1+z2/n)
        half=1.96*math.sqrt(mu*(1-mu)/n+z2/(4*n*n))/(1+z2/n)
        lo=max(0.,min(lo,center-half));hi=min(1.,max(hi,center+half))
    return {"n":len(rows),"clusters":n,"mean":mu,"se":se,"ci95":[lo,hi]}


def branch_stats(pairs):
    if not pairs:return {"n":0}
    rows=[]
    for b in pairs:
        r,n=b['RAMI'],b['NOLO']
        rows.append({'deal':r['deal'],'difference':r['equity']-n['equity'],
            'rami_won':r['won'],'pass_won':n['won'],'rami_points':r['points'],
            'pass_points':n['points'],'pass_rami':n['contract']=='RAMI'})
    return {"n":len(rows),"rami_win":clustered_ratio(rows,lambda r:r['rami_won']),
        "pass_win":clustered_ratio(rows,lambda r:r['pass_won']),
        "rami_points":clustered_ratio(rows,lambda r:r['rami_points']),
        "pass_points":clustered_ratio(rows,lambda r:r['pass_points']),
        "rami_minus_pass_equity":clustered_ratio(rows,lambda r:r['difference']),
        "pass_becomes_rami":clustered_ratio(rows,lambda r:r['pass_rami'])}


def card_suits(mask):
    ranks=['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    return {s:' '.join(ranks[i] for i in range(12,-1,-1) if mask&(1<<(13*k+i))) or '—'
            for k,s in enumerate(['♥','♦','♣','♠'])}


def main():
    bids=read('policy_bids.json')['rows'];games=read('policy_games.json')
    qualified=[r for r in bids if r['rule_rami']]
    by_count=[]
    for n in [5,6,7,8]:
        group=[r for r in qualified if r['supported']==n or (n==8 and r['supported']>8)]
        by_count.append({'count':str(n) if n<8 else '8+', 'n':len(group),
            'policy_rami':clustered_ratio(group,lambda r:r['policy_rami'])})
    pairs={}
    for r in read('policy_branches.json')['rows']:
        pairs.setdefault((r['deal'],r['position']),{})[r['forced_bid']]=r
    for b in pairs.values():assert set(b)=={'RAMI','NOLO'}
    by_branch_count={}
    for label,condition in [('all',lambda r:True),('policy_passes',lambda r:not r['policy_rami']),
            ('policy_rami',lambda r:r['policy_rami']),('5',lambda r:r['supported']==5),
            ('6',lambda r:r['supported']==6),('7',lambda r:r['supported']==7),('8+',lambda r:r['supported']>=8)]:
        by_branch_count[label]=branch_stats([b for b in pairs.values() if condition(b['RAMI'])])
    for row in by_count:row['branches']=by_branch_count[row['count']]
    game_metrics={}
    for arm,name in [(0,'baseline'),(1,'rami_trigger'),(2,'full_rule')]:
        g=[r for r in games['rows'] if r['arm']==arm]
        game_metrics[name]={'games':len(g),'win_rate':st.mean(r['won'] for r in g),
            'points':st.mean(r['points'] for r in g),'rami_deal_rate':st.mean(r['contract']=='RAMI' for r in g),
            'changed_bids':sum(r['changed_bids'] for r in g)}
    # The VRPO3-versus-itself reference must cancel in BOTH assignments on every base deal.
    baseline_by_deal=collections.defaultdict(list)
    for r in games['rows']:
        if r['arm']==0:baseline_by_deal[r['deal']].append(r['equity'])
    baseline_max=max(abs(st.mean(x)) for x in baseline_by_deal.values())
    assert baseline_max<1e-10
    searches={}
    pop_weights={(k,f):sum(r['position']==k and r['rule_rami']==f for r in bids)/len(bids)
                 for k in range(4) for f in [False,True]}
    for worlds in [128,1024]:
        data=read(f'search_bids_w{worlds}.json');rows=data['rows'];assert len(rows)==data['requested']
        g=[r for r in rows if r['rule_rami']]
        neg=[r for r in rows if not r['rule_rami']]
        same_deal_multiple=len(rows)-len({r['deal'] for r in rows})
        standard_agreement=standard_bid=standard_value=0.
        strata=[]
        for k in range(4):
            for flag in [False,True]:
                group=[r for r in rows if r['position']==k and r['rule_rami']==flag]
                assert group
                w=pop_weights[k,flag]
                agree=st.mean(r['search_rami']==r['rule_rami'] for r in group)
                rate=st.mean(r['search_rami'] for r in group)
                standard_agreement+=w*agree;standard_bid+=w*rate
                standard_value+=w*st.mean(r['rule_value_minus_bot_value'] for r in group)
                strata.append({'position':k,'qualified':flag,'n':len(group),'population_weight':w,
                               'search_rami':rate,'agreement':agree})
        count_rows=[]
        for n in [5,6,7,8]:
            group=[r for r in g if r['supported']==n or (n==8 and r['supported']>8)]
            count_rows.append({'count':str(n) if n<8 else '8+','n':len(group),
                              'search_rami':clustered_ratio(group,lambda r:r['search_rami'])})
        searches[str(worlds)]={'bids':len(rows),'qualified':len(g),'seconds':data['seconds'],
            'qualified_search_rami':clustered_ratio(g,lambda r:r['search_rami']),
            'unqualified_search_rami':clustered_ratio(neg,lambda r:r['search_rami']),
            'standardized_agreement':standard_agreement,'standardized_rami_rate':standard_bid,
            'standardized_rule_value_minus_bot_value':standard_value,
            'mean_qualified_rami_minus_nolo_search_value':st.mean(r['rami_minus_nolo_searched'] for r in g),
            'qualified_contract_trigger_minus_bot_model_value':st.mean(
                r['rule_value_minus_bot_value'] if not r['search_rami'] else 0. for r in g),
            'overridden_qualified_bids':sum(not r['search_rami'] for r in g),
            'mean_override_model_value_difference':st.mean(
                r['rule_value_minus_bot_value'] for r in g if not r['search_rami']),
            'extra_bids_on_repeated_deals':same_deal_multiple,'by_count':count_rows,'strata':strata}
    final_rows=read('search_bids_w1024.json')['rows']
    bad=[r for r in final_rows if r['rule_rami'] and not r['search_rami'] and r['rami_minus_nolo_searched']<-.02]
    bad.sort(key=lambda r:r['rami_minus_nolo_searched'])
    examples=[]
    # One ordinary exactly-five example in early position; no claim this is representative.
    filtered=[r for r in bad if r['supported']==5 and r['position'] in (0,1) and not r['policy_rami']]
    for r in filtered[:2]:
        examples.append({'deal':r['deal'],'position':r['position'],'supported':r['supported'],
            'suit_counts':r['by_suit'],'hand':card_suits(r['hand_mask']),
            'rami_minus_nolo_searched':r['rami_minus_nolo_searched'],
            'policy_rami':r['policy_rami'],'search_rami':r['search_rami']})
    hashes=read('SOURCE_HASHES.json')
    hash_status={str(p):hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==expected for p,expected in hashes.items()}
    assert all(hash_status.values())
    results={'population':{'deals':8192,'bids':len(bids),'qualified':len(qualified),
        'qualified_rate':clustered_ratio(bids,lambda r:r['rule_rami']),
        'qualified_policy_rami':clustered_ratio(qualified,lambda r:r['policy_rami']),
        'agreement':clustered_ratio(bids,lambda r:r['rule_rami']==r['policy_rami']),
        'by_count':by_count,'by_position':[{'position':k,'n':len(g),
            'policy_rami':clustered_ratio(g,lambda r:r['policy_rami'])}
            for k in range(4) if (g:=[r for r in qualified if r['position']==k])]},
        'duplicate':{k:v for k,v in games.items() if k not in ['rows','base_differences']},
        'game_metrics':game_metrics,'branches':by_branch_count,'search':searches,'counterexamples':examples,
        'integrity':{'baseline_max_absolute_equity_per_base':baseline_max,'source_hashes_unchanged':hash_status},
        'validation':read('validation.json')}
    (HERE/'RESULTS.json').write_text(json.dumps(results,indent=2))
    pct=lambda x:f'{100*x:.1f}%'
    ci=lambda x:f"{x['mean']:+.5f} [{x['ci95'][0]:+.5f}, {x['ci95'][1]:+.5f}]"
    search=searches['1024'];trigger=games['trigger_minus_policy_equity'];full=games['full_rule_minus_policy_equity']
    report=f'''# Five supported cards across three suits: RAMI at 0-0

Research completed 2026-10-04. **Useful strength signal, too broad as an automatic
RAMI trigger.** The current W1024 search bot bids RAMI on
{pct(search['qualified_search_rami']['mean'])} of qualifying hands in the stratified
confirmation. Forcing RAMI whenever the condition qualifies changes equity by
{ci(trigger)} estimated match equity per deal against the strongest available
fast policy (VRPO3), with identical card play. The interval excludes zero.

## The owner's confirmed idea

A card has enough *legs* when it has enough other cards of its suit to support
its rank: A needs 0, K 1, Q 2, J 3, 10 4, and so on. Higher cards count as legs
too; support can be shared. For suit length L and rank r, qualify the card when
**L-1 >= 14-r**. Count at least five qualifying cards, with qualifying cards
in at least three different suits. This is a count of prospective winners,
not guaranteed tricks. AK counts 2, KQx 2, Qxx 1, AKQJ 4. Qualifying cards in
three suits is stronger than merely holding cards in three suits.

The owner confirmed “at least five” and this interpretation. The primary test
is a **sufficient trigger**: force RAMI on qualifying hands, otherwise retain
the bot's decisions. A separate test examines RAMI iff the condition holds;
that complete strategy was not assumed to be the owner's intended rule.

## Bots and evidence

VRPO3 (`models/vrpo3_final.pt`) is the current strongest documented standalone
policy and the policy anchor of the current best search bot. It supplies the
large, fast outcome experiment. This is not the older heuristic bot.

The strongest bid confirmation uses `best_agents(worlds=1024)`: VRPO1 on both
rollout teams, VRPO3 anchor, .003 card margin, .03 bid margin, showing sampler
fix, six-trick exact search tail and adaptive bidding. A W128 screen precedes
it. Both use current frozen source/model/native files in SOURCE_HASHES.json;
all hashes matched after the study. Source revision was
`d518f7329c34e4a9070df806b3a5ef937cb04387` with unrelated existing changes.

All runs use project_target_v3 (blind locked bids and sooli), score 0-0.
The policy-only runs use the repository's normal policy sooli fallback, which
declines offers. The search valuations include its sooli model. Search agents
are observation-seeded and their history-sensitive sooli options are reset
to fresh-deal defaults for each isolated bid. No source, models, training,
running servers or live settings were changed.

## Agreement and the five-card boundary

8,192 independent random deals provide 32,768 blind shadow bids, all four
positions. {len(qualified):,} hands ({pct(len(qualified)/len(bids))}) qualify.
VRPO3 chooses RAMI on {pct(st.mean(r['policy_rami'] for r in qualified))} of these
hands. Overall agreement of the complete yes/no rule with VRPO3 is
{pct(st.mean(r['policy_rami']==r['rule_rami'] for r in bids))}.

| Supported cards, at least 3 qualifying suits | Fast-policy hands | VRPO3 bids RAMI | W1024 hands | W1024 bids RAMI | RAMI made in paired fast play |
|---|---:|---:|---:|---:|---:|
'''
    for a,b in zip(by_count,search['by_count']):
        report+=f"| {a['count']} | {a['n']:,} | {pct(a['policy_rami']['mean'])} | {b['n']} | {pct(b['search_rami']['mean']) if b['n'] else '—'} | {pct(a['branches']['rami_win']['mean'])} |\n"
    report+='''
Exactly five is the weak part of the rule. Six is more convincing and seven
is a strong indicator, but these are exploratory descriptions, not validated
replacement thresholds. The last rows have fewer search observations.

Position also matters. Among qualifying hands:

| Bid position | VRPO3 bids RAMI | W1024 bids RAMI |
|---|---:|---:|
'''
    names=['Forehand / 1st','2nd','3rd','Dealer / 4th']
    for k,name in enumerate(names):
        a=results['population']['by_position'][k]['policy_rami']['mean']
        b=next(s['search_rami'] for s in search['strata'] if s['qualified'] and s['position']==k)
        report+=f'| {name} | {pct(a)} | {pct(b)} |\n'
    report+=f'''
W1024 uses 1,024 shadow bids: 128 qualified and 128 unqualified per position.
Thus 512 qualified hands underpin the conditional recommendation rate
({pct(search['qualified_search_rami']['mean'])}; approximate deal-clustered
95% interval {pct(search['qualified_search_rami']['ci95'][0])}–{pct(search['qualified_search_rami']['ci95'][1])}).
The stratified sample is not half-qualified in the population. Standardizing
to the large random sample gives overall agreement
{pct(search['standardized_agreement'])}, rather than treating its raw balanced
average as a population rate. The W128 screen had 256 bids.

## What following the rule costs

2,048 independent base deals × four hand rotations × both partnership
assignments × three arms = **49,152 played games**. In every arm, VRPO3 plays
all cards; only the tested partnership's contract decisions differ. Shown
cards are VRPO3's favourite legal cards within the chosen contract. Pairing
uses identical hands/dealer/score. Intervals use independent base-deal means
over the eight duplicate legs, not 49,152 independent observations.
Proportion intervals use deal-clustered influence estimates with a conservative
Wilson safeguard, so small all-success subgroups do not imply certainty.

| Strategy versus VRPO3 bidding | Estimated match-equity difference per deal, 95% CI |
|---|---:|
| Force RAMI when condition holds; otherwise use VRPO3 | {ci(trigger)} |
| RAMI only when condition holds; otherwise NOLO | {ci(full)} |

The primary loss is about **{100*abs(trigger['mean']):.3f} percentage points of
estimated match-win probability after one deal**. This is an absolute change
in the repository's continuation-equity model. It is not a measured
full-match win-rate change, percentage of mathematical optimality, or a
claim that the same loss holds against human opponents. The equity table
comes from the incumbent continuation model. Raw points and deal wins are
also preserved in RESULTS.json.

The W1024 bot passes on {search['overridden_qualified_bids']} of the 512
qualifying bids. On those overrides, forcing RAMI with its best searched
RAMI card changes its own model value by
{search['mean_override_model_value_difference']:+.5f} on average. Leaving
its action unchanged when it already bids RAMI gives a model difference of
{search['qualified_contract_trigger_minus_bot_model_value']:+.5f} per
qualifying bid in this balanced-position sample. These are **search-model
estimates per bid**, separate from the played per-deal result above.

## RAMI versus passing on the same qualifying hand

Every qualifying shadow hand was played twice: RAMI and NOLO, with the other
bids and card play following VRPO3. Earlier seats were forced to NOLO using
their preferred NOLO cards, so these are shadow-context comparisons, not
the naturally occurring distribution after earlier bot passes. Passing may
let someone else declare RAMI. This adds **15,188 paired-branch games**.

| Qualifying group | Hands | RAMI made | Team wins after pass | RAMI minus pass equity, 95% CI |
|---|---:|---:|---:|---:|
'''
    for label,key in [('All qualifying','all'),('VRPO3 would bid RAMI','policy_rami'),('VRPO3 would pass','policy_passes'),('Exactly five supported cards','5')]:
        b=by_branch_count[key]
        report+=f"| {label} | {b['n']:,} | {pct(b['rami_win']['mean'])} | {pct(b['pass_win']['mean'])} | {ci(b['rami_minus_pass_equity'])} |\n"
    report+=f'''
On qualifying hands that VRPO3 rejects, forcing RAMI averages
{by_branch_count['policy_passes']['rami_points']['mean']:+.2f} signed points,
versus {by_branch_count['policy_passes']['pass_points']['mean']:+.2f} after passing.
This is the source of the automatic trigger's cost: the bot separates the
good qualifying hands from the weaker ones. The aggregate condition can
favour RAMI while still being an inferior automatic decision rule.

## Concrete counterexample

These examples were selected for a clear model disagreement, not to estimate
how common such hands are. Both the fast policy and W1024 choose NOLO.
'''
    for example in examples[:1]:
        hand=example['hand']
        report+=f"\n- Position: {names[example['position']]}. Hand: ♥ {hand['♥']}; ♦ {hand['♦']}; ♣ {hand['♣']}; ♠ {hand['♠']}.\n"
        report+=f"- Supported cards by suit (♥ ♦ ♣ ♠): {example['suit_counts']}; total five across three suits.\n"
        report+=f"- W1024's best RAMI-minus-NOLO searched value: {example['rami_minus_nolo_searched']:+.5f} equity.\n"
    report+='''
The count omits which higher ranks are held, missing higher cards, suit
entries and blocking, the rest of the hand's NOLO prospects, partner support,
and position. Cards with legs can become winners without providing five
usable tricks or making seven partnership tricks sufficiently likely.

## Interpretation and limits

Use the condition as a strength screen. At 0-0, exactly five supported cards
across three suits does not justify automatic RAMI; the bot rejects many such
hands. Six or seven increases its confidence, but a fixed count still misses
important hand and position information. This study does not establish a
replacement rule or mathematical optimality.

Actual paired outcomes were played with the strongest fast standalone policy,
not four W1024 search agents. W1024 confirms bidding decisions and records
model values; those values are not independent actual outcome validation.
The .03 bid anchor means the deployed search choice need not maximize its
own raw rollout mean. Adaptive search can value different discarded actions
on different numbers of worlds. Do not equate a rollout-value gap with proof
of a wrong bid or treat the bot as an oracle.

## Reproduction and artifacts

- PROTOCOL.md: original frozen design and explicitly dated follow-up.
- study.py: counting predicate, seeded deals, differential validation,
  bid samples, paired policy play and search confirmation.
- analyse.py and RESULTS.json: complete numeric summaries, cluster intervals,
  subgroup results, example hands and integrity checks.
- policy_bids.json, policy_games.json, policy_branches.json: underlying data.
- search_bids_w128.json, search_bids_w1024.json: decisions and all searched values.
- search_bids_w1024_pilot128.json: preserved initial pilot.
- SOURCE_HASHES.json and validation.json: source/model freeze and engine checks.

Run `study.py validate --n 24`, `bids --n 8192`, `games --n 2048 --chunk 64`,
`branches --chunk 256`, `search --n 256 --worlds 128`, and
`search --n 1024 --worlds 1024` with the existing tuppi-v2 Python, then
`analyse.py`. The fixed seed is `rami-five-legs-20261004-v1`.

Validation compared 24 complete v3 deals with the authoritative engine:
1,349 actions, all legal sets/actors/observation encodings/results matched;
zero native/PyTorch policy-choice disagreements. Duplicate baseline cancels
exactly against itself in both partnership assignments on every base deal.
No live deployment or GUI validation is claimed.

Source references: [best.py](../../TuppiAI/tuppi_ai/best.py),
[policies.py](../../TuppiAI/tuppi_ai/policies.py),
[equity.py](../../TuppiAI/tuppi_ai/equity.py),
[v3 rules](../../TuppiProject-current/docs/rules/project_target_v3.md),
and [policy sooli fallback](../../TuppiProject-current/src/tuppi_agents/sooli.py).
Authoritative current configuration was read from source because older status
prose describes earlier opponent models.
'''
    (HERE/'REPORT.md').write_text(report)
    print(json.dumps({'qualified_search_rami':search['qualified_search_rami'],
        'trigger_minus_policy_equity':trigger,'full_rule_minus_policy_equity':full,
        'by_count':search['by_count'],'source_hashes_unchanged':all(hash_status.values())},indent=2))


if __name__=='__main__':main()
