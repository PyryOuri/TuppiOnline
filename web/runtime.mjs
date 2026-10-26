import createModule from './assets/tuppi.mjs';

const fields = ['phase', 'actor', 'dealer', 'contract', 'declarer', 'bidCount', 'playedCount',
  'tricks0', 'tricks1', 'score0', 'score1', 'points', 'winnerTeam', 'soolaaja', 'trickSize',
  'terminal', 'given', 'returned'];
export const assetsBase = new URL('./assets/', import.meta.url);

export async function readAsset(name) {
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
export const heidiSearchBots = ['heidi10', 'heidi11', 'heidi12'];
const heidiSearch = bot => heidiSearchBots.includes(bot);
// The lite bots' saves carry their network cursors (seven context words).
export const liteNetBots = ['heidi05', 'nelli11'];
// Controller mode (tb_configure_bot) and the model roles each bot loads: 0 rollouts,
// 1 VRPO3 (anchor and likelihood of the older bots, likelihood of Heidi 1.2), 2 the new
// network. Legacy keeps tb_configure's mode 0.
export const runtimeBotModes = {legacy: 0, heidi05: 1, heidi10: 2, heidi11: 2, nelli11: 3, heidi12: 4, dan11: 0};
const modeRoles = {3: [0, 2], 4: [0, 1, 2]};
export const runtimeBotRoles = bot => bot === 'dan11' ? [0, 1, 2] : modeRoles[runtimeBotModes[bot]] ?? [0, 1];

export function inferenceLanes() {
  if (globalThis.crossOriginIsolated !== true || typeof SharedArrayBuffer !== 'function') return 1;
  return Math.max(1, Math.min(4, (globalThis.navigator?.hardwareConcurrency ?? 2) - 1));
}

export class Runtime {
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
