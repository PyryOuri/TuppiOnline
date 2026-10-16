// Source: runtime.mjs
import createModule from './runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/tuppi.mjs';

const fields = ['phase', 'actor', 'dealer', 'contract', 'declarer', 'bidCount', 'playedCount',
  'tricks0', 'tricks1', 'score0', 'score1', 'points', 'winnerTeam', 'soolaaja', 'trickSize',
  'terminal', 'given', 'returned'];
const assetsBase = new URL('./runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/', import.meta.url);

async function readAsset(name) {
  const response = await fetch(new URL(name, assetsBase));
  if (!response.ok) throw new Error(`Tiedoston lataus epäonnistui: ${name}`);
  return new Uint8Array(await response.arrayBuffer());
}

async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

class Runtime {
  static async create({worlds = 1024, read = readAsset, progress = () => {}} = {}) {
    if (![128, 1024].includes(worlds)) throw new Error('Bottiasetus ei ole tuettu.');
    progress('Ladataan bottipaketin tiedot…');
    const metadata = await read('models.json');
    const manifest = JSON.parse(new TextDecoder().decode(metadata));
    if (manifest.schema !== 'tuppi.browser.assets.v1' || manifest.ruleset !== 'project_target_v3')
      throw new Error('Bottipaketin versio ei ole tuettu.');
    const buildMetadata = await read('build.json');
    const build = JSON.parse(new TextDecoder().decode(buildMetadata));
    progress('Ladataan paikallinen pelimoottori…');
    const wasm = await read('tuppi.wasm');
    const wasmRecord = build.outputs.find(record => record.file === 'tuppi.wasm');
    if (!wasmRecord || wasm.byteLength !== wasmRecord.bytes || await sha256(wasm) !== wasmRecord.sha256)
      throw new Error('Pelimoottorin tarkistus epäonnistui.');
    const module = await createModule({wasmBinary: wasm});
    if (module._tb_api_version() !== manifest.api_version) throw new Error('Pelin ja botin versiot eivät täsmää.');
    const identityBytes = new Uint8Array(metadata.length + buildMetadata.length);
    identityBytes.set(metadata); identityBytes.set(buildMetadata, metadata.length);
    const runtime = new Runtime(module, manifest, await sha256(identityBytes));
    for (const record of manifest.models) {
      progress(`Ladataan botti ${manifest.models.indexOf(record) + 1}/${manifest.models.length}…`);
      const bytes = await read(record.file);
      if (!Number.isInteger(record.count) || bytes.byteLength !== record.count * 4 ||
          bytes.byteLength !== record.bytes || await sha256(bytes) !== record.sha256)
        throw new Error('Bottitiedoston tarkistus epäonnistui.');
      const pointer = runtime.alloc(bytes, 'HEAPU8');
      try {
        const result = module._tb_load_model(record.role, record.in_dim, record.config.width,
          record.config.blocks, record.config.encoder, record.count, pointer);
        if (result !== 0) throw new Error(`Botin lataus epäonnistui (${result}).`);
      } finally { module._free(pointer); }
    }
    progress('Valmistellaan pisteytys ja paikallinen haku…');
    const equity = await read(manifest.equity.file);
    if (equity.byteLength !== manifest.equity.bytes || await sha256(equity) !== manifest.equity.sha256)
      throw new Error('Pisteytyspaketin tarkistus epäonnistui.');
    const pointer = runtime.alloc(equity, 'HEAPU8');
    try {
      if (module._tb_configure(worlds, pointer) !== 0) throw new Error('Hakubudjetti ei ole tuettu.');
    } finally { module._free(pointer); }
    runtime.worlds = worlds;
    return runtime;
  }

  constructor(module, manifest, identity) {
    this.m = module; this.manifest = manifest; this.identity = identity;
  }

  alloc(data, heap = 'HEAP32') {
    const pointer = this.m._malloc(data.byteLength);
    if (!pointer) throw new Error('Laitteen muisti ei riitä.');
    this.m[heap].set(data, pointer / data.BYTES_PER_ELEMENT);
    return pointer;
  }

