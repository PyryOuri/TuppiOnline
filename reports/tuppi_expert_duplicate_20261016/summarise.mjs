// Summarise the duplicate replay (duplicate.mjs). Per deal: the expert's actual
// result against the mean of the all-bot replays from the same position.
// Primary measure: the change in the engine's match value for team 0 (the
// expert's team), V = lead/52, +-1 at 52. Also deal wins and signed points.
// Control: the same statistic between two halves of the bot seeds (noise floor).
import {readFile, writeFile} from 'node:fs/promises';
const [dir] = process.argv.slice(2);
const web = new URL('../../TuppiBrowser-round7/web/', import.meta.url);
const {Runtime, assetsBase} = await import(new URL('runtime.mjs', web));
const runtime = await Runtime.create({worlds: 128, read: async name => new Uint8Array(await readFile(new URL(name, assetsBase)))});
const meta = JSON.parse(await readFile(`${dir}/deals.json`, 'utf8'));
const {unwrap} = await import(new URL('storage.mjs', web));
const save = await unwrap(JSON.parse(await readFile(meta.source)));
const runs = (await readFile(`${dir}/runs.jsonl`, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
const V = ([a, b]) => a >= 52 ? 1 : b >= 52 ? -1 : (a - b) / 52;
const signed = r => r.winnerTeam === 0 ? r.points : -r.points;
// Who declared what: replay the actions without search.
function declaration(deal, actions) {
  runtime.init(deal.cards, deal.dealer, deal.score);
  const shows = [];
  for (const action of actions) {
    const state = runtime.state();
    if (state.phase === 0) shows.push({seat: state.actor, rami: action >= 104});
    runtime.apply(action);
  }
  const end = runtime.state();
  return {declarer: end.declarer, team0Rami: end.contract === 1 && end.declarer % 2 === 0 && end.soolaaja < 0,
    team1Rami: end.contract === 1 && end.declarer % 2 === 1 && end.soolaaja < 0, sooli: end.soolaaja >= 0,
    seat0Bid: shows.find(show => show.seat === 0) ?? null};
}
const rows = meta.deals.map(deal => {
  const cards = save.completed[deal.deal - 1];
  const mine = runs.filter(run => run.deal === deal.deal).sort((a, b) => a.seed - b.seed);
  const before = V(deal.score), expert = V(deal.expert.score) - before;
  const bots = mine.map(run => V(run.result.score) - before);
  const mean = values => values.reduce((s, v) => s + v, 0) / values.length;
  const half = Math.floor(bots.length / 2);
  const expertDecl = declaration(cards, cards.actions), botDecl = mine.map(run => declaration(cards, run.actions));
  return {deal: deal.deal, scoreBefore: deal.score, runs: mine.length,
    expert: {delta: expert, won: deal.expert.winnerTeam === 0, points: signed(deal.expert), ...expertDecl},
    bots: {delta: mean(bots), sd: Math.sqrt(mean(bots.map(v => (v - mean(bots)) ** 2))), won: mean(mine.map(run => +(run.result.winnerTeam === 0))),
      points: mean(mine.map(run => signed(run.result))), team0Rami: mean(botDecl.map(d => +d.team0Rami)),
      seat0Rami: mean(botDecl.map(d => +(d.seat0Bid?.rami ?? false)))},
    difference: expert - mean(bots),
    control: half ? mean(bots.slice(0, half)) - mean(bots.slice(half)) : null};
}).filter(row => row.runs > 0);
const mean = values => values.reduce((s, v) => s + v, 0) / values.length;
let seed = 20261016; const random = () => (seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32;
function bootstrap(values, n = 20000) {
  const means = Array.from({length: n}, () => mean(Array.from(values, () => values[Math.floor(random() * values.length)]))).sort((a, b) => a - b);
  return [means[Math.floor(0.025 * n)], means[Math.floor(0.975 * n)]];
}
const diffs = rows.map(row => row.difference), control = rows.map(row => row.control).filter(v => v !== null);
const summary = {deals: rows.length, runs: runs.length, seedsPerDeal: Math.min(...rows.map(row => row.runs)),
  matchValue: {expertMeanDelta: mean(rows.map(r => r.expert.delta)), botMeanDelta: mean(rows.map(r => r.bots.delta)),
    meanDifference: mean(diffs), ci95: bootstrap(diffs), expertBetterDeals: diffs.filter(d => d > 1e-9).length,
    botBetterDeals: diffs.filter(d => d < -1e-9).length, equalDeals: diffs.filter(d => Math.abs(d) <= 1e-9).length},
  noiseFloor: {halfVsHalfMean: mean(control), ci95: bootstrap(control), meanAbs: mean(control.map(Math.abs))},
  dealWins: {expert: rows.filter(r => r.expert.won).length, botsExpected: mean(rows.map(r => r.bots.won)) * rows.length},
  signedPoints: {expert: mean(rows.map(r => r.expert.points)), bots: mean(rows.map(r => r.bots.points))},
  rami: {expertTeamRamiDeals: rows.filter(r => r.expert.team0Rami).length, botTeamRamiDealsExpected: mean(rows.map(r => r.bots.team0Rami)) * rows.length,
    expertSeat0RamiBids: rows.filter(r => r.expert.seat0Bid?.rami).length, botSeat0RamiBidsExpected: mean(rows.map(r => r.bots.seat0Rami)) * rows.length,
    expertSeat0Bids: rows.filter(r => r.expert.seat0Bid).length}};
const largest = [...rows].sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference)).slice(0, 10)
  .map(r => ({deal: r.deal, scoreBefore: r.scoreBefore, difference: Number(r.difference.toFixed(3)), expert: r.expert, bots: r.bots}));
await writeFile(`${dir}/SUMMARY.json`, JSON.stringify({summary, largest, rows}, null, 1));
console.log(JSON.stringify(summary, null, 1));
