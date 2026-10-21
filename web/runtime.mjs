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

export class Runtime {
  static async create({worlds = 1024, bot = 'legacy', humanSeats = [0], read = readAsset, progress = () => {}} = {}) {
    if (![128, 1024].includes(worlds)) throw new Error('Bottiasetus ei ole tuettu.');
    if (!['legacy', 'heidi05', 'heidi10'].includes(bot) ||
        !Array.isArray(humanSeats) || humanSeats.some(seat => !Number.isInteger(seat) || seat < 0 || seat > 3))
      throw new Error('Bottiasetus ei ole tuettu.');
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
    runtime.bot = bot;
    if (bot !== 'legacy') {
      const mask = [...new Set(humanSeats)].reduce((value, seat) => value | (1 << seat), 0);
      if (!module._tb_configure_bot || module._tb_configure_bot(bot === 'heidi05' ? 1 : 2, mask) !== 0)
        throw new Error('Tämä peliversio ei tue valittua bottia.');
    }
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
    Array.from({length: this.bot === 'heidi05' ? 7 : 3}, (_, field) => this.m._tb_context(seat, field) >>> 0)); }
  restoreContext(context) {
    if (!Array.isArray(context) || context.length !== 4 || context.some(row =>
      !Array.isArray(row) || row.length !== (this.bot === 'heidi05' ? 7 : 3) || row.some(v => !Number.isInteger(v) || v < 0 || v > 0xffffffff)))
      throw new Error('Botin tallennustila on virheellinen.');
    context.forEach((row, seat) => {
      if (this.m._tb_restore_context(seat, ...row.slice(0, 3)) !== 0 ||
          (this.bot === 'heidi05' && this.m._tb_restore_net_context(seat, ...row.slice(3)) !== 0))
        throw new Error('Botin tallennustila ei ole tuettu.');
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