  buffer(length, callback, heap = 'HEAP32') {
    const bytes = heap === 'HEAPU8' ? 1 : heap === 'HEAPF64' ? 8 : 4;
    const pointer = this.m._malloc(length * bytes);
    if (!pointer) throw new Error('Laitteen muisti ei riitä.');
    try { return callback(pointer, () => this.m[heap].slice(pointer / bytes, pointer / bytes + length)); }
    finally { this.m._free(pointer); }
  }

  init(cards, dealer = 0, score = [0, 0]) {
    if (!Array.isArray(cards) || cards.length !== 52 || new Set(cards).size !== 52 ||
        cards.some(card => !Number.isInteger(card) || card < 0 || card > 51) ||
        !Number.isInteger(dealer) || dealer < 0 || dealer > 3 || !Array.isArray(score) || score.length !== 2 ||
        score.some(value => !Number.isInteger(value) || value < 0 || value >= 52 || value % 4) ||
        (score[0] && score[1])) throw new Error('Jaon tiedot ovat virheelliset.');
    const pointer = this.alloc(Int32Array.from(cards));
    try {
      if (this.m._tb_init(pointer, dealer, ...score) !== 0) throw new Error('Jaon tiedot ovat virheelliset.');
    } finally { this.m._free(pointer); }
  }

  legalActions(seat) {
    return this.buffer(210, (pointer, read) => {
      const count = this.m._tb_legal(seat, pointer);
      return Array.from(read().slice(0, count));
    });
  }

  apply(action) {
    if (!Number.isInteger(action) || this.m._tb_apply(action) !== 0) throw new Error('Siirto ei ole sallittu.');
  }

  state() { return Object.fromEntries(fields.map((field, i) => [field, this.m._tb_state(i)])); }
  hand(seat) {
    return this.buffer(14, (pointer, read) => {
      const count = this.m._tb_hand(seat, pointer);
      return Array.from(read().slice(0, count));
    });
  }

  history() {
    return this.buffer(52, (cards, readCards) => this.buffer(52, (seats, readSeats) => {
      const count = this.m._tb_history(cards, seats), c = readCards(), s = readSeats();
      return Array.from({length: count}, (_, i) => ({card: c[i], seat: s[i]}));
    }));
  }

  bids() {
    return this.buffer(4, (cards, readCards) => this.buffer(4, (seats, readSeats) =>
      this.buffer(4, (contracts, readContracts) => {
        const count = this.m._tb_bids(cards, seats, contracts);
        const c = readCards(), s = readSeats(), k = readContracts();
        return Array.from({length: count}, (_, i) => ({card: c[i], seat: s[i], contract: k[i]}));
      })));
  }

  context() { return Array.from({length: 4}, (_, seat) =>
    Array.from({length: 3}, (_, field) => this.m._tb_context(seat, field) >>> 0)); }
  restoreContext(context) {
    if (!Array.isArray(context) || context.length !== 4 || context.some(row =>
      !Array.isArray(row) || row.length !== 3 || row.some(v => !Number.isInteger(v) || v < 0 || v > 0xffffffff)))
      throw new Error('Botin tallennustila on virheellinen.');
    context.forEach((row, seat) => {
      if (this.m._tb_restore_context(seat, ...row) !== 0) throw new Error('Botin tallennustila ei ole tuettu.');
    });
  }

  choose(seat) {
    const start = performance.now(), action = this.m._tb_choose(seat);
    if (action < 0 || !this.legalActions(seat).includes(action)) throw new Error(`Botin siirto epäonnistui (${action}).`);
    const values = this.buffer(210, (ids, readIds) => this.buffer(210, (values, readValues) => {
      const count = this.m._tb_values(ids, values), actions = readIds(), prices = readValues();
      return Object.fromEntries(Array.from({length: count}, (_, i) => [actions[i], prices[i]]));
    }, 'HEAPF64'));
    return {action, values, milliseconds: performance.now() - start};
  }

  features(seat, encoder = 2) {
    return this.buffer(2048, (pointer, read) => {
      const count = this.m._tb_features(seat, encoder, pointer);
      return read().slice(0, count);
    }, 'HEAPU8');
  }

