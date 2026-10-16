// Duplicate replay of an expert's offline deals (owner request 2026-10-16).
// Each completed deal is replayed from the same cards, dealer and score with a
// bot (the same 1024-world WASM engine the expert played against) in the
// expert's seat 0, under several seeds for all four bots. The expert's actual
// result is compared deal by deal with the bots' mean. Local only: no model is
// fitted, the bot is unchanged, nothing leaves this machine.
// Usage: node duplicate.mjs <save.json> <out dir> [seeds=8] [workers=6]
import {readFile, writeFile, appendFile} from 'node:fs/promises';
import {existsSync, readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {Worker, isMainThread, parentPort, workerData} from 'node:worker_threads';
const web = new URL('../../TuppiBrowser-round7/web/', import.meta.url);
const {Runtime, assetsBase} = await import(new URL('runtime.mjs', web));
const read = async name => new Uint8Array(await readFile(new URL(name, assetsBase)));
// The engine's match value for team 0 (as in tuppi_rules.match_transition_value).
const value = (score0, score1) => score0 >= 52 ? 1 : score1 >= 52 ? -1 : (score0 - score1) / 52;
function seedContext(base, deal, seed) {
  return base.map((row, seat) => {
    const h = createHash('sha256').update(`tuppi-duplicate-v1|${deal}|${seed}|${seat}`).digest();
    return [h.readUInt32LE(0), h.readUInt32LE(4), row[2]];
  });
}

if (!isMainThread) {
  const runtime = await Runtime.create({worlds: 1024, read}), base = runtime.context();
  parentPort.on('message', task => {
    if (!task) { process.exit(0); }
    const started = performance.now();
    runtime.init(task.cards, task.dealer, task.score);
    runtime.restoreContext(seedContext(base, task.deal, task.seed));
    const actions = [];
    for (let guard = 0; runtime.state().phase !== 2; guard++) {
      if (guard > 80) throw new Error('deal did not finish');
      const actor = runtime.state().actor, {action} = runtime.choose(actor);
      runtime.apply(action); actions.push(action);
    }
    const end = runtime.state();
    parentPort.postMessage({deal: task.deal, seed: task.seed, actions, seconds: (performance.now() - started) / 1000,
      result: {contract: end.contract, soolaaja: end.soolaaja, winnerTeam: end.winnerTeam, points: end.points,
        tricks: [end.tricks0, end.tricks1], score: [end.score0, end.score1], terminal: Boolean(end.terminal)}});
  });
  parentPort.postMessage({ready: true});
} else {
  const [savePath, out, seedsArg = '8', workersArg = '6'] = process.argv.slice(2);
  const seeds = Number(seedsArg), workers = Number(workersArg);
  const {unwrap} = await import(new URL('storage.mjs', web));
  const bytes = await readFile(savePath), save = await unwrap(JSON.parse(bytes));
  const runtime = await Runtime.create({worlds: save.worlds, read});
  assert.equal(runtime.identity, save.identity, 'The recorded original runtime');
  assert.equal(save.worlds, 1024);
  // Every recorded deal must replay exactly before anything is compared.
  const deals = save.completed.map((deal, index) => {
    runtime.init(deal.cards, deal.dealer, deal.score);
    deal.actions.forEach(action => runtime.apply(action));
    const end = runtime.state();
    assert.deepEqual(end, deal.result, `deal ${index + 1} replays`);
    return {deal: index + 1, cards: deal.cards, dealer: deal.dealer, score: deal.score,
      expert: {contract: end.contract, soolaaja: end.soolaaja, winnerTeam: end.winnerTeam, points: end.points,
        tricks: [end.tricks0, end.tricks1], score: [end.score0, end.score1], terminal: Boolean(end.terminal)}};
  });
  const checkpoint = `${out}/runs.jsonl`, done = new Set();
  if (existsSync(checkpoint)) for (const line of readFileSync(checkpoint, 'utf8').split('\n').filter(Boolean))
    done.add(`${JSON.parse(line).deal}:${JSON.parse(line).seed}`);
  const tasks = deals.flatMap(deal => Array.from({length: seeds}, (_, seed) => ({...deal, seed})))
    .filter(task => !done.has(`${task.deal}:${task.seed}`));
  console.log(JSON.stringify({deals: deals.length, seeds, todo: tasks.length, already: done.size,
    sha256: createHash('sha256').update(bytes).digest('hex')}));
  await writeFile(`${out}/deals.json`, JSON.stringify({source: savePath, sha256: createHash('sha256').update(bytes).digest('hex'),
    identity: save.identity, worlds: save.worlds, deals: deals.map(({cards, ...rest}) => rest)}, null, 1));
  let finished = 0;
  await Promise.all(Array.from({length: Math.min(workers, tasks.length)}, () => new Promise((resolve, reject) => {
    const worker = new Worker(new URL(import.meta.url));
    const next = () => { const task = tasks.shift(); worker.postMessage(task ? {deal: task.deal, seed: task.seed, cards: task.cards,
      dealer: task.dealer, score: task.score} : null); if (!task) resolve(); };
    worker.on('message', async message => {
      if (!message.ready) {
        await appendFile(checkpoint, JSON.stringify(message) + '\n'); finished++;
        if (finished % 12 === 0) console.log(JSON.stringify({finished, remaining: tasks.length, lastSeconds: Number(message.seconds.toFixed(1))}));
      }
      next();
    });
    worker.on('error', reject);
  })));
  console.log(JSON.stringify({finished}));
}
