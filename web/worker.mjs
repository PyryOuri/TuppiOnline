import {Runtime} from './runtime.mjs';
import {LocalSession, analyseDeal, shuffledDeck} from './session.mjs';
import {buildTimeline, TimelineBuilder} from './timeline.mjs';

let session, generation = 0, delay = 350, running = false, finishReveal;
let checkpointId = 0, durableCheckpoint = Promise.resolve();
const checkpoints = new Map();
const send = (type, payload) => postMessage({type, generation, ...payload});

// A separate instance of this worker analyses finished deals with the best
// bot (full search, 1024 worlds); it never plays a game.
let analysisRuntime = null, analysisContext = null, analysisQueue = Promise.resolve();
async function runAnalysis(data) {
  const report = payload => postMessage({type: 'analysis-progress', id: data.id, ...payload});
  try {
    if (!analysisRuntime) {
      analysisRuntime = await Runtime.create({worlds: 1024, progress: message => report({message})});
      analysisContext = analysisRuntime.context();
    }
    const result = analyseDeal(analysisRuntime, data.deal, data.seat, {context: analysisContext,
      stopAfterPlayed: data.stopAfterPlayed ?? 52, expectedTricks: data.expectedTricks ?? null,
      progress: (done, total) => report({done, total})});
    postMessage({type: 'analysis', id: data.id, result});
  } catch (error) { postMessage({type: 'analysis', id: data.id, error: error.message}); }
}

// A separate instance of this worker builds the game viewer's timelines
// (round 16: replays of recorded games); it never plays a game.
let viewerRuntime = null, viewerQueue = Promise.resolve();
async function runTimeline(data) {
  try {
    if (!viewerRuntime) viewerRuntime = await Runtime.create({worlds: 128,
      progress: message => postMessage({type: 'timeline-progress', id: data.id, message})});
    postMessage({type: 'timeline', id: data.id, timeline: buildTimeline(viewerRuntime, data.match)});
  } catch (error) { postMessage({type: 'timeline', id: data.id, error: error.message}); }
}

// Bot-only games for the viewer (round 16): four bots play a match to 52 on
// this device, and every move goes to the viewer as a timeline step. Each team
// has its own bot (legacy W128/W1024, Nelli 1.0, Heidi 1.0 or 1.1); a runtime per
// profile follows every move, and the actor's team runtime chooses. One game
// at a time; `delay` paces the moves and can change while it plays.
const botProfiles = {fast: {worlds: 128, bot: 'legacy'}, full: {worlds: 1024, bot: 'legacy'},
  heidi05: {worlds: 128, bot: 'heidi05'}, heidi10: {worlds: 1024, bot: 'heidi10'}, heidi11: {worlds: 1024, bot: 'heidi11'}};
// Profile -> runtime being created or ready. Each holds its own models and
// WASM memory, so only the current game's (at most two) stay loaded, and
// stopping the game releases them.
const botRuntimes = new Map();
let botGame = null;
function releaseBotRuntimes(keep = []) {
  for (const [name, created] of botRuntimes) if (!keep.includes(name)) {
    botRuntimes.delete(name);
    created.then(runtime => runtime.close(), () => {});
  }
}
async function runBotMatch(data) {
  const game = {id: data.id, stopped: false, delay: Math.max(0, Math.min(5000, data.delay ?? 1000))};
  if (botGame) botGame.stopped = true;
  botGame = game;
  const post = (type, payload) => postMessage({type, id: game.id, ...payload});
  try {
    const teams = Array.isArray(data.teams) && data.teams.length === 2 && data.teams.every(name => name in botProfiles) ? data.teams : ['fast', 'fast'];
    const names = [...new Set(teams)];
    releaseBotRuntimes(names);
    for (const name of names) if (!botRuntimes.has(name)) {
      const created = Runtime.create({...botProfiles[name], humanSeats: [], progress: message => post('botmatch-progress', {message})});
      created.catch(() => { if (botRuntimes.get(name) === created) botRuntimes.delete(name); });
      botRuntimes.set(name, created);
    }
    const runtimes = await Promise.all(names.map(name => botRuntimes.get(name)));
    // A newer game or a stop may have released these runtimes meanwhile.
    if (game.stopped) return;
    const team = teams.map(name => runtimes[names.indexOf(name)]);
    const runtime = runtimes[0], others = runtimes.slice(1), builder = new TimelineBuilder(runtime);
    // An optional starting score (tests start near the end): one side up, in fours, below 52.
    const start = data.score, valid = Array.isArray(start) && start.length === 2 && start.every(v => Number.isInteger(v) && v >= 0 && v < 52 && v % 4 === 0) && !(start[0] && start[1]);
    let score = valid ? [...start] : [0, 0], dealer = crypto.getRandomValues(new Uint8Array(1))[0] % 4;
    // An optional deal limit (tests): the match ends after that many deals.
    const limit = Number.isInteger(data.deals) && data.deals > 0 ? Math.min(data.deals, 500) : 500;
    for (let d = 0; d < limit && !game.stopped; d++) {
      const deal = {cards: shuffledDeck(), dealer, score: [...score], actions: []};
      for (const r of runtimes) r.init(deal.cards, dealer, score);
      post('botmatch-step', {step: builder.beginDeal(deal), info: builder.deals.at(-1), deal: {cards: deal.cards, dealer, score: [...score]}});
      while (!game.stopped && runtime.state().phase !== 2) {
        await new Promise(resolve => setTimeout(resolve, game.delay));
        if (game.stopped) break;
        const actor = runtime.state().actor, {action} = team[actor % 2].choose(actor);
        post('botmatch-step', {step: builder.step(action, 'bot'), info: builder.deals.at(-1)});
        for (const r of others) r.apply(action);
      }
      if (game.stopped) break;
      score = builder.deals.at(-1).result.scoreAfter; dealer = (dealer + 1) % 4;
      if (score[0] >= 52 || score[1] >= 52 || d === limit - 1) { post('botmatch-end', {score}); break; }
      await new Promise(resolve => setTimeout(resolve, game.delay * 2));
    }
  } catch (error) { post('botmatch-error', {error: error.message}); }
  finally { if (botGame === game) botGame = null; }
}