  inference(role, features, rows = 1) {
    const input = this.alloc(features, 'HEAPU8');
    try {
      return this.buffer(rows * 156, (output, read) => {
        if (this.m._tb_inference(role, input, rows, output) !== 0) throw new Error('Mallin arvio epäonnistui.');
        return read();
      }, 'HEAPF32');
    } finally { this.m._free(input); }
  }

  snapshot(seat = 0) {
    const state = this.state();
    return {...state, hand: this.hand(seat), counts: [0, 1, 2, 3].map(s => this.hand(s).length),
      legal: this.legalActions(seat), history: this.history(), bids: this.bids(),
      heapBytes: this.m.HEAPU8.byteLength, worlds: this.worlds};
  }
}

// Source: session.mjs
// The deal's result is already 0-0: in the rising score a deal won by the team
// behind resets the match, and that is certain once, in NOLO (contract 0), the
// team ahead has 7 tricks or, in RAMI (1), the team behind has 7. Normal trick
// play (phase 1) only. The server's rule is match_runner.concede_available;
// network.mjs keeps the same rule for online views (separate bundles).
function decidedForZero({phase, contract, tricks0, tricks1, score0, score1}) {
  if (phase !== 1 || (!score0 && !score1)) return false;
  const tricks = [tricks0, tricks1], ahead = score0 > 0 ? 0 : 1;
  return contract === 1 ? tricks[1 - ahead] >= 7 : tricks[ahead] >= 7;
}

/* LocalSession is independent of DOM, workers and persistence adapters. */
class LocalSession {
  constructor(runtime, {checkpoint = () => {}, update = () => {}, pause = async () => {}, reveal = async () => {}} = {}) {
    this.runtime = runtime; this.checkpoint = checkpoint; this.update = update; this.pause = pause;
    this.reveal = reveal; this.revealing = false;
    this.completed = []; this.humanBid = null; this.actions = []; this.archived = false;
    this.concession = null;
  }

  start(cards, dealer = 0, score = [0, 0]) {
    this.cards = [...cards]; this.dealer = dealer; this.score = [...score];
    this.actions = []; this.humanBid = null; this.archived = false; this.revealing = false;
    this.runtime.init(cards, dealer, score); this.captureStartingHand(); this.emit();
  }

  captureStartingHand() {
    // Capture only the human's dealt hand, before play or a sooli exchange.
    // Restore derives this again from the existing deal, without changing saves.
    const suitLengths = [0, 0, 0, 0]; let highCardPoints = 0;
    for (const card of this.runtime.hand(0)) {
      suitLengths[Math.floor(card / 13)]++;
      highCardPoints += Math.max(0, card % 13 - 8);
    }
    this.startingHandSummary = {suitLengths, highCardPoints};
  }

  save() {
    return {schema: 'tuppi.browser.save.v1', identity: this.runtime.identity, worlds: this.runtime.worlds,
      cards: [...this.cards], dealer: this.dealer, score: [...this.score], actions: [...this.actions],
      context: this.runtime.context(), humanBid: this.humanBid, completed: structuredClone(this.completed),
      archived: this.archived};
  }

