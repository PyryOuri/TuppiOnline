// Source: runtime.mjs
import createModule from './runtime/ab2b37c6fa31035c211fab2fbf99505dd7b5d4f562dc9fc2a4d1db333f5773bc/tuppi.mjs';

const fields = ['phase', 'actor', 'dealer', 'contract', 'declarer', 'bidCount', 'playedCount',
  'tricks0', 'tricks1', 'score0', 'score1', 'points', 'winnerTeam', 'soolaaja', 'trickSize',
  'terminal', 'given', 'returned'];
const assetsBase = new URL('./runtime/ab2b37c6fa31035c211fab2fbf99505dd7b5d4f562dc9fc2a4d1db333f5773bc/', import.meta.url);

async function readAsset(name) {
  const response = await fetch(new URL(name, assetsBase));
  if (!response.ok) throw new Error(`Tiedoston lataus epäonnistui: ${name}`);
  return new Uint8Array(await response.arrayBuffer());
}

async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

// Heidi 1.0 and Heidi 1.1 are the same W1024 search and decisions; 1.1 names
// games played on the faster engine (distinct-hand scoring, worker lanes).
// Heidi 1.2 is that search with the new base network (model role 2) as its
// anchor only: the play-inference likelihood model stays VRPO3 (role 1) and the
// rollouts VRPO1 (role 0). Nelli 1.1 is Nelli 1.0 (heidi05, the lite C1H bot) on
// the new network (its policy and its safety net).
const heidiSearchBots = ['heidi10', 'heidi11', 'heidi12'];
const heidiSearch = bot => heidiSearchBots.includes(bot);
// The lite bots' saves carry their network cursors (seven context words).
const liteNetBots = ['heidi05', 'nelli11'];
// Controller mode (tb_configure_bot) and the model roles each bot loads: 0 rollouts,
// 1 VRPO3 (anchor and likelihood of the older bots, likelihood of Heidi 1.2), 2 the new
// network. Legacy keeps tb_configure's mode 0.
const runtimeBotModes = {legacy: 0, heidi05: 1, heidi10: 2, heidi11: 2, nelli11: 3, heidi12: 4, dan11: 0};
const modeRoles = {3: [0, 2], 4: [0, 1, 2]};
const runtimeBotRoles = bot => bot === 'dan11' ? [0, 1, 2] : modeRoles[runtimeBotModes[bot]] ?? [0, 1];

function inferenceLanes() {
  if (globalThis.crossOriginIsolated !== true || typeof SharedArrayBuffer !== 'function') return 1;
  return Math.max(1, Math.min(4, (globalThis.navigator?.hardwareConcurrency ?? 2) - 1));
}