self.onmessage = async ({data}) => {
  if (data.type === 'analyse') { analysisQueue = analysisQueue.then(() => runAnalysis(data)); return; }
  if (data.type === 'botmatch-start') { runBotMatch(data); return; }
  if (data.type === 'botmatch-delay') { if (botGame?.id === data.id && Number.isFinite(data.delay)) botGame.delay = Math.max(0, Math.min(5000, data.delay)); return; }
  if (data.type === 'botmatch-stop') {
    if (botGame?.id === data.id) botGame.stopped = true;
    if (!botGame || botGame.stopped) releaseBotRuntimes();
    return;
  }
  if (data.type === 'timeline') { viewerQueue = viewerQueue.then(() => runTimeline(data)); return; }
  if (data.type === 'checkpoint-saved' && data.generation === generation) {
    const pending = checkpoints.get(data.checkpointId);
    if (pending) { checkpoints.delete(data.checkpointId); data.error ? pending.reject(new Error(`Tallennus keskeytyi: ${data.error}`)) : pending.resolve(); }
    return;
  }
  if (data.type === 'reveal-done' && data.generation === generation && finishReveal) {
    const finish = finishReveal; finishReveal = null; finish(); return;
  }
  if (data.type === 'delay' && session && data.generation === generation) {
    if (Number.isFinite(data.delay)) delay = Math.max(0, Math.min(3000, data.delay));
    return;
  }
  if (running) { send('error', {message: 'Odota botin vuoroa.'}); return; }
  running = true;
  try {
    if (data.type === 'init') {
      generation = data.generation; delay = data.delay ?? 350;
      send('loading', {message: 'Ladataan paikallinen botti…'});
      const runtime = await Runtime.create({worlds: data.worlds, bot: data.save?.bot ?? data.bot ?? 'legacy',
        inference: data.save ? (data.save.inference ?? 4) : (data.inference ?? 8),
        bids: data.save ? (data.save.bids ?? 0) : (data.bids ?? 0),
        singleInference: data.save ? null : (data.singleInference ?? null),
        progress: message => send('loading', {message})});
      session = new LocalSession(runtime, {
        checkpoint: save => {
          const id = ++checkpointId;
          durableCheckpoint = new Promise((resolve, reject) => checkpoints.set(id, {resolve, reject}));
          durableCheckpoint.catch(() => {});
          send('checkpoint', {save, checkpointId: id});
        },
        update: view => send('view', {view}),
        pause: async () => { await durableCheckpoint; await new Promise(resolve => setTimeout(resolve, delay)); },
        reveal: () => {
          const shown = new Promise(resolve => { finishReveal = resolve; });
          return Promise.all([durableCheckpoint, shown]);
        },
      });
      if (data.save) { session.restore(data.save); await session.advance(); }
      else session.start(shuffledDeck());
      await durableCheckpoint; send('ready', {});
    } else if (!session || data.generation !== generation) {
      throw new Error('Peli ei ole vielä valmis.');
    } else if (data.type === 'submit') {
      await session.submit(data.action);
    } else if (data.type === 'concede') {
      session.concede();
    } else if (data.type === 'next') {
      session.next(shuffledDeck());
    }
    await durableCheckpoint;
  } catch (error) { send('error', {message: error.message}); }
  finally { running = false; }
};