  restore(save) {
    if (save?.schema !== 'tuppi.browser.save.v1' || save.identity !== this.runtime.identity ||
        save.worlds !== this.runtime.worlds) throw new Error('Tallennus tarvitsee sen alkuperäisen peliversion ja bottiasetuksen.');
    if (!Array.isArray(save.cards) || save.cards.length !== 52 || !Array.isArray(save.score) || save.score.length !== 2 ||
        !Number.isInteger(save.dealer) || !Array.isArray(save.actions) || save.actions.length > 64 ||
        !Array.isArray(save.completed) || save.completed.length > 500 || typeof save.archived !== 'boolean')
      throw new Error('Tallennuksen rakenne on virheellinen.');
    const completed = save.completed.map(deal => {
      if (!Array.isArray(deal.cards) || deal.cards.length !== 52 || !Array.isArray(deal.score) || deal.score.length !== 2 ||
          !Number.isInteger(deal.dealer) || !Array.isArray(deal.actions) || deal.actions.length > 64)
        throw new Error('Jaon tallennus on virheellinen.');
      this.runtime.init(deal.cards, deal.dealer, deal.score);
      deal.actions.forEach(action => this.runtime.apply(action));
      if (this.runtime.state().phase !== 2) throw new Error('Historian jako ei ole valmis.');
      // Optional (older saves have none): a deal finished by concession.
      if (deal.conceded !== undefined && (deal.conceded === null || !Number.isInteger(deal.conceded.afterTricks) ||
          deal.conceded.afterTricks < 0 || deal.conceded.afterTricks > 12)) throw new Error('Jaon tallennus on virheellinen.');
      return {cards: [...deal.cards], dealer: deal.dealer, score: [...deal.score], actions: [...deal.actions],
        result: this.runtime.state(), history: this.runtime.history(),
        ...(deal.conceded ? {conceded: {afterTricks: deal.conceded.afterTricks}} : {})};
    });
    this.runtime.init(save.cards, save.dealer, save.score);
    this.captureStartingHand();
    save.actions.forEach(action => this.runtime.apply(action));
    this.runtime.restoreContext(save.context);
    if (save.humanBid !== null && (this.runtime.state().phase !== 0 ||
        !this.runtime.legalActions(0).includes(save.humanBid))) throw new Error('Tallennuksen lukittu tarjous on virheellinen.');
    this.cards = [...save.cards]; this.dealer = save.dealer; this.score = [...save.score];
    this.actions = [...save.actions]; this.humanBid = save.humanBid;
    this.completed = completed; this.archived = save.archived; this.revealing = false;
    if (this.archived !== (this.runtime.state().phase === 2)) throw new Error('Tallennuksen lopputila ei täsmää.');
    this.emit();
  }

  view(thinking = false) {
    const snapshot = this.runtime.snapshot(0);
    return {...snapshot, thinking, revealing: this.revealing, humanBidLocked: this.humanBid !== null,
      concedeAvailable: !thinking && this.concedeAvailable(),
      startingHandSummary: structuredClone(this.startingHandSummary),
      waitingHuman: !thinking && !this.revealing && snapshot.phase !== 2 &&
        (snapshot.phase === 0 ? this.humanBid === null : snapshot.actor === 0),
      dealNumber: this.completed.length + (this.archived ? 0 : 1),
      completed: this.completed.map((deal, i) => ({index: i, result: deal.result, history: deal.history,
        conceded: deal.conceded ?? null}))};
  }

  emit(thinking = false) { this.checkpoint(this.save()); this.update(this.view(thinking)); }

  apply(action) {
    const wasShowing = this.runtime.state().phase === 0;
    this.runtime.apply(action); this.actions.push(action);
    if (wasShowing && this.runtime.state().phase !== 0) this.revealing = true;
    if (this.runtime.state().phase !== 0) this.humanBid = null;
    this.archiveIfComplete();
    this.emit();
  }

  archiveIfComplete() {
    if (this.runtime.state().phase !== 2 || this.archived) return;
    this.completed.push({cards: [...this.cards], dealer: this.dealer, score: [...this.score],
      actions: [...this.actions], result: this.runtime.state(), history: this.runtime.history(),
      ...(this.concession ? {conceded: this.concession} : {})});
    this.archived = true; this.concession = null;
  }

  async submit(action) {
    if (this.revealing) throw new Error('Odota tarjousten paljastamista.');
    if (!Number.isInteger(action) || !this.runtime.legalActions(0).includes(action)) throw new Error('Siirto ei ole sallittu.');
    if (this.runtime.state().phase === 0) {
      if (this.humanBid !== null) throw new Error('Tarjous on jo lukittu.');
      this.humanBid = action; this.emit(true);
    } else {
      if (this.runtime.state().actor !== 0) throw new Error('Odota omaa vuoroasi.');
      this.apply(action);
    }
    await this.advance();
  }

  concedeAvailable() {
    const state = this.runtime.state();
    return !this.revealing && !this.archived && decidedForZero({...state, score0: this.score[0], score1: this.score[1]});
  }