class Runtime {
  // Profile options off by default (the owner's decision to enable): bids 1 takes Heidi 1.0's
  // anchor bid in the show phase without search; singleInference 4 runs a new game at PIB4
  // when it ends up on the single-thread backend. Saves record both (session.mjs).
  static async create({worlds = 1024, bot = 'legacy', humanSeats = [0], inference = 8,
      backend = 'auto', lanes = inferenceLanes(), read = readAsset, progress = () => {},
      bids = 0, singleInference = null} = {}) {
    if (!(bot === 'dan11' ? worlds === 64 : [128, 1024].includes(worlds))) throw new Error('Bottiasetus ei ole tuettu.');
    if (!Object.hasOwn(runtimeBotModes, bot) ||
        !Array.isArray(humanSeats) || humanSeats.some(seat => !Number.isInteger(seat) || seat < 0 || seat > 3) ||
        (heidiSearch(bot) && ![4, 8].includes(inference)) || !['auto', 'single', 'threads'].includes(backend) ||
        ![0, 1].includes(bids) || (bids && !heidiSearch(bot)) || ![null, 4, 8].includes(singleInference) ||
        !Number.isInteger(lanes) || lanes < 1 || lanes > 4)
      throw new Error('Bottiasetus ei ole tuettu.');
    progress('Ladataan bottipaketin tiedot…');
    const metadata = await read('models.json');
    const manifest = JSON.parse(new TextDecoder().decode(metadata));
    if (manifest.schema !== 'tuppi.browser.assets.v1' || manifest.ruleset !== 'project_target_v3')
      throw new Error('Bottipaketin versio ei ole tuettu.');
    const buildMetadata = await read('build.json');
    const build = JSON.parse(new TextDecoder().decode(buildMetadata));
    progress('Ladataan paikallinen pelimoottori…');
    const load = async threaded => {
      const name = threaded ? 'tuppi-thread' : 'tuppi';
      const verified = async file => {
        const record = build.outputs.find(record => record.file === file), bytes = await read(file);
        if (!record || bytes.byteLength !== record.bytes || await sha256(bytes) !== record.sha256)
          throw new Error('Pelimoottorin tarkistus epäonnistui.');
        return bytes;
      };
      const wasm = await verified(name + '.wasm');
      let factory = createModule;
      if (threaded) {
        await verified(name + '.mjs');
        factory = (await import(new URL(name + '.mjs', assetsBase).href)).default;
      }
      const options = {wasmBinary: wasm};
      const pending = Promise.resolve().then(() => factory(options));
      let timer;
      try {
        return await (threaded ? Promise.race([pending, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('Pelimoottorin käynnistys kesti liian kauan.')), 8000);
        })]) : pending);
      } catch (error) {
        options.PThread?.terminateAllThreads();
        pending.then(module => module.PThread?.terminateAllThreads(), () => {});
        throw error;
      } finally { clearTimeout(timer); }
    };
    let module, threaded = heidiSearch(bot) && backend !== 'single' && (backend === 'threads' || lanes > 1);
    try { module = await load(threaded); }
    catch (error) {
      if (!threaded || backend !== 'auto') throw error;
      threaded = false; module = await load(false);
    }
    const identityBytes = new Uint8Array(metadata.length + buildMetadata.length);
    identityBytes.set(metadata); identityBytes.set(buildMetadata, metadata.length);
    const runtime = new Runtime(module, manifest, await sha256(identityBytes));
    runtime.backend = threaded ? 'threads' : 'single'; runtime.lanes = threaded ? lanes : 1;
    if (heidiSearch(bot) && !threaded && singleInference) inference = singleInference;
    runtime.inferenceCandidates = heidiSearch(bot) ? inference : 0;
    runtime.bidMode = bids;
    try {
      if (module._tb_api_version() !== manifest.api_version) throw new Error('Pelin ja botin versiot eivät täsmää.');
      // Only the networks this bot uses: a Nelli 1.1 game never reads the VRPO3 file, a
      // Heidi 1.2 game reads all three, and the older bots never read the new network.
      const roles = runtimeBotRoles(bot), records = manifest.models.filter(record => roles.includes(record.role));
      if (records.length !== roles.length) throw new Error('Bottipaketin versio ei ole tuettu.');
      for (const record of records) {
        progress(`Ladataan botti ${records.indexOf(record) + 1}/${records.length}…`);
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
      runtime.bot = bot;
      if (bot !== 'legacy') {
        const mask = [...new Set(humanSeats)].reduce((value, seat) => value | (1 << seat), 0);
        if (!module._tb_configure_bot || module._tb_configure_bot(runtimeBotModes[bot], mask) !== 0)
          throw new Error('Tämä peliversio ei tue valittua bottia.');
        if (heidiSearch(bot) && (!module._tb_configure_inference ||
            module._tb_configure_inference(inference, runtime.lanes) !== 0))
          throw new Error('Tämä peliversio ei tue valittua bottia.');
        if (bids && (!module._tb_configure_bids || module._tb_configure_bids(bids) !== 0))
          throw new Error('Tämä peliversio ei tue valittua bottia.');
      }
      if (bot === 'dan11') {
        if (module._tb_dan_context_words?.() !== 8) throw new Error('Dan 1.1 ei ole tuettu tässä peliversiossa.');
        runtime.danContexts = Array.from({length: 4}, (_, seat) => runtime.buffer(8, (p, read) => {
          if (module._tb_dan_initial_context(seat, p)) throw new Error('Danin tallennustila ei ole tuettu.');
          return Array.from(read(), n => n >>> 0);
        }));
      }
      return runtime;
    } catch (error) { runtime.close(); throw error; }
  }

  constructor(module, manifest, identity) {
    this.m = module; this.manifest = manifest; this.identity = identity;
  }

  // The numerical profile a save is bound to (the execution backend is not part of it).
  profile() {
    return `${this.bot ?? 'legacy'} W${this.worlds}` + (heidiSearch(this.bot) ?
      ` PIB${this.inferenceCandidates ?? 4} bids:${this.bidMode ? 'anchor' : 'search'}` : '');
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.m._tb_dispose?.();
    this.m.PThread?.terminateAllThreads();
  }

  alloc(data, heap = 'HEAP32') {
    const pointer = this.m._malloc(data.byteLength);
    if (!pointer) throw new Error('Laitteen muisti ei riitä.');
    this.m.refreshHeap?.();
    this.m[heap].set(data, pointer / data.BYTES_PER_ELEMENT);
    return pointer;
  }

  buffer(length, callback, heap = 'HEAP32') {
    const bytes = heap === 'HEAPU8' ? 1 : heap === 'HEAPF64' ? 8 : 4;
    const pointer = this.m._malloc(length * bytes);
    if (!pointer) throw new Error('Laitteen muisti ei riitä.');
    try { return callback(pointer, () => {
      this.m.refreshHeap?.();
      return this.m[heap].slice(pointer / bytes, pointer / bytes + length);
    }); }
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
    this.danPending = null; this.danRevision = 0;
    if (this.bot === 'dan11') this.danContexts = this.danContexts.map(row => {
      const p = this.alloc(Int32Array.from(row));
      try {
        if (this.m._tb_dan_reset_deal(p)) throw new Error('Danin tallennustila on virheellinen.');
        return Array.from(this.m.HEAP32.subarray(p / 4, p / 4 + 8), n => n >>> 0);
      } finally { this.m._free(p); }
    });
  }

  legalActions(seat) {
    return this.buffer(210, (pointer, read) => {
      const count = this.m._tb_legal(seat, pointer);
      return Array.from(read().slice(0, count));
    });
  }

  apply(action) {
    if (!Number.isInteger(action) || this.m._tb_apply(action) !== 0) throw new Error('Siirto ei ole sallittu.');
    if (this.bot === 'dan11') {
      if (this.danPending && this.danPending.revision === this.danRevision && this.danPending.action === action)
        this.danContexts[this.danPending.seat] = [...this.danPending.context];
      this.danPending = null; this.danRevision++;
    }
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

  context() { if (this.bot === 'dan11') return this.danContexts.map(row => [...row]);
    return Array.from({length: 4}, (_, seat) =>
    Array.from({length: liteNetBots.includes(this.bot) ? 7 : 3}, (_, field) => this.m._tb_context(seat, field) >>> 0)); }
  restoreContext(context) {
    if (this.bot === 'dan11') {
      if (!Array.isArray(context) || context.length !== 4 || context.some(row => !Array.isArray(row) || row.length !== 8 ||
          row.some(v => !Number.isInteger(v) || v < 0 || v > 0xffffffff))) throw new Error('Danin tallennustila on virheellinen.');
      for (const row of context) {
        const p = this.alloc(Int32Array.from(row));
        try { if (this.m._tb_dan_validate_context(p)) throw new Error('Danin tallennustila ei ole tuettu.'); }
        finally { this.m._free(p); }
      }
      this.danContexts = context.map(row => [...row]); this.danPending = null;
      return;
    }
    const lite = liteNetBots.includes(this.bot);
    if (!Array.isArray(context) || context.length !== 4 || context.some(row =>
      !Array.isArray(row) || row.length !== (lite ? 7 : 3) || row.some(v => !Number.isInteger(v) || v < 0 || v > 0xffffffff)))
      throw new Error('Botin tallennustila on virheellinen.');
    context.forEach((row, seat) => {
      if (this.m._tb_restore_context(seat, ...row.slice(0, 3)) !== 0 ||
          (lite && this.m._tb_restore_net_context(seat, ...row.slice(3)) !== 0))
        throw new Error('Botin tallennustila ei ole tuettu.');
    });
  }

  choose(seat) {
    if (this.bot === 'dan11' && this.danPending?.seat === seat && this.danPending.revision === this.danRevision)
      return {action: this.danPending.action, values: {...this.danPending.values}, milliseconds: 0};
    const start = performance.now(); let action, proposed = null;
    if (this.bot === 'dan11') {
      if (!Number.isInteger(seat) || seat < 0 || seat > 3) throw new Error('Bottipaikka on virheellinen.');
      const before = this.alloc(Int32Array.from(this.danContexts[seat]));
      try { action = this.buffer(8, (after, read) => {
        const a = this.m._tb_dan_choose_context(seat, before, after);
        if (a >= 0) proposed = Array.from(read(), n => n >>> 0);
        return a;
      }); } finally { this.m._free(before); }
    } else action = this.m._tb_choose(seat);
    if (action < 0 || !this.legalActions(seat).includes(action)) throw new Error(`Botin siirto epäonnistui (${action}).`);
    const values = this.buffer(210, (ids, readIds) => this.buffer(210, (values, readValues) => {
      const count = this.m._tb_values(ids, values), actions = readIds(), prices = readValues();
      return Object.fromEntries(Array.from({length: count}, (_, i) => [actions[i], prices[i]]));
    }, 'HEAPF64'));
    if (proposed) this.danPending = {seat, revision: this.danRevision, action, context: proposed, values: {...values}};
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
// Heidi 1.0, 1.1 and 1.2: the search bots, whose saves bind the inference count
// (as runtime.mjs's list; not imported here, to keep the engine out, and
// named differently because release bundles concatenate the modules). The lite
// bots' saves (heidi05, nelli11) carry their network cursors in the context
// (runtime.mjs, seven words per seat).
const inferenceBoundBots = ['heidi10', 'heidi11', 'heidi12'];

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
      ...(this.runtime.bot && this.runtime.bot !== 'legacy' ? {bot: this.runtime.bot} : {}),
      ...(inferenceBoundBots.includes(this.runtime.bot) ? {inference: this.runtime.inferenceCandidates ?? 4} : {}),
      ...(this.runtime.bidMode ? {bids: this.runtime.bidMode} : {}),
      cards: [...this.cards], dealer: this.dealer, score: [...this.score], actions: [...this.actions],
      context: this.runtime.context(), humanBid: this.humanBid, completed: structuredClone(this.completed),
      archived: this.archived};
  }

  restore(save) {
    if (save?.schema !== 'tuppi.browser.save.v1' || save.identity !== this.runtime.identity ||
        save.worlds !== this.runtime.worlds || (save.bot ?? 'legacy') !== (this.runtime.bot ?? 'legacy') ||
        (inferenceBoundBots.includes(save.bot) && (save.inference ?? 4) !== (this.runtime.inferenceCandidates ?? 4)) ||
        (save.bids ?? 0) !== (this.runtime.bidMode ?? 0))
      throw new Error('Tallennus tarvitsee sen alkuperäisen peliversion ja bottiasetuksen.');
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
    return {...snapshot, bot: this.runtime.bot ?? 'legacy', thinking, revealing: this.revealing, humanBidLocked: this.humanBid !== null,
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

// Source: timeline.mjs
// Timelines for the game viewer (round 16): every decision of a match as one
// step with the whole table after it, built by replaying the match on the
// engine, so the viewer never re-implements the rules.
//
// A match is {deals: [{cards, dealer, score, actions, who?, concededAfterTricks?}]}:
// each deal's 52 dealt cards (seat s holds cards[13s..13s+12]), dealer, the
// score before it, its engine action ids in order, optionally who made each
// move ('human', 'bot' or 'forced') and the tricks completed before a
// concession. A deal still in progress simply ends early.

const SHOW_NOLO = 52, SHOW_RAMI = 104, SOOLI_YES = 157, EXCHANGE = 158;

function validDeal(deal) {
  return deal && Array.isArray(deal.cards) && deal.cards.length === 52 && new Set(deal.cards).size === 52 &&
    deal.cards.every(card => Number.isInteger(card) && card >= 0 && card < 52) &&
    Number.isInteger(deal.dealer) && deal.dealer >= 0 && deal.dealer < 4 &&
    Array.isArray(deal.score) && deal.score.length === 2 && Array.isArray(deal.actions) && deal.actions.length <= 80 &&
    deal.actions.every(Number.isInteger) && (deal.who === undefined || (Array.isArray(deal.who) &&
      deal.who.length === deal.actions.length));
}

// The winning seat of a completed trick: the highest card of the suit led
// (ace lowest in sooli play).
function trickWinner(trick, aceLow = false) {
  const suit = Math.floor(trick[0].card / 13);
  const rank = card => aceLow && card % 13 === 12 ? -1 : card % 13;
  let best = trick[0];
  for (const play of trick.slice(1)) if (Math.floor(play.card / 13) === suit && rank(play.card) > rank(best.card)) best = play;
  return best.seat;
}

// The rising score after a deal (tc_next_score): with nobody up the winner
// goes up; the team up adds; the team down winning resets to 0-0.
function scoreAfter(score, winnerTeam, points) {
  const [s0, s1] = score;
  if (!s0 && !s1) return winnerTeam === 0 ? [points, 0] : [0, points];
  const up = s0 > 0 ? 0 : 1;
  if (winnerTeam !== up) return [0, 0];
  return up === 0 ? [s0 + points, 0] : [0, s1 + points];
}

function table(runtime) {
  return {hands: [0, 1, 2, 3].map(seat => runtime.hand(seat)), bids: runtime.bids(), state: runtime.state()};
}

/* One step at a time, for timelines that grow while a game is played (bot
   games): beginDeal after runtime.init, then step(action) for every move
   (applying it to the runtime). steps and deals are the timeline so far. */
class TimelineBuilder {
  constructor(runtime) { this.runtime = runtime; this.steps = []; this.deals = []; this.current = null; }

  beginDeal(deal) {
    const d = this.deals.length;
    this.current = {deal, d, conceded: deal.concededAfterTricks ?? null, index: 0};
    const step = {deal: d, index: -1, kind: 'start', seat: null, action: null, who: null, trick: [], winner: null,
      ...table(this.runtime)};
    this.steps.push(step);
    this.deals.push({start: this.steps.length - 1, end: this.steps.length - 1, dealer: deal.dealer, score: [...deal.score],
      complete: false, result: null, concededAfterTricks: this.current.conceded});
    return step;
  }

  step(action, who = null) {
    const {deal, d, conceded} = this.current, i = this.current.index++, runtime = this.runtime;
    const before = runtime.state(), seat = before.actor, phase = before.phase;
    try { runtime.apply(action); } catch { throw new Error(`Jaon ${d + 1} siirto ${i + 1} ei ole sallittu.`); }
    const after = table(runtime);
    const step = {deal: d, index: i, seat, action, who, trick: [], winner: null, ...after};
    if (phase === 0) {
      step.kind = 'bid'; step.card = (action - SHOW_NOLO) % 52; step.contract = action >= SHOW_RAMI ? 1 : 0;
      // The bids are revealed together once the last one is locked.
      step.revealed = after.state.phase !== 0;
    } else if (phase === 3) {
      step.kind = 'sooli'; step.accept = action === SOOLI_YES;
    } else if (phase === 4 || phase === 5) {
      step.kind = phase === 4 ? 'give' : 'return'; step.card = action - EXCHANGE;
    } else {
      step.kind = 'card'; step.card = action;
      const history = runtime.history(), size = before.trickSize, n = history.length;
      step.trick = history.slice(n - (n % size || size));
      if (n % size === 0) step.winner = trickWinner(step.trick, before.soolaaja >= 0);
      step.trickNumber = Math.ceil(n / size);
      if (conceded !== null && step.trickNumber > conceded) step.forced = true;
    }
    if (who === 'forced') step.forced = true;
    const info = this.deals[d];
    if (after.state.phase === 2) {
      const final = after.state;
      step.result = {winnerTeam: final.winnerTeam, points: final.points, tricks: [final.tricks0, final.tricks1],
        scoreAfter: scoreAfter(deal.score, final.winnerTeam, final.points)};
      info.complete = true; info.result = step.result;
    }
    this.steps.push(step);
    info.end = this.steps.length - 1;
    return step;
  }
}

function buildTimeline(runtime, match) {
  if (!Array.isArray(match?.deals) || !match.deals.length || match.deals.length > 500)
    throw new Error('Ottelun tiedot ovat puutteelliset.');
  const builder = new TimelineBuilder(runtime);
  match.deals.forEach((deal, d) => {
    if (!validDeal(deal)) throw new Error(`Jaon ${d + 1} tiedot ovat virheelliset.`);
    runtime.init(deal.cards, deal.dealer, deal.score);
    builder.beginDeal(deal);
    deal.actions.forEach((action, i) => builder.step(action, deal.who?.[i] ?? null));
  });
  return {steps: builder.steps, deals: builder.deals};
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
// has its own bot (legacy W128/W1024, Nelli 1.0 or 1.1, Heidi 1.0, 1.1 or 1.2); a
// runtime per profile follows every move, and the actor's team runtime chooses.
// One game at a time; `delay` paces the moves and can change while it plays.
const botProfiles = {fast: {worlds: 128, bot: 'legacy'}, full: {worlds: 1024, bot: 'legacy'},
  heidi05: {worlds: 128, bot: 'heidi05'}, nelli11: {worlds: 128, bot: 'nelli11'}, dan11: {worlds: 64, bot: 'dan11'},
  heidi10: {worlds: 1024, bot: 'heidi10'}, heidi11: {worlds: 1024, bot: 'heidi11'}, heidi12: {worlds: 1024, bot: 'heidi12'}};
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
