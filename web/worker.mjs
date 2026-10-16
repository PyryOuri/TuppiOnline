import {Runtime} from './runtime.mjs';
import {LocalSession, analyseDeal, shuffledDeck} from './session.mjs';

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

self.onmessage = async ({data}) => {
  if (data.type === 'analyse') { analysisQueue = analysisQueue.then(() => runAnalysis(data)); return; }
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
      const runtime = await Runtime.create({worlds: data.worlds, progress: message => send('loading', {message})});
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