  // Finish a decided deal at once: every seat plays its first legal card. The
  // bots are not asked, so their random state (the saved context) is unchanged;
  // the plays are ordinary saved actions, so a restore replays them exactly.
  concede() {
    if (!this.concedeAvailable()) throw new Error('Jakoa ei voi luovuttaa nyt.');
    const state = this.runtime.state();
    this.concession = {afterTricks: state.tricks0 + state.tricks1};
    while (this.runtime.state().phase === 1) {
      const action = this.runtime.legalActions(this.runtime.state().actor)[0];
      this.runtime.apply(action); this.actions.push(action);
    }
    this.archiveIfComplete(); this.emit();
  }

  async advance() {
    for (;;) {
      // The UI acknowledges the full Swift-style reveal before any player can act.
      if (this.revealing) {
        await this.reveal(this.runtime.bids());
        this.revealing = false; this.emit();
      }
      const state = this.runtime.state();
      if (state.phase === 2) break;
      if (state.phase === 0) {
        if (this.humanBid === null) break;
        if (state.actor === 0) { this.apply(this.humanBid); continue; }
      } else if (state.actor === 0) break;
      this.emit(true);
      await this.pause();
      const choice = this.runtime.choose(state.actor);
      this.apply(choice.action);
    }
    this.update(this.view(false));
  }

  next(cards) {
    const state = this.runtime.state();
    if (state.phase !== 2 || state.terminal) throw new Error('Uutta jakoa ei voi aloittaa vielä.');
    this.start(cards, (this.dealer + 1) % 4, [state.score0, state.score1]);
  }
}

// Analysis of a finished deal: replay it and, at each of one seat's decisions
// with more than one legal option, run the bot's search from that seat's view
// (what it could see then; others' locked bids stay hidden) and compare the
// move made with the bot's choice. Use a runtime that plays no game: its random
// state is reset from `context` so the same deal always gets the same answer.
// Plays made automatically after a concession (`stopAfterPlayed`) are not judged.
function analyseDeal(runtime, deal, seat, {context = null, stopAfterPlayed = 52, expectedTricks = null, progress = () => {}} = {}) {
  if (!Array.isArray(deal?.cards) || deal.cards.length !== 52 || !Array.isArray(deal.actions) || !Number.isInteger(seat))
    throw new Error('Jaon tiedot ovat puutteelliset.');
  runtime.init(deal.cards, deal.dealer, deal.score);
  if (context) runtime.restoreContext(context);
  const decisions = [], mine = deal.actions.length;
  deal.actions.forEach((action, index) => {
    const state = runtime.state();
    if (state.actor === seat && state.phase !== 2 && state.playedCount < stopAfterPlayed) {
      const legal = runtime.legalActions(seat);
      if (legal.length > 1 && legal.includes(action)) {
        const {action: best, values} = runtime.choose(seat);
        const known = values[action] !== undefined && values[best] !== undefined;
        decisions.push({index, phase: state.phase, played: state.playedCount, trickSize: state.trickSize, options: legal.length,
          chosen: action, best, loss: action === best ? 0 : known ? Math.max(0, values[best] - values[action]) : null,
          value: known ? values[action] : null, bestValue: known ? values[best] : null});
      }
      progress(index + 1, mine);
    }
    runtime.apply(action);
  });
  const end = runtime.state();
  if (end.phase !== 2 || (expectedTricks && (end.tricks0 !== expectedTricks[0] || end.tricks1 !== expectedTricks[1])))
    throw new Error('Jakoa ei voitu toistaa analyysia varten.');
  return {seat, worlds: runtime.worlds, decisions};
}

function shuffledDeck() {
  const cards = Array.from({length: 52}, (_, i) => i), buffer = new Uint32Array(1);
  for (let i = 51; i > 0; i--) {
    const limit = Math.floor(0x100000000 / (i + 1)) * (i + 1);
    do { crypto.getRandomValues(buffer); } while (buffer[0] >= limit);
    const j = buffer[0] % (i + 1);
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }
  return cards;
}

// Source: worker.mjs
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
