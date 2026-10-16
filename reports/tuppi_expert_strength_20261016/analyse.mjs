// Local, resumable review of a fixed save. No product edits or model fitting.
import {readFile, writeFile, mkdir, rename} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {Runtime, assetsBase} from './baseline/web/runtime.mjs';
import {LocalSession} from './baseline/web/session.mjs';
import {unwrap} from './baseline/web/storage.mjs';
const directory = new URL('./', import.meta.url), source = JSON.parse(await readFile(new URL('SOURCE.json', directory)));
const bytes = await readFile(source.expert_source);
assert.equal(createHash('sha256').update(bytes).digest('hex'), source.expert_sha256);
const save = await unwrap(JSON.parse(bytes));
const read = async name => new Uint8Array(await readFile(new URL(name, assetsBase)));
const runtime = await Runtime.create({worlds: 1024, read});
assert.equal(runtime.identity, save.identity);
new LocalSession(runtime).restore(save);
const initialContext = runtime.context(); // All seats start with their deterministic original cursor/mode.
// restore above loads the saved context; analysis must use a fresh controller,
// exactly as the app's separate analysis worker does, never the end-of-match RNG.
const fresh = await Runtime.create({worlds: 1024, read});
const resetContext = fresh.context();
const decisionsURL = new URL('deals/', directory); await mkdir(decisionsURL, {recursive: true});
async function atomic(name, value) {
  const url = new URL(name, directory), temporary = new URL(name + '.tmp', directory);
  await writeFile(temporary, JSON.stringify(value, null, 2) + '\n'); await rename(temporary, url);
}
function estimate(action, choice, legal) {
  const known = legal.every(card => Number.isFinite(choice.values[card]));
  const best = known ? legal.reduce((a, b) => choice.values[b] > choice.values[a] ? b : a) : null;
  return {recommended: choice.action, searchBest: best, values: choice.values,
    recommendationGap: action === choice.action ? 0 : known ? Math.max(0, choice.values[choice.action] - choice.values[action]) : null,
    searchGap: known ? Math.max(0, choice.values[best] - choice.values[action]) : null,
    humanValue: known ? choice.values[action] : null,
    searchBestValue: known ? choice.values[best] : null,
    recommendedValue: known ? choice.values[choice.action] : null,
    milliseconds: choice.milliseconds};
}
const reports = [], started = Date.now();
for (const [index, deal] of save.completed.entries()) {
  const name = `deals/deal-${String(index + 1).padStart(2, '0')}.json`;
  let prior;
  try { prior = JSON.parse(await readFile(new URL(name, directory))); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (prior) {
    assert.equal(prior.sourceSha256, source.expert_sha256); assert.equal(prior.worlds, 1024);
    reports.push(prior); continue;
  }
  runtime.init(deal.cards, deal.dealer, deal.score); runtime.restoreContext(resetContext);
  const decisions = [], dealStarted = Date.now();
  for (const [actionIndex, action] of deal.actions.entries()) {
    const state = runtime.state();
    if (state.actor === 0) {
      const legal = runtime.legalActions(0);
      if (legal.length > 1) {
        const context = runtime.context(), hand = runtime.hand(0);
        const choice = runtime.choose(0);
        decisions.push({deal: index + 1, actionIndex, phase: state.phase, contract: state.contract,
          played: state.playedCount, trickSize: state.trickSize, soolaaja: state.soolaaja,
          leading: state.phase === 1 && state.playedCount % 4 === 0,
          human: action, legal, hand, context, ...estimate(action, choice, legal)});
      }
    }
    runtime.apply(action);
  }
  assert.deepEqual(runtime.state(), deal.result);
  assert.deepEqual(runtime.history(), deal.history);
  const report = {deal: index + 1, sourceSha256: source.expert_sha256, worlds: 1024,
    result: deal.result, decisions, seconds: (Date.now() - dealStarted) / 1000};
  await atomic(name, report); reports.push(report);
  await atomic('PROGRESS.json', {completedDeals: reports.length, totalDeals: save.completed.length,
    humanChoices: reports.reduce((n, d) => n + d.decisions.length, 0), runningSeconds: (Date.now() - started) / 1000});
  console.log(JSON.stringify({deal: index + 1, decisions: decisions.length, seconds: report.seconds}));
}
const decisions = reports.flatMap(deal => deal.decisions);
// Repeat the predeclared largest disagreements, once, at a different cursor.
const targets = decisions.filter(d => d.recommendationGap !== null && d.recommendationGap > 0)
  .sort((a, b) => b.recommendationGap - a.recommendationGap || a.deal - b.deal || a.actionIndex - b.actionIndex).slice(0, 12);
const repeats = [];
for (const target of targets) {
  const name = `deals/repeat-${target.deal}-${target.actionIndex}.json`;
  let repeat;
  try { repeat = JSON.parse(await readFile(new URL(name, directory))); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (!repeat) {
    const deal = save.completed[target.deal - 1]; runtime.init(deal.cards, deal.dealer, deal.score);
    deal.actions.slice(0, target.actionIndex).forEach(action => runtime.apply(action));
    const context = structuredClone(target.context);
    context[0][0] = (context[0][0] ^ 0xa5a5a5a5) >>> 0;
    context[0][1] = (context[0][1] ^ 0x9e3779b9) >>> 0;
    runtime.restoreContext(context);
    repeat = {deal: target.deal, actionIndex: target.actionIndex, sourceSha256: source.expert_sha256,
      human: target.human, context, ...estimate(target.human, runtime.choose(0), target.legal)};
    await atomic(name, repeat);
  }
  repeats.push(repeat);
}
const grade = gap => gap === null ? 'unscored' : gap < 0.01 ? 'withinNoise' : gap < 0.04 ? 'moderateDisagreement' : 'largeDisagreement';
function aggregate(rows) {
  const known = rows.filter(d => d.recommendationGap !== null), gaps = known.map(d => d.recommendationGap).sort((a, b) => a - b);
  const searchKnown = rows.filter(d => d.searchGap !== null);
  return {choices: rows.length, scored: known.length, exactAgreement: rows.filter(d => d.human === d.recommended).length,
    grades: Object.fromEntries(['withinNoise', 'moderateDisagreement', 'largeDisagreement', 'unscored'].map(g => [g, rows.filter(d => grade(d.recommendationGap) === g).length])),
    meanRecommendationGap: known.length ? gaps.reduce((a, b) => a + b) / known.length : null,
    medianRecommendationGap: gaps.length ? gaps[Math.floor(gaps.length / 2)] : null,
    meanSearchGap: searchKnown.length ? searchKnown.reduce((n, d) => n + d.searchGap, 0) / searchKnown.length : null};
}
const result = {sourceSha256: source.expert_sha256, originalIdentity: save.identity, worlds: 1024,
  completedDeals: reports.length, totalHumanActions: 506, analysisChoices: decisions.length,
  overall: aggregate(decisions), bidding: aggregate(decisions.filter(d => d.phase === 0)),
  normalPlay: aggregate(decisions.filter(d => d.phase === 1)),
  noloPlay: aggregate(decisions.filter(d => d.phase === 1 && d.contract === 0)),
  ramiPlay: aggregate(decisions.filter(d => d.phase === 1 && d.contract === 1)),
  leading: aggregate(decisions.filter(d => d.leading)), following: aggregate(decisions.filter(d => d.phase === 1 && !d.leading)),
  sooli: aggregate(decisions.filter(d => d.phase >= 3)), repeats,
  largestDisagreements: targets.map(d => ({...d, repeat: repeats.find(r => r.deal === d.deal && r.actionIndex === d.actionIndex)})),
  sourceUnchanged: createHash('sha256').update(await readFile(source.expert_source)).digest('hex') === source.expert_sha256,
  interpretation: 'One incomplete human-plus-bot vs two-bot match. Search estimates use actor-local information and the incumbent rollout model. Agreement and estimated gaps are not a validated human rating or causal strength difference. Replicated cases were selected for high initial gaps.'};
await atomic('ANALYSIS.json', result);
console.log(JSON.stringify({completed: true, choices: decisions.length, overall: result.overall, bidding: result.bidding, normalPlay: result.normalPlay, repeats: repeats.length}));
