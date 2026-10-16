// Source: capabilities.mjs
// The release packager selects this flag; local development includes networking.
const networkEnabled = true;

// Source: preferences.mjs
const preferenceKey = 'tuppi.ui.preferences.v1';
const defaults = {nickname: 'Pelaaja', expandedHand: false, turnSound: false};
function cleanPreferences(value) {
  return {nickname: typeof value?.nickname === 'string' && value.nickname.trim() ? value.nickname.trim().slice(0, 40) : defaults.nickname,
    expandedHand: value?.expandedHand === true, turnSound: value?.turnSound === true};
}
// Optional UI preferences cannot prevent a match from opening. They never
// contain room credentials, actions, cards or an offline save.
function loadPreferences(storage) {
  try { return cleanPreferences(JSON.parse((storage ?? globalThis.localStorage)?.getItem(preferenceKey) ?? 'null')); }
  catch { return {...defaults}; }
}
function savePreferences(value, storage) {
  const preferences = cleanPreferences(value);
  try { (storage ?? globalThis.localStorage)?.setItem(preferenceKey, JSON.stringify(preferences)); }
  catch {}
  return preferences;
}

// Source: storage.mjs
let database;
function open() {
  if (!database) database = new Promise((resolve, reject) => {
    const request = indexedDB.open('tuppi-local', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('saves');
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => { db.close(); database = null; };
      db.onclose = () => { database = null; };
      resolve(db);
    };
    request.onerror = () => reject(request.error);
  }).catch(error => { database = null; throw error; });
  return database;
}

async function hash(save) {
  const bytes = new TextEncoder().encode(JSON.stringify(save));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

async function envelope(save) { return {format: 'tuppi.local.backup.v1', sha256: await hash(save), save}; }
async function unwrap(record) {
  if (!record || record.format !== 'tuppi.local.backup.v1' || await hash(record.save) !== record.sha256)
    throw new Error('Tallennuksen tarkistus epäonnistui.');
  return record.save;
}

async function readLocalRecord(key = 'current') {
  if (!['current', 'previous'].includes(key)) throw new Error('Tuntematon paikallinen tallennus.');
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db.transaction('saves').objectStore('saves').get(key);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}

async function load() {
  const record = await readLocalRecord();
  return record ? unwrap(record) : null;
}

async function store(save, {replace = false} = {}) {
  const record = await envelope(save), db = await open();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('saves', 'readwrite');
    const saves = transaction.objectStore('saves');
    if (replace) {
      // Copy and replacement commit together. A quota/abort failure preserves
      // both the old match and its previous recovery copy, including raw data
      // whose integrity check failed. Never touch the separate network key.
      const request = saves.get('current');
      request.onsuccess = () => {
        if (request.result && JSON.stringify(request.result) !== JSON.stringify(record)) saves.put(request.result, 'previous');
        saves.put(record, 'current');
      };
    } else saves.put(record, 'current');
    transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error('Tallennus keskeytyi.'));
  });
}

// Online credentials occupy a separate key and never enter offline backups.
async function loadNetwork() {
  const db = await open();
  const record = await new Promise((resolve, reject) => {
    const request = db.transaction('saves').objectStore('saves').get('network');
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  return record ? unwrap(record) : null;
}
async function storeNetwork(session) {
  const record = await envelope(session), db = await open();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('saves', 'readwrite');
    transaction.objectStore('saves').put(record, 'network');
    transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error('Verkkopelin tallennus keskeytyi.'));
  });
}

async function storageHealth({requestPersistence = false, storage = navigator.storage} = {}) {
  let persistent = null, usage = null, quota = null;
  const errors = [];
  if (storage?.persisted) {
    try { persistent = await storage.persisted(); } catch (error) { errors.push(error.message); }
  }
  if (requestPersistence && persistent !== true && storage?.persist) {
    try { persistent = await storage.persist(); } catch (error) { errors.push(error.message); }
  }
  if (storage?.estimate) {
    try {
      const estimate = await storage.estimate();
      if (Number.isFinite(estimate.usage)) usage = estimate.usage;
      if (Number.isFinite(estimate.quota)) quota = estimate.quota;
    } catch (error) { errors.push(error.message); }
  }
  return {persistent, usage, quota, available: usage !== null && quota !== null ? Math.max(0, quota - usage) : null,
    canRequest: Boolean(storage?.persist), errors};
}

// Source: table.mjs
// Presentation and keyboard rules mirror the Swift table, without deciding legality.
const suits = ['♥', '♦', '♣', '♠'];
const suitCodes = ['H', 'D', 'C', 'S'];
const suitNames = ['hertta', 'ruutu', 'risti', 'pata'];
const seatNames = ['Sinä', 'Vasen vastustaja', 'Pari', 'Oikea vastustaja'];
const revealTiming = {step: 700, hold: 1800, fade: 400};
const suitShapes = [
  '<path d="M16 28S3 19.2 3 10.5C3 3.6 11.8 1.5 16 7.5c4.2-6 13-3.9 13 3C29 19.2 16 28 16 28Z"/>',
  '<path d="M16 2 29 16 16 30 3 16Z"/>',
  '<circle cx="16" cy="8" r="6"/><circle cx="8" cy="17" r="6.7"/><circle cx="24" cy="17" r="6.7"/><path d="M13 15h6c-1 5-1 9 3 14H10c4-5 4-9 3-14Z"/>',
  '<path d="M16 2C12 8 3 12 3 19a7 7 0 0 0 11.5 5.3L11 30h10l-3.5-5.7A7 7 0 0 0 29 19C29 12 20 8 16 2Z"/>',
];
function suitSVG(suit) {
  return `<svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" focusable="false">${suitShapes[suit]}</svg>`;
}

function cardRank(card) {
  const n = card % 13 + 2;
  return n < 11 ? String(n) : ['J', 'Q', 'K', 'A'][n - 11];
}
function cardLabel(card) { return `${cardRank(card)}${suits[Math.floor(card / 13)]}`; }
function cardAction(card, phase, contract = 0) {
  return card + (phase === 0 ? 52 + 52 * contract : [4, 5].includes(phase) ? 158 : 0);
}
function legalCards(view, contract) {
  return view.hand.filter(card => view.legal.includes(cardAction(card, view.phase, contract)));
}
function sortedHand(view) {
  const aceLow = view.soolaaja >= 0 || [4, 5, 6].includes(view.phase);
  const rank = card => aceLow && card % 13 === 12 ? -1 : card % 13;
  return view.hand.toSorted((a, b) => Math.floor(a / 13) - Math.floor(b / 13) || rank(a) - rank(b));
}
function bidRevealFrame(bids, elapsed) {
  const last = revealTiming.step * Math.max(0, bids.length - 1);
  return {cards: bids.slice(0, Math.min(bids.length, 1 + Math.floor(elapsed / revealTiming.step))),
    contractPending: elapsed < last, fading: elapsed >= last + revealTiming.hold,
    finished: elapsed >= last + revealTiming.hold + revealTiming.fade};
}

class TableKeyboardSelection {
  reset() { this.suit = null; this.awaitingTen = false; }
  constructor() { this.reset(); }
  get prompt() {
    if (this.suit === null) return null;
    return this.awaitingTen
      ? `Näppäimistö: ${suits[this.suit]} 1 valittu — paina 0 kortille 10${suitCodes[this.suit]}.`
      : `Näppäimistö: ${suits[this.suit]} valittu — paina arvoa 2–9, 0/T, J, Q, K tai A.`;
  }
  handle(key, view, contract) {
    if (!view?.waitingHuman || view.revealing || view.phase === 2) { this.reset(); return null; }
    const input = key.toUpperCase();
    if (view.phase === 0 && ['N', 'R'].includes(input)) {
      const value = input === 'R' ? 1 : 0;
      if (!legalCards(view, value).length) return null;
      this.reset(); return {type: 'contract', contract: value};
    }
    const suit = suitCodes.indexOf(input);
    if (suit >= 0) { this.suit = suit; this.awaitingTen = false; return {type: 'armed'}; }
    if (this.suit === null) return null;
    if (input === '1') { this.awaitingTen = true; return {type: 'armed'}; }
    const rank = ['0', 'T'].includes(input) ? 8 :
      ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'].indexOf(input);
    if (rank < 0) return null;
    this.awaitingTen = false;
    const card = this.suit * 13 + rank;
    if (!legalCards(view, contract).includes(card)) return {type: 'unavailable', card};
    this.reset(); return {type: 'card', card};
  }
  adjacent(selected, direction, view, contract) {
    if (!view?.waitingHuman || view.revealing || selected === null) return null;
    const hand = sortedHand(view), start = hand.indexOf(selected), allowed = legalCards(view, contract);
    if (start < 0) return null;
    for (let distance = 1; distance < hand.length; distance++) {
      const card = hand[(start + direction * distance + hand.length) % hand.length];
      if (allowed.includes(card)) return card;
    }
    return null;
  }
}

// Source: hand.mjs
// Geometry only: card IDs, legality and rank order belong to the session/table.
function handGeometry({count, width, compact = false, expanded = false, scale = 1}) {
  const available = Math.max(1, width), size = Math.max(1, scale);
  const cardWidth = (compact || expanded ? 64 : 60) * size;
  const cardHeight = cardWidth * 1.42;
  const gap = 8 * size;
  const capacity = expanded ? Math.max(1, Math.floor((available + gap) / (cardWidth + gap))) :
    compact ? Math.max(1, Math.min(7, Math.floor((available - cardWidth) / (40 * size)) + 1)) : Math.max(1, count);
  const columns = Math.min(Math.max(1, count), capacity);
  const stride = expanded ? cardWidth + gap : compact ? Math.min(48 * size, (available - cardWidth) / Math.max(1, columns - 1)) :
    count > 1 ? Math.min(40, Math.max(30, Math.floor((available - cardWidth) / (count - 1)))) : 0;
  const step = Math.max(0, stride), rows = Math.ceil(count / capacity);
  const occupied = cardWidth + Math.max(0, columns - 1) * step;
  return {cardWidth, cardHeight, capacity, rows, width: Math.max(cardWidth, occupied),
    height: rows ? rows * cardHeight + (rows - 1) * gap : 0,
    positions: Array.from({length: count}, (_, index) => ({
      x: index % capacity * step, y: Math.floor(index / capacity) * (cardHeight + gap),
    }))};
}

// Keep card nodes through selection, checkpoints and connection updates. This
// preserves keyboard/assistive focus; only a changed hand changes DOM order.
class HandView {
  constructor(element, create, update) {
    this.element = element; this.create = create; this.update = update; this.cards = new Map();
  }
  render(ids, state) {
    const nodes = ids.map(id => {
      if (!this.cards.has(id)) this.cards.set(id, this.create(id));
      const node = this.cards.get(id); this.update(node, id, state); return node;
    });
    for (const id of this.cards.keys()) if (!ids.includes(id)) this.cards.delete(id);
    if (nodes.length !== this.element.children.length || nodes.some((node, i) => node !== this.element.children[i])) {
      this.element.replaceChildren(...nodes);
    }
  }
  layout(options) {
    const geometry = handGeometry({count: this.element.children.length, ...options});
    this.element.style.width = `${geometry.width}px`;
    this.element.style.height = `${geometry.height}px`;
    this.element.style.setProperty('--hand-card-width', `${geometry.cardWidth}px`);
    this.element.style.setProperty('--hand-card-height', `${geometry.cardHeight}px`);
    geometry.positions.forEach(({x, y}, i) => {
      this.element.children[i].style.setProperty('--card-x', `${x}px`);
      this.element.children[i].style.setProperty('--card-y', `${y}px`);
    });
    return geometry;
  }
}

// Source: presentation.mjs
// Only consume the adapter's public view, never infer a hidden bid or hand.
function seatPresentation(view, seat, nickname = seatNames[seat]) {
  const team = seat % 2 ? 'Vastustaja' : 'Joukkueesi';
  const role = view.soolaaja === seat ? 'Soolaaja' :
    view.soolaaja >= 0 && seat === (view.soolaaja + 2) % 4 ? 'Kuollut käsi' :
    !view.revealing && view.phase !== 0 && view.declarer === seat ? 'Julistaja' : '';
  const count = `${view.counts[seat]} korttia`;
  const position = view.dealer === seat ? 'Jakaja' : (view.dealer + 1) % 4 === seat ? 'Etukäsi' : '';
  const bid = !view.revealing && view.bids.find(item => item.seat === seat);
  const shown = bid ? `Näytetty ${cardLabel(bid.card)} · ${bid.contract ? 'RAMI' : 'NOLO'}` : '';
  return {name: nickname, count, position, role, shown, team,
    detail: [team, count, position, role, shown].filter(Boolean).join(' · '),
    active: view.phase !== 2 && view.actor === seat};
}

// End-of-match summary from the public completed-deal results only.
function matchSummary(view) {
  if (!view?.terminal) return null;
  const deals = view.completed ?? [], ours = deals.filter(deal => deal.result.winnerTeam === 0);
  const count = test => deals.filter(deal => test(deal.result)).length;
  const best = Math.max(0, ...ours.map(deal => deal.result.points));
  const won = view.score0 > view.score1;
  return {won, title: `${won ? 'Voititte ottelun' : 'Vastustajat voittivat ottelun'} ${view.score0}–${view.score1}`,
    lines: [`${deals.length} ${deals.length === 1 ? 'jako' : 'jakoa'}: voititte ${ours.length}, vastustajat ${deals.length - ours.length}.`,
      `RAMI ${count(r => r.soolaaja < 0 && r.contract === 1)} · NOLO ${count(r => r.soolaaja < 0 && r.contract === 0)} · SOOLI ${count(r => r.soolaaja >= 0)}`,
      ...(best ? [`Suurin jakovoittonne: ${best} pistettä.`] : [])]};
}

// Source: offline.mjs
// The packager pins this value without changing runtime/model save identity.
const packagedRuntimeIdentity = "95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d";

class OfflineSetup {
  constructor({serviceWorker = navigator.serviceWorker, paths, onChange = () => {}} = {}) {
    this.serviceWorker = serviceWorker; this.paths = paths; this.onChange = onChange;
    this.registration = null; this.state = {state: 'idle', ready: false}; this.queryToken = 0;
  }
  request(worker, data, timeout = 5000) {
    if (!worker) return Promise.resolve(null);
    return new Promise(resolve => {
      const channel = new MessageChannel(), timer = setTimeout(() => { channel.port1.close(); resolve(null); }, timeout);
      channel.port1.onmessage = ({data}) => { clearTimeout(timer); channel.port1.close(); resolve(data); };
      try { worker.postMessage(data, [channel.port2]); }
      catch { clearTimeout(timer); channel.port1.close(); resolve(null); }
    });
  }
  async refresh() {
    if (!this.registration) return;
    const token = ++this.queryToken, registration = this.registration;
    const active = registration.active, newest = registration.installing ?? registration.waiting ?? active;
    const [current, update] = await Promise.all([this.request(active, {type: 'offline-status', paths: this.paths}),
      newest !== active ? this.request(newest, {type: 'offline-status', paths: this.paths}) : Promise.resolve(null)]);
    if (token !== this.queryToken) return;
    this.activeStatus = current;
    const data = update ?? current ?? {state: 'idle'};
    const ready = Boolean(current?.ready && current.clientReady);
    const error = data.error ?? (!ready && !['downloading', 'ready'].includes(data.state) ? this.state.error : null);
    this.state = {...data, state: error ? 'error' : data.state ?? (ready ? 'ready' : 'idle'), ready,
      updateReady: Boolean(update?.ready), error};
    this.onChange(this.state);
  }
  watch(worker) {
    if (!worker) return;
    worker.addEventListener('statechange', () => {
      if (worker.state === 'redundant' && !this.state.ready) {
        this.state = {...this.state, state: 'error', error: this.state.error ?? 'Offline-lataus jäi kesken. Yritä uudelleen.'};
        this.onChange(this.state);
      } else this.refresh();
    });
  }
  async start() {
    if (this.started) return this.started;
    this.started = this.begin();
    return this.started;
  }
  async begin() {
    if (!this.serviceWorker) {
      this.state = {state: 'unavailable', ready: false, error: 'Tämä selain ei tue offline-käynnistystä.'};
      this.onChange(this.state); return;
    }
    this.serviceWorker.addEventListener('message', ({data}) => {
      if (data?.type !== 'offline-progress') return;
      this.state = {...this.state, ...data}; this.onChange(this.state);
      if (['ready', 'error'].includes(data.state)) this.refresh();
    });
    this.serviceWorker.addEventListener('controllerchange', () => this.refresh());
    await this.retry();
  }
  async retry() {
    try {
      this.registration = await this.serviceWorker.register('./sw.mjs', {type: 'module'});
      this.registration.addEventListener('updatefound', () => this.watch(this.registration.installing));
      this.watch(this.registration.installing);
      await this.refresh();
      if (!this.registration.installing && !this.registration.waiting && !this.state.ready) {
        // An unchanged worker script is not reinstalled after cache eviction.
        // Rehydrate its verified release explicitly before checking for updates.
        if (this.registration.active && this.activeStatus?.recovery === 1) await this.repair(packagedRuntimeIdentity);
        await this.registration.update();
      }
    } catch (error) {
      this.registration ??= await this.serviceWorker.getRegistration().catch(() => null);
      if (this.registration?.active) await this.refresh();
      if (!this.state.ready) { this.state = {...this.state, state: 'error', error: error.message}; this.onChange(this.state); }
    }
  }
  // After the game server returns from a restart (perhaps a new release),
  // look for a newer browser release, at most every ten minutes. It installs
  // in the background and never activates beneath an open Tuppi.
  async checkForUpdate(now = Date.now()) {
    if (!this.registration || now - (this.lastUpdateCheck ?? -Infinity) < 600000) return false;
    this.lastUpdateCheck = now;
    try { await this.registration.update(); } catch { return false; }
    await this.refresh(); return true;
  }
  async compatible(identity) {
    return (await this.release(identity))?.launch ?? null;
  }
  async latestInstalled() {
    this.registration ??= await this.serviceWorker?.getRegistration();
    const data = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths});
    if (!/^[a-f0-9]{64}$/.test(data?.identity ?? '')) return null;
    this.activeStatus = data;
    return {identity: data.identity,
      engine: /^engine\.[a-f0-9]{16}\.mjs$/.test(data.currentEngine ?? '') ? data.currentEngine : null};
  }
  async release(identity) {
    if (!/^[a-f0-9]{64}$/.test(identity ?? '')) return null;
    this.registration ??= await this.serviceWorker?.getRegistration();
    const data = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths, identity});
    const launch = /^launch\.[a-f0-9]{16}\.html$/.test(data?.compatibleLaunch ?? '') ? data.compatibleLaunch : null;
    const engine = /^engine\.[a-f0-9]{16}\.mjs$/.test(data?.compatibleEngine ?? '') ? data.compatibleEngine : null;
    return launch || engine ? {identity, launch, engine} : null;
  }
  async repair(identity = packagedRuntimeIdentity) {
    this.registration ??= await this.serviceWorker?.getRegistration();
    const status = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths});
    if (status?.recovery !== 1) throw new Error('Sulje kaikki Tuppi-ikkunat ja avaa peli uudelleen päivityksen valmistuttua. Tallennukset säilyvät.');
    const data = await this.request(this.registration?.active, {type: 'offline-repair', identity}, 120000);
    await this.refresh();
    if (!data?.repaired) throw new Error(data?.error ?? 'Pelitiedostoja ei voitu palauttaa. Tarkista verkkoyhteys ja yritä uudelleen.');
    return data;
  }
  async retain(identities) {
    if (this.registration?.installing || this.registration?.waiting || !this.state.ready) return;
    return this.request(this.registration.active, {type: 'offline-retain', paths: this.paths, identities});
  }
}

// Source: network.mjs
// Transport and presentation of authorised seat observations. No local engine.
const networkProtocol = 'tuppi.network.v1';
const networkPhases = {SHOWING: 0, TRICK_PLAY: 1, DEAL_COMPLETE: 2, MATCH_COMPLETE: 2,
  SOOLI_OFFER: 3, SOOLI_GIVE: 4, SOOLI_RETURN: 5, SOOLI_PLAY: 6};
const networkErrors = {room_not_found:'Huonetta ei löydy. Tarkista huonekoodi.', room_full:'Huone on täynnä.',
  invalid_session:'Tallennettua paikkaa ei löydy. Voit luoda uuden huoneen.',
  settings_locked:'Ottelu on jo alkanut. Paikat on lukittu.', host_required:'Vain huoneen luoja voi vaihtaa bottipaikkoja.',
  server_busy:'Palvelu on täynnä. Jatka huoneeseen myöhemmin.',
  room_passcode_required:'Huoneen luominen tällä palvelimella vaatii luontikoodin.',
  invalid_room_passcode:'Luontikoodi ei kelpaa. Tarkista koodi.',
  too_many_attempts:'Liian monta väärää koodia. Odota minuutti ja yritä uudelleen.',
  storage_unavailable:'Palvelimen tallennus ei juuri nyt toimi. Siirtoasi ei tallennettu; peli jatkuu, kun palvelu on käynnistynyt uudelleen.',
  storage_low:'Palvelimen tallennustila on vähissä, joten uusia huoneita ei nyt voi luoda. Käynnissä olevat pelit jatkuvat.',
  match_not_active:'Ottelu ei ole käynnissä.', match_not_complete:'Uuden ottelun voi aloittaa, kun ottelu on päättynyt.',
  invalid_display_name:'Kirjoita nimimerkki (1–40 merkkiä).'};
function networkBase(value) {
  const url = new URL(value);
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) ||
      url.username || url.password || url.search || url.hash || url.pathname !== '/')
    throw new Error('Verkkopalvelun osoitteen on oltava HTTPS-alkuperä.');
  return url.origin;
}
function networkCard(code) {
  const match = /^(2|3|4|5|6|7|8|9|10|J|Q|K|A)([HDCS])$/.exec(code);
  if (!match) throw new Error('Palvelin lähetti tuntemattoman kortin.');
  return 'HDCS'.indexOf(match[2]) * 13 + ['2','3','4','5','6','7','8','9','10','J','Q','K','A'].indexOf(match[1]);
}
function networkCardCode(card) {
  if (!Number.isInteger(card) || card < 0 || card > 51) throw new Error('Tuntematon kortti.');
  return ['2','3','4','5','6','7','8','9','10','J','Q','K','A'][card % 13] + 'HDCS'[Math.floor(card / 13)];
}
function networkActionID(action) {
  if (action.type === 'show') return 52 + (action.declared_contract === 'RAMI' ? 52 : 0) + networkCard(action.shown_card);
  if (action.type === 'play') return networkCard(action.card);
  if (action.type === 'sooli_exchange') return 158 + networkCard(action.card);
  if (action.type === 'sooli_decision') return action.play_sooli ? 157 : 156;
  throw new Error('Palvelin lähetti tuntemattoman siirron.');
}
function networkSeat(seat, observingSeat) {
  return seat === null || seat === undefined || seat < 0 ? -1 : (seat - observingSeat + 4) % 4;
}
function networkView(payload, completed = [], summary = null) {
  const observation = payload.observation, own = observation.observing_seat;
  if (!Number.isInteger(own) || own < 0 || own > 3 || observation.ruleset_id !== 'project_target_v3' ||
      !(observation.phase in networkPhases)) throw new Error('Verkkopelin säännöt tai paikka eivät vastaa tätä versiota.');
  const phase = networkPhases[observation.phase], team = own % 2;
  const play = item => ({seat: networkSeat(item.seat, own), card: networkCard(item.card)});
  const history = [...observation.completed_tricks.flatMap(trick => trick.plays), ...observation.current_trick].map(play);
  const counts = [13,13,13,13];
  for (const item of history) counts[item.seat]--;
  const soolaaja = networkSeat(observation.sooli?.soolaaja, own), partner = (soolaaja + 2) % 4;
  if (phase === 5 && soolaaja >= 0) { counts[soolaaja]--; counts[partner]++; }
  const hand = observation.own_hand.map(networkCard); counts[0] = hand.length;
  const actions = phase === 0 ? payload.bidding?.options ?? [] : observation.legal_actions;
  if (actions.some(action => action.seat !== own)) throw new Error('Siirto kuuluu toiselle paikalle.');
  const legal = actions.map(networkActionID);
  const deals = completed.map(deal => ({index: deal.deal_number,
    history: deal.tricks.flatMap(trick => trick.plays).map(play),
    result: {contract: deal.contract === 'RAMI' ? 1 : 0,
      soolaaja: networkSeat(deal.sooli?.soolaaja, own), trickSize: deal.sooli?.soolaaja === null || !deal.sooli ? 4 : 3,
      winnerTeam: deal.deal_score.winner_team === team ? 0 : 1, points: deal.deal_score.points}}));
  const currentCompleted = completed.find(deal => deal.deal_ref === observation.deal_ref);
  return {phase, hand, legal, waitingHuman: legal.length > 0, thinking: false, revealing: false,
    actor: phase === 0 && legal.length ? 0 : networkSeat(observation.current_actor, own),
    dealer: networkSeat(observation.dealer, own), declarer: networkSeat(observation.declarer, own), soolaaja,
    contract: observation.contract === 'RAMI' ? 1 : 0, score0: observation.match_score[team], score1: observation.match_score[1-team],
    tricks0: observation.team_tricks[team], tricks1: observation.team_tricks[1-team], counts,
    dealNumber: currentCompleted ? currentCompleted.deal_number + 1 : completed.length + 1,
    bids: observation.show_actions.map(bid => ({seat: networkSeat(bid.seat, own), card: networkCard(bid.shown_card),
      contract: bid.declared_contract === 'RAMI' ? 1 : 0})), history, completed: deals,
    trickSize: soolaaja >= 0 && observation.sooli.exchanged ? 3 : 4,
    terminal: observation.match_terminal, startingHandSummary: summary,
    prompt: legal.length ? null : phase === 0 ? 'Tarjous lukittu. Odotetaan muita pelaajia…' :
      observation.current_actor === null ? 'Ottelu päättyi.' : 'Odotetaan siirtoa…'};
}

class NetworkSession {
  constructor({persist, onView = () => {}, onLobby = () => {}, onStatus = () => {}, onConnection = () => {},
    onReconnect = () => {}, fetcher = (...args) => globalThis.fetch(...args), Socket = globalThis.WebSocket, timers = globalThis} = {}) {
    Object.assign(this, {persist, onView, onLobby, onStatus, onConnection, onReconnect, fetcher, Socket, timers});
    this.session = null; this.socket = null; this.connected = false; this.stopped = true;
    this.queue = Promise.resolve(); this.retryCount = 0; this.epoch = 0; this.completed = new Map();
    this.authRequired = false; this.configuring = false; this.lobbyRevision = 0;
    // client_action_id of a pending move that an authorised update already
    // contains. Never sent or stored: the pending envelope must stay exact.
    this.placed = null;
    // Optional host commands the server accepts (hello_ack.features).
    this.features = new Set();
    // A server restart (close 1012/1001, e.g. an update) is shown as such
    // until the seat is authorised again; onReconnect then lets the app
    // look for a newer browser release.
    this.restarting = false; this.interrupted = false;
  }
  // The server broadcasts an accepted move before the paced bot replies and
  // acknowledges it after them. Only this seat's own move can advance the
  // match from the cursor it was based on; a stale move is rejected at once.
  placedPending() { return Boolean(this.session?.pending) && this.placed === this.session.pending.client_action_id; }
  connection(phase) {
    if (phase === 'connected' && (!this.connected || this.stopped)) phase = 'synchronising';
    if (phase === 'reconnecting' && this.restarting) phase = 'restarting';
    const state = {phase: this.authRequired ? 'authentication' : phase,
      pending: Boolean(this.session?.pending), connected: this.connected && !this.stopped};
    const key = JSON.stringify(state);
    if (key !== this.lastConnection) { this.lastConnection = key; this.onConnection(state); }
  }
  async request(path, payload = null, base = this.session?.base) {
    const controller = new AbortController(), timeout = this.timers.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await this.fetcher(networkBase(base) + path, {method: payload ? 'POST' : 'GET',
        cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
        headers: payload ? {'Content-Type': 'application/json'} : {}, body: payload ? JSON.stringify(payload) : undefined});
      if ([401, 403].includes(response.status) && !response.headers?.get('content-type')?.includes('application/json')) {
        this.authRequired = true; this.connection('authentication');
        throw new Error(`Testilinkin kirjautuminen tarvitsee vahvistuksen (HTTP ${response.status}). Päivitä sama sivu ja kirjaudu tarvittaessa uudelleen; huoneesi säilyy.`);
      }
      let result;
      try { result = await response.json(); }
      catch {
        // Do not show returned HTML, URLs, headers or any credential in errors.
        const operation = path.endsWith('/configure') ? 'Bottipaikkojen päivitys' : path.endsWith('/join') ? 'Huoneeseen liittyminen' : 'Verkkopyyntö';
        throw new Error(`${operation}: palvelu palautti virheellisen vastauksen (HTTP ${response.status ?? '?'}, ${response.headers?.get('content-type')?.split(';')[0] || 'tuntematon tyyppi'}). Päivitä sama sivu ja yritä uudelleen.`);
      }
      if (!response.ok) {
        const error = new Error(networkErrors[result.error] || 'Verkkopalvelun pyyntö epäonnistui.');
        error.code = result.error; throw error;
      }
      return result;
    } finally { this.timers.clearTimeout(timeout); }
  }
  async check(base) {
    const result = await this.request('/v1/compatibility', null, base);
    if (result.protocol_version !== networkProtocol || result.ruleset_id !== 'project_target_v3')
      throw new Error('Palvelin tarvitsee yhteensopivan peliversion.');
  }
  // Public hosts may require a room-creation passcode; joining never does.
  async createPasscodeRequired(base) {
    return Boolean((await this.request('/v1/compatibility', null, base)).create_passcode_required);
  }
  async create(base, displayName, passcode = '') {
    await this.check(base);
    const result = await this.request('/v1/rooms', {display_name: displayName, ai_seats: [],
      ...(passcode ? {room_passcode: passcode} : {})}, base);
    await this.begin({...result, base: networkBase(base), host: true, pending: null, cursor: -1,
      schema: 'tuppi.browser.network.v1', active: true});
  }
  async join(base, code, displayName) {
    if (!/^[A-Z0-9]{6}$/.test(code)) throw new Error('Huonekoodi on kuusi kirjainta tai numeroa.');
    await this.check(base);
    const result = await this.request(`/v1/rooms/${code}/join`, {display_name: displayName}, base);
    await this.begin({...result, base: networkBase(base), host: false, pending: null, cursor: -1,
      schema: 'tuppi.browser.network.v1', active: true});
  }
  async begin(session) {
    if (session?.schema !== 'tuppi.browser.network.v1' || !/^[A-Z0-9]{6}$/.test(session.room_code) ||
        typeof session.session_token !== 'string' || session.session_token.length < 20 ||
        !Number.isInteger(session.seat) || session.seat < 0 || session.seat > 3)
      throw new Error('Verkkopelin tallennus ei ole yhteensopiva.');
    networkBase(session.base);
    this.close(); this.session = structuredClone(session); this.completed.clear(); this.latest = null;
    await this.persist(this.session); this.stopped = false;
    this.onLobby(this.session.lobby); this.connect();
  }
  connect() {
    if (this.stopped || this.socket) return;
    this.connected = false; this.connection(this.retryCount ? 'reconnecting' : 'connecting'); this.onStatus('Yhdistetään verkkopeliin…', false);
    const epoch = ++this.epoch;
    const url = new URL('/v1/ws', this.session.base); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = this.socket = new this.Socket(url.href);
    const live = () => !this.stopped && this.epoch === epoch && this.socket === socket;
    this.deadline = this.timers.setTimeout(() => { if (live()) socket.close(); }, 20000);
    socket.onopen = () => { if (live()) { this.connection('synchronising'); this.send('hello', {protocol_version: networkProtocol,
      room_code: this.session.room_code, session_token: this.session.session_token}); } };
    socket.onmessage = event => {
      this.lastHeard = Date.now();
      this.queue = this.queue.then(async () => { if (live()) await this.message(JSON.parse(event.data)); })
        .catch(error => { if (live()) { this.close(); this.connection('failed'); this.onStatus(error.message, true); } });
    };
    socket.onerror = () => {};
    socket.onclose = event => {
      if (!live()) return;
      this.socket = null; this.connected = false;
      this.pendingSent = false; this.emitView();
      this.timers.clearTimeout(this.deadline); this.timers.clearTimeout(this.heartbeat);
      if (event.code === 4001) { this.stopped = true; this.connection('superseded'); this.onStatus('Tämä paikka avattiin toisessa välilehdessä.', true); return; }
      this.interrupted = true;
      if ([1001, 1012].includes(event.code)) this.restarting = true;
      this.connection('reconnecting');
      this.onStatus(this.restarting ? 'Palvelin käynnistyy uudelleen, esimerkiksi päivityksen vuoksi. Paikkasi säilyy; peli jatkuu hetken kuluttua…' :
        'Yhteys katkesi. Paikkasi säilyy; yhdistetään uudelleen…', false);
      const delay = Math.min(30000, 500 * 2 ** this.retryCount++) * (0.8 + Math.random() * 0.4);
      this.retry = this.timers.setTimeout(() => this.connect(), delay);
    };
  }
  send(messageType, payload) {
    if (this.socket?.readyState !== 1) return false;
    this.socket.send(JSON.stringify({message_type: messageType, payload})); return true;
  }
  beat() {
    this.timers.clearTimeout(this.heartbeat);
    this.heartbeat = this.timers.setTimeout(() => {
      if (Date.now() - this.lastHeard > 60000) this.socket?.close();
      else { this.send('ping', {}); this.beat(); }
    }, 25000);
  }
  async message(message) {
    const payload = message.payload;
    if (message.message_type === 'hello_ack') {
      if (payload.protocol_version !== networkProtocol || payload.seat !== this.session.seat || payload.room_code !== this.session.room_code)
        throw new Error('Verkkopelin paikka tai versio muuttui.');
      this.retryCount = 0; this.timers.clearTimeout(this.deadline); this.beat();
      const resumed = this.interrupted; this.restarting = this.interrupted = false;
      if (resumed) this.onReconnect();
      this.features = new Set(Array.isArray(payload.features) ? payload.features : []);
      // The browser never reads the full terminal match result; skip it.
      if (this.features.has('compact_results')) this.send('client_options', {omit_match_result: true});
    } else if (message.message_type === 'compatibility_result') throw new Error('Päivitä Tuppi ennen verkkopeliä.');
    else if (message.message_type === 'protocol_error') throw new Error(networkErrors[payload.code] || 'Verkkopelin yhteyttä ei voitu jatkaa. Paikkasi on tallennettu.');
    else if (message.message_type === 'lobby_snapshot') {
      this.lobbyRevision++;
      if (this.latest && !['playing','completed'].includes(payload.lifecycle)) {
        // The host started a rematch: the finished match's view and cursor
        // belong to the previous match. The next match starts from event 0.
        this.latest = null; this.completed.clear(); this.placed = null;
        Object.assign(this.session, {cursor: -1, match_ref: null, pending: null, summaryDeal: null, summary: null});
      }
      this.session.lobby = payload; await this.persist(this.session); this.onLobby(payload);
      this.emitView();
      if (!['playing','completed'].includes(payload.lifecycle)) { this.connected = true; this.connection('connected'); this.onStatus('', false); }
    } else if (['match_update','reconnect_result'].includes(message.message_type)) {
      if (payload.observation.observing_seat !== this.session.seat) throw new Error('Palvelin lähetti väärän paikan havainnon.');
      for (const deal of payload.completed_deals ?? []) this.completed.set(deal.deal_number, deal);
      this.latest = payload;
      const events = payload.event_batch ?? payload.event_delta ?? [];
      this.session.cursor = payload.last_event_index ?? events.at(-1)?.event_index ?? this.session.cursor;
      this.session.match_ref = payload.match_ref ?? payload.observation.match_ref;
      if (this.session.pending && this.session.cursor > this.session.pending.expected_event_index)
        this.placed = this.session.pending.client_action_id;
      if (payload.observation.phase === 'SHOWING' && this.session.summaryDeal !== payload.observation.deal_ref) {
        const hand = payload.observation.own_hand.map(networkCard);
        this.session.summaryDeal = payload.observation.deal_ref;
        this.session.summary = {suitLengths: [0,1,2,3].map(suit => hand.filter(c => Math.floor(c/13) === suit).length),
          highCardPoints: hand.reduce((sum,c) => sum + Math.max(0,c%13-8),0)};
      }
      await this.persist(this.session); this.connected = true;
      const unplaced = this.session.pending && !this.placedPending();
      this.connection(unplaced ? 'pending' : 'connected');
      this.emitView(); this.onStatus(unplaced ? 'Varmistetaan edellinen siirto…' : '', false);
      // The full authorised snapshot arrives first. Retry only the original
      // envelope/id; the server either deduplicates it or rejects it as stale.
      if (this.session.pending && !this.pendingSent) {
        this.pendingSent = true; this.send('action_submission', this.session.pending);
      }
    } else if (message.message_type === 'action_acknowledgement') {
      if (payload.client_action_id !== this.session.pending?.client_action_id) return;
      const accepted = ['accepted','duplicate'].includes(payload.status);
      this.session.pending = null; this.pendingSent = false; this.placed = null;
      await this.persist(this.session); this.connection('connected'); this.emitView();
      this.onStatus(accepted ? '' : payload.status === 'stale' ? 'Tilanne muuttui. Valitse siirto uudelleen.' :
        payload.code === 'paused' ? 'Peli on tauolla. Valitse siirto, kun peli jatkuu.' : `Siirtoa ei hyväksytty: ${payload.code}`, !accepted);
    }
  }
  emitView() {
    if (!this.latest) return;
    const view = networkView(this.latest, [...this.completed.values()].sort((a,b) => a.deal_number-b.deal_number),
      this.session.summaryDeal === this.latest.observation.deal_ref ? this.session.summary : null);
    const paused = Boolean(this.session.lobby?.paused) && !view.terminal;
    if (!this.connected || this.stopped || this.session.pending || paused) view.waitingHuman = false;
    view.paused = paused;
    if (!this.connected) view.prompt = 'Yhdistetään verkkopeliin…';
    else if (paused) view.prompt = this.session.host ? 'Peli on tauolla. Jatka, kun kaikki ovat valmiita.' : 'Peli on tauolla. Huoneen luoja jatkaa peliä.';
    else if (this.session.pending && view.phase !== 2 &&
        (!this.placedPending() || this.latest.observation.current_actor === this.session.seat)) view.prompt = 'Käsitellään siirtoasi…';
    else if (!view.waitingHuman && ![0,2].includes(view.phase)) {
      const participant = this.session.lobby?.seats.find(s => s.seat === this.latest.observation.current_actor);
      view.prompt = participant?.kind === 'ai' ? `${participant.display_name || 'Botti'} miettii…` :
        participant ? `${participant.display_name}: odotetaan siirtoa…` : 'Odotetaan siirtoa…';
    }
    this.onView(view);
  }
  async submit(id) {
    if (!this.connected || this.session.pending || !this.latest) return;
    const observation = this.latest.observation;
    const actions = observation.phase === 'SHOWING' ? this.latest.bidding?.options ?? [] : observation.legal_actions;
    const action = actions.find(item => networkActionID(item) === id);
    if (!action) return;
    this.session.pending = {action, client_action_id: crypto.randomUUID(), expected_event_index: this.session.cursor,
      match_ref: this.session.match_ref};
    this.placed = null;
    this.connection('pending');
    this.emitView(); await this.persist(this.session);
    this.pendingSent = this.send('action_submission', this.session.pending);
  }
  // Host commands: pause and resume a match in progress, rematch after it.
  hostCommand(type) {
    const feature = type === 'rematch' ? 'rematch' : 'pause';
    if (!this.session?.host || !this.connected || this.stopped || !this.features.has(feature)) return false;
    return this.send(type, {});
  }
  // Wins and losses per nickname on this server; null when not offered.
  async leaderboard() {
    if (!this.session || !this.features.has('leaderboard')) return null;
    const result = await this.request(`/v1/rooms/${this.session.room_code}/leaderboard`, {session_token: this.session.session_token});
    return Array.isArray(result.entries) ? result.entries : [];
  }
  pause() { return this.hostCommand('pause'); }
  resume() { return this.hostCommand('resume'); }
  rematch() { return this.hostCommand('rematch'); }
  ready() { if (this.connected && !this.stopped && !this.configuring && !this.authRequired) this.send('ready', {session_token: this.session.session_token}); }
  async fillEmptySeats() {
    const aiSeats = this.session.lobby.seats.filter(s => ['open','ai'].includes(s.kind)).map(s => s.seat);
    await this.configureBots(aiSeats);
  }
  async configureBots(aiSeats) {
    if (!this.session.host || !this.connected || this.stopped) throw new Error('Vain huoneen luoja voi vaihtaa bottipaikkoja.');
    if (this.configuring || this.authRequired) return;
    const epoch = this.epoch, revision = this.lobbyRevision;
    this.configuring = true; this.onLobby(this.session.lobby);
    try {
      const result = await this.request(`/v1/rooms/${this.session.room_code}/configure`,
        {session_token: this.session.session_token, ai_seats: aiSeats});
      if (epoch !== this.epoch || this.stopped) return;
      // A WebSocket snapshot received during this HTTP request is newer than
      // its captured response; do not overwrite another player's readiness.
      if (revision === this.lobbyRevision) { this.session.lobby = result.lobby; await this.persist(this.session); }
    } finally { this.configuring = false; if (epoch === this.epoch && !this.stopped) this.onLobby(this.session.lobby); }
  }
  async toggleBot(seat) {
    const current = this.session.lobby.seats.find(s => s.seat === seat);
    if (!current || seat === 0 || !['open','ai'].includes(current.kind)) throw new Error('Paikka on jo pelaajan käytössä.');
    const aiSeats = new Set(this.session.lobby.seats.filter(s => s.kind === 'ai').map(s => s.seat));
    if (aiSeats.has(seat)) aiSeats.delete(seat); else aiSeats.add(seat);
    await this.configureBots([...aiSeats].sort());
  }
  async openSeats() {
    await this.configureBots([]);
  }
  wake() {
    if (this.stopped) return;
    if (this.socket?.readyState === 1 && this.latest) {
      this.connected = false; this.connection('synchronising'); this.emitView(); this.pendingSent = false;
      this.send('reconnect', {last_applied_event_index: -1});
    } else if (!this.socket) { this.timers.clearTimeout(this.retry); this.connect(); }
  }
  async retryNow() {
    if (!this.session || this.authRequired || this.retrying) return;
    this.retrying = true; this.close(); this.connection('reconnecting');
    const epoch = this.epoch;
    try {
      await this.queue.catch(() => {});
      if (epoch !== this.epoch || this.authRequired) return;
      this.close(); this.retryCount = 0; this.stopped = false; this.connect();
    } finally { this.retrying = false; }
  }
  close() {
    this.stopped = true; this.connected = false; this.epoch++;
    this.timers.clearTimeout(this.retry); this.timers.clearTimeout(this.deadline); this.timers.clearTimeout(this.heartbeat);
    this.socket?.close(); this.socket = null; this.pendingSent = false;
    this.emitView();
  }
}

// Source: lobby.mjs
// Pasted links supply only a room code. Requests still use this app's configured
// server; a link to another site must be opened there rather than joined here.
function roomCodeFromInput(value, base) {
  const text = String(value ?? '').trim();
  if (/^[a-z0-9]{6}$/i.test(text)) return text.toUpperCase();
  let url;
  try { url = new URL(text); } catch { throw new Error('Kirjoita kuusimerkkinen huonekoodi tai liitä kutsulinkki.'); }
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Kutsulinkki ei ole kelvollinen.');
  if (base && url.origin !== new URL(base).origin) throw new Error('Tämä kutsu on toiselle Tuppi-sivustolle. Avaa alkuperäinen kutsulinkki.');
  const code = url.searchParams.get('room') ?? '';
  if (!/^[a-z0-9]{6}$/i.test(code)) throw new Error('Kutsulinkistä puuttuu kelvollinen huonekoodi.');
  return code.toUpperCase();
}

function lobbyPresentation(lobby, ownSeat = 0) {
  const seats = lobby.seats.map(seat => ({...seat, position: networkSeat(seat.seat, ownSeat)}));
  const teams = [0, 1].map(team => seats.filter(seat => seat.position % 2 === team)
    .sort((a, b) => a.position - b.position));
  const humans = seats.filter(seat => seat.kind === 'human');
  const open = seats.filter(seat => seat.kind === 'open').length;
  const waiting = humans.filter(seat => !seat.ready);
  const playing = ['playing', 'completed'].includes(lobby.lifecycle);
  const label = seat => seat.position === 0 ? 'sinä' : seat.display_name || seatNames[seat.position];
  const readyText = playing ? 'Ottelu on alkanut. Paikat on lukittu.' : open ?
    `${open} ${open === 1 ? 'vapaa paikka' : 'vapaata paikkaa'}. Kutsu ystävä tai lisää botti ennen valmiuden vahvistamista.` :
    waiting.length ? `Valmiutta odotetaan: ${waiting.map(label).join(', ')}.` : 'Kaikki ovat valmiina. Ottelu alkaa…';
  return {teams, humans: humans.length, bots: seats.filter(seat => seat.kind === 'ai').length,
    open, playing, readyText, configuration: JSON.stringify(seats.map(seat => [seat.seat, seat.kind, seat.display_name])),
    ownReady: Boolean(humans.find(seat => seat.seat === ownSeat)?.ready)};
}

function invitationURL(page, room) {
  if (!/^[A-Z0-9]{6}$/.test(room)) throw new Error('Virheellinen huonekoodi.');
  const link = new URL(page); link.search = ''; link.hash = '';
  link.searchParams.set('play', 'online'); link.searchParams.set('room', room);
  return link.href;
}

class LobbyView {
  constructor(teams, onToggle) { this.teams = teams; this.onToggle = onToggle; this.nodes = new Map(); }
  render(model, {host, connected, configuring = false}) {
    model.teams.forEach((seats, index) => {
      const nodes = seats.map(seat => {
        if (!this.nodes.has(seat.seat)) {
          const item = document.createElement('li'); item.className = 'lobby-seat';
          const position = document.createElement('span'); position.className = 'lobby-position';
          const name = document.createElement('strong'); name.className = 'lobby-name';
          const state = document.createElement('span'); state.className = 'lobby-state';
          const button = document.createElement('button'); button.type = 'button';
          button.onclick = () => this.onToggle(seat.seat);
          item.append(position, name, state, button);
          this.nodes.set(seat.seat, {item, position, name, state, button});
        }
        const node = this.nodes.get(seat.seat), label = seatNames[seat.position];
        node.position.textContent = label;
        node.name.textContent = seat.display_name || (seat.kind === 'ai' ? 'Botti' : 'Vapaa paikka');
        node.state.textContent = seat.kind === 'ai' ? 'Botti' : seat.kind === 'open' ? 'Odottaa pelaajaa' : seat.ready ? 'Pelaaja · valmis' : 'Pelaaja · ei vielä valmis';
        node.item.dataset.kind = seat.kind;
        node.button.hidden = !host || model.playing || !['open', 'ai'].includes(seat.kind);
        node.button.disabled = !connected || configuring;
        node.button.textContent = seat.kind === 'ai' ? 'Avaa ystävälle' : 'Lisää botti';
        node.button.setAttribute('aria-label', `${node.button.textContent}: ${label}`);
        return node.item;
      });
      const list = this.teams[index];
      if (nodes.length !== list.children.length || nodes.some((node, i) => node !== list.children[i])) list.replaceChildren(...nodes);
    });
  }
}

// Source: app.mjs
const $ = id => document.getElementById(id);
let worker, generation = 0, view, lastSave, selectedCard = null, bidContract = 0, busy = true, writeAccess = false;
let saveQueue = Promise.resolve(), replayDeal, replayIndex = 0;
let pendingWrites = 0, saveFailed = false, durableIdentity = null, saveIdentityKnown = false;
let previousRecord = null, previousSave = null, recoveryKnown = false, localReadable = false, changingLocal = false, hasLocalRecord = false;
let activeIdentity = packagedRuntimeIdentity, repairIdentity = packagedRuntimeIdentity;
let replacementPending = false;
let preferences = loadPreferences();
let expandedHand = preferences.expandedHand, detailSeat = null;
let leaderboardEntries = null, leaderboardFetched = 0, leaderboardLoading = false, matchEndCounted = false;
let turnAudio = null, lastTurnKey = null;
let connectionState = {phase: 'local'}, lobbyConfiguration = null, lobbyRoom = null;
const historyRows = new Map();
const keyboard = new TableKeyboardSelection();
let keyboardFeedback = '', revealTimer, revealFrame = null, revealKey = null;
let networkClient = null, savedNetwork = null, networkAddress = null, offlineStarted = false, networkRevealDeal = null;
let screen = 'home', entryReady = false, networkResolved = false, navigationPending = false, navigationToken = 0;
let roomIntent = 'join', invitation = false, entryPending = false, passcodeRequired = null, passcodeCheck = null;
let awaitingNetworkGame = false;
const networkEntry = (() => { try { return new URL(globalThis.location.href).searchParams; } catch { return new URLSearchParams(); } })();
const startsOnline = networkEnabled && (networkEntry.get('play') === 'online' || networkEntry.has('room'));
async function readNetworkConfiguration() {
  if (!networkEnabled) return null;
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch('./deployment.json', {cache: 'no-store', signal: controller.signal});
    const config = await response.json();
    if (response.ok && config.schema === 'tuppi.browser.deployment.v1' && config.backend) return networkBase(config.backend);
  } catch {} finally { clearTimeout(timeout); }
  return null;
}
const networkConfiguration = readNetworkConfiguration();
const networkReady = networkConfiguration.then(address => {
  networkAddress = address; networkResolved = true;
  if (!writeAccess) return address;
  renderHome();
  if (!$('network-entry').hidden) renderRoomEntry();
  if (!address && $('network-dialog').open) $('network-status').textContent = 'Verkkopeli ei ole käytettävissä. Voit pelata botteja vastaan.';
  else if ($('network-status').textContent === 'Yhdistetään verkkopeliin…') $('network-status').textContent = '';
  return address;
});

function cardFace(card, interactive = false, disabled = false, selected = false, legal = true, shown = false) {
  const suit = Math.floor(card / 13), rank = cardRank(card);
  const element = document.createElement(interactive ? 'button' : 'span');
  element.className = `card ${suit < 2 ? 'red' : ''} ${selected ? 'selected' : ''} ${legal ? '' : 'illegal'} ${shown ? 'shown' : ''}`;
  element.setAttribute('aria-label', `${suitNames[suit]} ${rank}`);
  const corner = `<span class="rank">${rank}</span><span class="suit">${suitSVG(suit)}</span>`;
  const shownBadge = shown ? '<span class="shown-badge" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></span>' : '';
  element.innerHTML = `<span class="corner" aria-hidden="true">${corner}</span><span class="center-suit" aria-hidden="true">${suitSVG(suit)}</span><span class="corner bottom" aria-hidden="true">${corner}</span>${shownBadge}`;
  if (interactive) {
    element.type = 'button'; element.disabled = disabled;
    element.setAttribute('aria-pressed', String(selected)); element.onclick = () => pickCard(card);
  }
  return element;
}

function status(message, error = false) {
  $('status').textContent = message; $('status').classList.toggle('error', error);
  if ($('settings').open && error) $('settings-status').textContent = message;
  if (screen === 'home' && error && !document.querySelector('dialog[open]')) { $('home-status').textContent = message; $('home-status').classList.toggle('error', true); }
}
// One modal at a time. Native dialog supplies Escape, focus containment and
// focus return; settings must not push the live table down the page.
function openDialog(id) {
  const dialog = $(id), current = document.querySelector('dialog[open]');
  if (current && current !== dialog) current.close();
  dialog.hidden = false;
  if (!dialog.open) dialog.showModal();
}
function renderHome() {
  const session = networkClient?.session ?? savedNetwork;
  $('home-friends').hidden = !networkEnabled;
  $('home-online').disabled = !entryReady || !writeAccess || navigationPending || entryPending;
  $('home-online').textContent = session?.active && session.base === networkAddress ? `Jatka huoneessa ${session.room_code}` : 'Pelaa verkossa';
  $('home-local').disabled = !entryReady || !writeAccess || !localReadable || changingLocal || navigationPending || entryPending;
  $('home-local').textContent = lastSave || (worker && !networkClient) ? 'Jatka omaa peliä' : 'Pelaa botteja vastaan';
  $('home-local-copy').textContent = lastSave ? 'Tallennettu ottelusi jatkuu siitä, mihin jäit.' : 'Pelaa omaan tahtiin. Ottelu tallentuu tälle laitteelle.';
  $('network-toggle').hidden = !networkEnabled || !networkClient?.session;
}
function showGame() {
  screen = 'game'; $('home').hidden = true; $('game').hidden = $('game-footer').hidden = false;
  $('mode-label').textContent = networkClient?.session ? `· Verkkopeli ${networkClient.session.room_code}` : '· Paikallinen peli';
}
function showHome() {
  navigationToken++; awaitingNetworkGame = false;
  document.querySelector('dialog[open]')?.close();
  screen = 'home'; $('home').hidden = false; $('game').hidden = $('game-footer').hidden = true;
  $('mode-label').textContent = '';
  if (entryReady) { $('home-status').textContent = ''; $('home-status').classList.toggle('error', false); }
  render();
}
function renderRoomEntry() {
  const creating = roomIntent === 'create';
  if (!$('network-entry').hidden) {
    $('network-dialog').dataset.stage = 'entry';
    $('network-title').textContent = creating ? 'Luo oma huone' : invitation ? `Liity huoneeseen ${$('network-code').value}` : 'Liity ystävän huoneeseen';
  }
  $('network-entry-copy').textContent = creating ? 'Luo huone ja jaa sen kutsulinkki ystävillesi.' : invitation ?
    'Valitse nimimerkki ja liity peliin.' : 'Kirjoita nimimerkkisi ja huoneen koodi. Voit myös liittää kutsulinkin.';
  $('network-code-row').hidden = creating || invitation;
  $('network-passcode-row').hidden = !creating || passcodeRequired === false;
  $('network-submit').textContent = entryPending ? 'Yhdistetään…' : creating ? 'Luo huone' : 'Liity huoneeseen';
  $('network-submit').disabled = !entryReady || !writeAccess || !networkAddress || entryPending;
  $('network-reload').hidden = !networkResolved || Boolean(networkAddress);
  for (const id of ['network-name', 'network-code', 'network-passcode', 'network-switch', 'network-resume']) $(id).disabled = entryPending;
  $('network-switch').hidden = invitation;
  $('network-switch').textContent = creating ? 'Liity sittenkin ystävän huoneeseen' : 'Luo oma huone';
  const sameServer = savedNetwork?.base === networkAddress;
  $('network-resume').hidden = !sameServer || (invitation && savedNetwork.room_code !== $('network-code').value);
  $('network-resume').textContent = savedNetwork ? `Jatka huoneessa ${savedNetwork.room_code}` : 'Jatka verkkopeliä';
}
function openRoomEntry({invite = false} = {}) {
  navigationToken++; roomIntent = 'join'; invitation = invite;
  $('network-entry').hidden = false; $('network-lobby').hidden = true;
  $('network-status').textContent = !networkResolved ? 'Yhdistetään verkkopeliin…' : !networkAddress ? 'Verkkopeli ei ole käytettävissä. Voit pelata botteja vastaan.' : '';
  $('network-local').hidden = false;
  renderRoomEntry(); openDialog('network-dialog');
}
async function enterLocalPlay() {
  if (!entryReady || !writeAccess || !localReadable || changingLocal || navigationPending || entryPending) return;
  navigationToken++; navigationPending = true; renderHome();
  try {
    awaitingNetworkGame = false; $('network-dialog').close();
    if (networkClient || savedNetwork?.active) await returnToLocal();
    else if (worker) { showGame(); render(); }
    else if (!lastSave || !packagedRuntimeIdentity || lastSave.identity === packagedRuntimeIdentity) boot(lastSave);
    else await resumeLocal(lastSave);
  } catch (error) { localFailure(error); }
  finally { navigationPending = false; renderHome(); }
}
const startup = detail => dispatchEvent(new CustomEvent('tuppi-startup', {detail}));
function post(type, extra = {}) {
  if (networkClient) {
    if (type === 'submit' && canSelect()) {
      const submittingClient = networkClient;
      busy = true; render(); submittingClient.submit(extra.action).catch(error => {
        if (networkClient !== submittingClient) return;
        status(error.message, true); submittingClient.close(); connectionState = {phase: 'failed'};
        renderConnection(); busy = true; render();
      });
    } else if (type === 'reveal-done' && view) {
      view.revealing = false; busy = !networkClient.connected || Boolean(networkClient.session.pending); render();
    }
    return;
  }
  if (!worker) return;
  if (!['delay', 'reveal-done'].includes(type)) { busy = true; keyboard.reset(); keyboardFeedback = ''; render(); }
  worker.postMessage({type, generation, ...extra});
}

function pickCard(card) {
  if (!canSelect() || !legalCards(view, bidContract).includes(card)) return;
  selectedCard = selectedCard === card ? null : card;
  keyboard.reset(); keyboardFeedback = ''; render();
}

function canSelect() { return writeAccess && screen === 'game' && !changingLocal && !busy && !pendingWrites && !saveFailed && view?.waitingHuman && !view.revealing; }
function selectContract(contract) {
  if (!canSelect() || !legalCards(view, contract).length) return;
  bidContract = contract;
  if (!legalCards(view, contract).includes(selectedCard)) selectedCard = null;
  keyboard.reset(); keyboardFeedback = ''; render();
}
function submitSelected() {
  if (!canSelect() || selectedCard === null) return;
  const action = cardAction(selectedCard, view.phase, bidContract);
  if (!view.legal.includes(action)) return;
  selectedCard = null; post('submit', {action});
}
function cancelReveal() {
  clearTimeout(revealTimer); revealTimer = null; revealFrame = null; revealKey = null;
}
function startReveal() {
  cancelReveal(); keyboard.reset(); selectedCard = null;
  const token = generation, bids = view.bids, started = performance.now();
  revealKey = `${view.dealNumber}:${JSON.stringify(bids)}`;
  const last = revealTiming.step * Math.max(0, bids.length - 1);
  const milestones = bids.slice(1).map((_, i) => (i + 1) * revealTiming.step)
    .concat([last + revealTiming.hold, last + revealTiming.hold + revealTiming.fade]);
  const tick = () => {
    if (token !== generation) return;
    const elapsed = performance.now() - started;
    revealFrame = bidRevealFrame(bids, elapsed);
    if (revealFrame.finished) { cancelReveal(); render(); post('reveal-done'); return; }
    render();
    const next = milestones.find(time => time > elapsed);
    revealTimer = setTimeout(tick, Math.max(1, next - elapsed));
  };
  tick();
}
function playedCard(play) {
  const wrap = document.createElement('div'); wrap.className = 'played-card';
  const label = document.createElement('span'); label.textContent = ['Sinä', 'Vasen', 'Pari', 'Oikea'][play.seat];
  wrap.append(cardFace(play.card), label); return wrap;
}
function renderStair(id, title, count) {
  const panel = $(id);
  if (panel.dataset.count === String(count)) return;
  panel.dataset.count = String(count);
  const heading = document.createElement('div'); heading.className = 'stair-title';
  heading.textContent = title;
  const number = document.createElement('span'); number.className = 'stair-count'; number.textContent = `${count}/13`; heading.append(number);
  const cards = document.createElement('div'); cards.className = 'stair-cards';
  if (!count) { const empty = document.createElement('span'); empty.className = 'stair-empty'; empty.textContent = 'Ei vielä tikkejä'; cards.append(empty); }
  for (let i = 0; i < Math.min(count, 13); i++) {
    const marker = document.createElement('span'); marker.className = 'trick-marker'; marker.setAttribute('aria-hidden', 'true');
    marker.style.setProperty('--marker-index', i);
    if (i % 2) marker.style.transform = 'rotate(90deg)'; cards.append(marker);
  }
  panel.setAttribute('aria-label', `${title}, ${count} tikkiä 13:sta`); panel.replaceChildren(heading, cards);
}
function layoutHand() {
  const compact = globalThis.matchMedia?.('(max-width: 600px) and (orientation: portrait)').matches ?? false;
  const fontSize = globalThis.getComputedStyle ? parseFloat(getComputedStyle(document.documentElement).fontSize) : 16;
  handView.layout({width: $('hand').parentElement.clientWidth - 8, compact, expanded: expandedHand,
    scale: compact || expandedHand ? fontSize / 16 : 1});
}
const handView = new HandView($('hand'), card => cardFace(card, true), (element, card, state) => {
  const legal = !state.allowed.length || state.allowed.includes(card);
  element.classList.toggle('illegal', !legal);
  element.classList.toggle('selected', selectedCard === card);
  element.disabled = !canSelect() || !state.allowed.includes(card);
  element.setAttribute('aria-pressed', String(selectedCard === card));
  element.setAttribute('aria-label', `${suitNames[Math.floor(card / 13)]} ${cardRank(card)}${legal ? '' : ', ei sallittu tällä vuorolla'}`);
});
function seatInfo(seat) {
  const nickname = networkClient?.session?.lobby?.seats.find(s => networkSeat(s.seat, networkClient.session.seat) === seat)?.display_name;
  return seatPresentation(view, seat, nickname || seatNames[seat]);
}
function renderDetails() {
  if (!view) return;
  if (detailSeat !== null) {
    const info = seatInfo(detailSeat);
    $('seat-detail-title').textContent = info.name;
    $('seat-detail-copy').textContent = info.detail;
  }
  const summary = view.startingHandSummary;
  $('hand-detail-copy').textContent = summary ?
    `Alkukäsi: ${summary.suitLengths.map((count, suit) => `${suitNames[suit]} ${count}`).join(', ')}. HCP ${summary.highCardPoints}. HCP laskee kuvakorttipisteet: ässä 4, kuningas 3, rouva 2 ja jätkä 1.` :
    'Alkukäden yhteenveto ei ole saatavilla tässä pelissä.';
}

function renderHistory(completed) {
  const rows = completed.toReversed().map(deal => {
    if (!historyRows.has(deal.index)) {
      const row = document.createElement('div'); row.className = 'history-row';
      const label = document.createElement('span'), button = document.createElement('button');
      button.textContent = 'Toista jako'; button.onclick = () => openReplay(row.deal);
      row.append(label, button); historyRows.set(deal.index, row);
    }
    const row = historyRows.get(deal.index); row.deal = deal;
    row.children[0].textContent = `Jako ${deal.index + 1} · ${deal.result.soolaaja >= 0 ? 'SOOLI' : deal.result.contract ? 'RAMI' : 'NOLO'} · ${deal.result.winnerTeam === 0 ? 'meille' : 'vastustajille'} ${deal.result.points} p`;
    row.children[1].setAttribute('aria-label', `Toista jako ${deal.index + 1}`);
    return row;
  });
  const visible = new Set(completed.map(deal => deal.index));
  for (const id of historyRows.keys()) if (!visible.has(id)) historyRows.delete(id);
  const container = $('history');
  if (rows.length !== container.children.length || rows.some((row, i) => row !== container.children[i])) container.replaceChildren(...rows);
  if (!rows.length) container.textContent = 'Valmiit jaot ja niiden toisto ilmestyvät tähän.';
  $('history-count').textContent = `${completed.length} ${completed.length === 1 ? 'jako' : 'jakoa'}`;
}

function render() {
  renderLocalChoices(); renderNetworkControls(); renderHome();
  $('export').disabled = !lastSave;
  for (const id of ['worlds', 'pacing', 'new-game', 'import']) $(id).disabled = Boolean(networkClient);
  for (const id of ['worlds', 'new-game', 'import']) $(id).disabled ||= changingLocal || !writeAccess || !localReadable;
  if (!view) {
    $('history-section').hidden = true;
    handView.render([], {allowed: []}); layoutHand(); $('bid-reveal').replaceChildren(); $('trick').replaceChildren(); delete $('trick').dataset.cards;
    $('own-seat-details').disabled = $('hand-details').disabled = true;
    $('starting-hand').hidden = true;
    for (const id of ['bid-controls', 'card-controls', 'sooli-controls', 'next-controls', 'trick-panel']) $(id).hidden = true;
    $('action-row').classList.toggle('card-action', false);
    for (const name of ['rami', 'sooli', 'revealing']) $('table').classList.toggle(name, false);
    for (let seat = 0; seat < 4; seat++) {
      const panel = $(`seat-${seat}`); panel.classList.toggle('active', false);
      panel.querySelector('.seat-shown').textContent = ''; panel.querySelector('.seat-role').textContent = '';
    }
    return;
  }
  $('our-score').textContent = view.score0; $('their-score').textContent = view.score1;
  $('history-section').hidden = !view.completed.length && !view.terminal;
  $('deal-label').textContent = `Jako ${view.dealNumber}`;
  const pending = Boolean(revealFrame?.contractPending), revealing = Boolean(view.revealing);
  $('phase-title').textContent = pending || view.phase === 0 ? 'Tarjoukset (lukitut)' :
    ['Tarjoukset (lukitut)', 'Tikinpeluu', view.terminal ? 'Ottelu päättyi' : 'Jako valmis', 'Pelataanko sooli?', 'Soolin kortinvaihto', 'Soolin kortinvaihto', 'Sooli · ässä pienin'][view.phase];
  $('contract').textContent = view.phase === 0 || pending ? 'TARJOUS' : view.soolaaja >= 0 ? 'SOOLI' : view.contract ? 'RAMI' : 'NOLO';
  for (const id of ['table', 'contract']) {
    $(id).classList.toggle('rami', !pending && view.contract === 1 && view.soolaaja < 0);
    $(id).classList.toggle('sooli', view.soolaaja >= 0);
  }
  $('table').classList.toggle('revealing', revealing);
  renderStair('our-tricks', 'SINÄ + PARI', view.tricks0);
  renderStair('their-tricks', 'VASTUSTAJAT', view.tricks1);
  for (let seat = 0; seat < 4; seat++) {
    const panel = $(`seat-${seat}`);
    const name = panel.querySelector('.seat-name');
    const info = seatInfo(seat);
    if (name) { name.textContent = info.name; name.setAttribute('aria-label', `${info.name}: ${info.detail}${info.active ? ' · Vuorossa' : ''}. Näytä tiedot`); }
    panel.classList.toggle('active', info.active);
    panel.querySelector('.seat-cards').textContent = [info.count, info.position].filter(Boolean).join(' · ');
    panel.querySelector('.seat-shown').textContent = info.shown;
    panel.querySelector('.seat-role').textContent = info.role;
  }
  const own = seatInfo(0);
  $('own-seat-details').disabled = $('hand-details').disabled = false;
  $('own-seat-details').textContent = own.name;
  $('own-seat-meta').textContent = [own.position, own.role, own.shown].filter(Boolean).join(' · ');
  $('own-seat-details').setAttribute('aria-label', `${own.name}: ${own.detail}. Näytä tiedot`);
  renderDetails();
  $('bid-reveal').classList.toggle('fading', Boolean(revealFrame?.fading));
  const visibleBids = revealFrame?.cards ?? [], container = $('bid-reveal');
  if (!visibleBids.length) container.replaceChildren();
  // Keep already visible cards mounted so only each new bid animates.
  for (const bid of visibleBids.slice(container.children.length)) {
    const wrap = document.createElement('div'); wrap.className = 'revealed-bid'; wrap.dataset.seat = bid.seat;
    const seat = document.createElement('span'); seat.className = 'reveal-seat'; seat.textContent = seatNames[bid.seat];
    const title = document.createElement('span'); title.className = `reveal-title ${bid.contract ? 'rami' : ''}`; title.textContent = bid.contract ? 'RAMI' : 'NOLO';
    wrap.setAttribute('aria-label', `${seatNames[bid.seat]}: ${title.textContent}, ${cardLabel(bid.card)}`);
    wrap.append(title, cardFace(bid.card, false, false, false, true, true), seat); container.append(wrap);
  }
  const size = view.trickSize, count = view.history.length;
  const trickStart = count ? count - (count % size || size) : 0;
  $('trick-panel').hidden = !count || revealing;
  $('trick-title').textContent = count % size ? 'NYKYINEN TIKKI' : 'VIIMEISIN TIKKI';
  const plays = view.history.slice(trickStart), trickKey = plays.map(play => `${play.seat}:${play.card}`).join('|');
  if ($('trick').dataset.cards !== trickKey) {
    $('trick').replaceChildren(...plays.map(playedCard)); $('trick').dataset.cards = trickKey;
  }
  const previousStart = count - (count % size || size) - size;
  $('previous-trick').hidden = previousStart < 0;
  $('previous-trick').textContent = count % size ? 'Näytä viimeisin tikki' : 'Näytä edellinen tikki';
  $('bidding-banner').hidden = view.phase !== 0 || revealing;
  let prompt;
  if (revealing) prompt = 'Tarjoukset paljastetaan – peli jatkuu, kun kortit häviävät.';
  else if (view.phase === 2) prompt = view.terminal ? (view.score0 >= 52 ? 'Sinä ja parisi voititte ottelun.' : 'Vastustajat voittivat ottelun.') : 'Jako päättyi.';
  else if (busy || view.thinking) prompt = view.actor === 0 ? 'Käsitellään siirtoa…' : `${seatNames[view.actor]} miettii…`;
  else if (view.phase === 0) prompt = 'Lukitse tarjous';
  else if (view.phase === 3) prompt = 'Haluatko pelata soolia?';
  else if (view.phase === 4) prompt = 'Anna yksi kortti parillesi.';
  else if (view.phase === 5) prompt = 'Palauta yksi kortti soolin pelaajalle.';
  else prompt = 'Sinun vuorosi pelata';
  if (!revealing && view.prompt) prompt = view.prompt;
  $('prompt').textContent = prompt;
  $('table-status').textContent = view.phase === 0 && canSelect() ? 'Sinun vuorosi tarjota' : prompt;
  $('table-status').classList.toggle('our-turn', canSelect());
  $('bid-controls').hidden = view.phase !== 0 || revealing;
  $('card-controls').hidden = ![1, 4, 5, 6].includes(view.phase) || view.actor !== 0 || revealing;
  $('action-row').classList.toggle('card-action', !$('card-controls').hidden);
  const selectedLabel = selectedCard === null ? 'kortti' : cardLabel(selectedCard);
  $('play-card').textContent = `${view.phase === 4 ? 'Anna' : view.phase === 5 ? 'Palauta' : 'Pelaa'} ${selectedLabel}`;
  $('play-card').disabled = !canSelect() || selectedCard === null || !legalCards(view, bidContract).includes(selectedCard);
  $('sooli-controls').hidden = view.phase !== 3 || view.actor !== 0 || revealing;
  $('next-controls').hidden = Boolean(networkClient) || view.phase !== 2 || Boolean(view.terminal);
  $('lock-bid').textContent = bidContract ? 'Lukitse RAMI' : 'Lukitse NOLO';
  $('lock-bid').disabled = !canSelect() || selectedCard === null || !view.legal.includes(52 + bidContract * 52 + selectedCard);
  $('next-deal').disabled = busy;
  document.querySelectorAll('[data-contract]').forEach(button => {
    const selected = Number(button.dataset.contract) === bidContract;
    button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
    button.disabled = !canSelect() || !legalCards(view, Number(button.dataset.contract)).length;
  });
  document.querySelectorAll('[data-action]').forEach(button => { button.disabled = !canSelect(); });
  $('hand-count').textContent = `${view.hand.length} korttia`;
  const summary = view.startingHandSummary;
  $('starting-hand').hidden = !summary;
  if (summary) {
    const lengths = summary.suitLengths.map((count, suit) => {
      const item = document.createElement('span'); item.className = `suit-length suit-${suit}`;
      item.innerHTML = `<span class="summary-suit" aria-hidden="true">${suitSVG(suit)}</span>`;
      const number = document.createElement('span'); number.textContent = count; item.append(number); return item;
    });
    const points = document.createElement('span'); points.className = 'hand-points'; points.textContent = `HCP ${summary.highCardPoints}`;
    $('starting-hand').replaceChildren(...lengths, points);
    $('starting-hand').setAttribute('aria-label', `Alkukäsi: ${summary.suitLengths.map((count, suit) => `${suitNames[suit]} ${count}`).join(', ')}, HCP ${summary.highCardPoints}`);
  }
  const allowedCards = legalCards(view, bidContract);
  handView.render(sortedHand(view), {allowed: allowedCards});
  layoutHand();
  let selectionInfo = selectedCard === null ? view.phase === 0 ? 'Valitse kädestä näytettävä kortti.' : 'Valitse laillinen kortti kädestä.' : `Valittu kortti: ${cardLabel(selectedCard)}`;
  if (view.phase === 0 && selectedCard !== null) {
    const red = selectedCard < 26, rank = selectedCard % 13, ordinary = rank >= 1 && rank <= 7;
    if (red !== Boolean(bidContract)) selectionInfo += ` Vastaväri: ilmoitat ${bidContract ? 'RAMIn' : 'NOLOn'} tällä kortilla.`;
    else if (!ordinary) selectionInfo += ' Kädessäsi ei ole tavallista näyttökorttia. Sopimus ilmoitetaan valitulla kortilla.';
  }
  $('selection-info').textContent = canSelect() && view.phase !== 3 && (view.phase === 0 || selectedCard === null) ? selectionInfo : '';
  $('selection-info').hidden = !$('selection-info').textContent;
  $('keyboard-prompt').textContent = canSelect() && view.phase !== 3 ? keyboardFeedback || keyboard.prompt ||
    `Pikanäppäimet: ${view.phase === 0 ? 'N NOLO · R RAMI · ' : ''}H/D/C/S maa · arvo · ←/→ valinta · Enter vahvistaa` : '';
  $('keyboard-prompt').classList.toggle('armed', Boolean(keyboard.prompt || keyboardFeedback));
  renderHistory(view.completed);
  const result = matchSummary(view);
  // The request waits for the room's lock, which the server holds until it has credited this match.
  if (result && networkClient && !matchEndCounted) { matchEndCounted = true; refreshLeaderboard(true); }
  if (!result) matchEndCounted = false;
  $('summary-leaderboard').hidden = !result || !networkClient || !leaderboardEntries?.length;
  $('match-summary').hidden = !result;
  if (result) {
    $('match-summary-title').textContent = result.title;
    $('match-summary-lines').replaceChildren(...result.lines.map(line => {
      const item = document.createElement('li'); item.textContent = line; return item;
    }));
  }
  announceTurn();
}
// Opt-in turn sound: once each time it becomes this player's turn.
function announceTurn() {
  const key = canSelect() ? `${view.dealNumber}:${view.phase}:${view.history.length}:${view.legal.join(',')}` : null;
  if (key && key !== lastTurnKey && preferences.turnSound && turnAudio) {
    try {
      const tone = turnAudio.createOscillator(), gain = turnAudio.createGain();
      tone.frequency.value = 880; gain.gain.value = 0.04;
      tone.connect(gain).connect(turnAudio.destination); tone.start(); tone.stop(turnAudio.currentTime + 0.12);
    } catch {}
  }
  lastTurnKey = key;
}
function enableTurnAudio() {
  // Browsers allow audio only after a user gesture, such as ticking the option.
  try { turnAudio ??= new (globalThis.AudioContext ?? globalThis.webkitAudioContext)(); turnAudio.resume?.(); } catch { turnAudio = null; }
}

function boot(save = null, {replace = false, engine = new URL('./engine.ba679a5bb2e66563.mjs', import.meta.url), identity = save?.identity ?? packagedRuntimeIdentity} = {}) {
  if (!writeAccess) { status('Peli on avoinna toisessa välilehdessä tai selain ei tue turvallista paikallistallennusta.', true); return; }
  if (save) lastSave = structuredClone(save);
  activeIdentity = identity;
  replacementPending ||= replace;
  let replaceOnCheckpoint = replacementPending;
  showGame();
  $('saved').textContent = 'Pelisi tallentuu tälle laitteelle.';
  $('mode-label').textContent = '· Paikallinen peli';
  if (!offlineStarted) { offlineStarted = true; offline.start(); }
  worker?.terminate(); generation++; cancelReveal(); keyboard.reset(); keyboardFeedback = '';
  busy = true; view = null; selectedCard = null; bidContract = 0;
  pendingWrites = 0; saveFailed = false;
  startup({begin: true, message: 'Ladataan paikallinen botti…'});
  $('retry').hidden = true; $('prompt').textContent = 'Ladataan paikallinen botti…';
  status('Botti toimii omalla laitteellasi.'); render();
  const currentGeneration = generation;
  worker = new Worker(engine, {type: 'module'});
  const targetWorker = worker;
  worker.onmessage = ({data}) => {
    if (data.generation !== generation) return;
    if (data.type === 'checkpoint') {
      lastSave = data.save; pendingWrites++; $('saved').textContent = 'Tallennetaan…'; render();
      saveQueue = saveQueue.catch(() => {}).then(async () => {
        const replaced = replaceOnCheckpoint;
        if (replaced) recoveryKnown = false;
        await store(data.save, {replace: replaced});
        replaceOnCheckpoint = false;
        replacementPending = false;
        if (currentGeneration === generation) {
          pendingWrites--; durableIdentity = data.save.identity; saveIdentityKnown = true;
          $('saved').textContent = pendingWrites ? 'Tallennetaan…' : 'Tallennettu tälle laitteelle';
          if (Number.isInteger(data.checkpointId)) targetWorker.postMessage({type: 'checkpoint-saved', generation, checkpointId: data.checkpointId});
          render();
          if (replaced) await refreshRecoveryCopy();
        }
      }).catch(error => { if (currentGeneration === generation) {
        pendingWrites--; saveFailed = true;
        if (Number.isInteger(data.checkpointId)) targetWorker.postMessage({type: 'checkpoint-saved', generation, checkpointId: data.checkpointId, error: error.message});
        $('saved').textContent = 'Tallennus ei onnistunut'; status(`Lataa varmuuskopio asetuksista. ${error.message}`, true);
        $('retry').hidden = false; render(); showLocalChoices(`Tallennus ei onnistunut. Nykyinen peli ja palautuskopio säilyvät ennallaan. ${error.message}`);
      }});
    } else if (data.type === 'view') {
      startup({ready: true});
      const old = view;
      view = data.view; busy = view.thinking;
      if (old?.dealNumber !== view.dealNumber && view.phase === 0) bidContract = legalCards(view, 0).length ? 0 : 1;
      if (!view.waitingHuman || old?.dealNumber !== view.dealNumber || old?.phase !== view.phase) {
        selectedCard = null; keyboard.reset(); keyboardFeedback = '';
      }
      if (view.revealing && revealKey !== `${view.dealNumber}:${JSON.stringify(view.bids)}`) startReveal();
      else render();
    } else if (data.type === 'loading') {
      status(data.message); startup({message: data.message});
    } else if (data.type === 'ready') {
      busy = false; render(); status(''); offline.refresh();
    } else if (data.type === 'error') {
      if (!view) startup({error: data.message});
      else { status(data.message, true); $('retry').hidden = !lastSave; }
      busy = false; render();
    }
  };
  worker.onerror = event => {
    if (currentGeneration !== generation || worker !== targetWorker) return;
    busy = false;
    if (!view) startup({error: event.message || 'Paikallisen pelimoottorin lataus epäonnistui.'});
    else { status('Pelin laskenta keskeytyi. Voit jatkaa viimeisestä tallennetusta siirrosta.', true); $('retry').hidden = !lastSave; }
    render();
  };
  const worlds = save?.worlds ?? Number($('worlds').value); $('worlds').value = String(worlds);
  worker.postMessage({type: 'init', generation, worlds, delay: Number($('pacing').value), save});
}

document.querySelectorAll('[data-contract]').forEach(button => { button.onclick = () => selectContract(Number(button.dataset.contract)); });
document.querySelectorAll('[data-action]').forEach(button => { button.onclick = () => {
  const action = Number(button.dataset.action);
  if (canSelect() && view.legal.includes(action)) post('submit', {action});
}});
$('lock-bid').onclick = submitSelected;
$('play-card').onclick = submitSelected;
$('next-deal').onclick = () => { if (!busy && view?.phase === 2 && !view.terminal) post('next'); };
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.metaKey || event.ctrlKey || event.altKey ||
      event.target?.closest('input, textarea, select, [contenteditable="true"], #settings, dialog, .masthead, .history-section') ||
      document.querySelector('dialog[open]') || !canSelect()) return;
  if (event.key === 'Enter') {
    if (selectedCard === null || !legalCards(view, bidContract).includes(selectedCard)) return;
    event.preventDefault(); submitSelected(); return;
  }
  if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    const card = keyboard.adjacent(selectedCard, event.key === 'ArrowLeft' ? -1 : 1, view, bidContract);
    if (card === null) return;
    selectedCard = card; keyboardFeedback = `Näppäimistö: valittu ${cardLabel(card)}. Enter vahvistaa.`;
  } else {
    const action = keyboard.handle(event.key, view, bidContract);
    if (!action) return;
    keyboardFeedback = '';
    if (action.type === 'contract') selectContract(action.contract);
    else if (action.type === 'card') selectedCard = action.card;
    else if (action.type === 'unavailable') keyboardFeedback = `Kortti ${cardLabel(action.card)} ei ole sallittu tässä tilanteessa.`;
  }
  event.preventDefault(); render();
});
new ResizeObserver(layoutHand).observe($('hand').parentElement);
globalThis.matchMedia?.('(max-width: 600px) and (orientation: portrait)').addEventListener('change', layoutHand);
function showSeatDetails(seat) {
  if (!view) return;
  detailSeat = seat; renderDetails(); openDialog('seat-details');
}
for (let seat = 0; seat < 4; seat++) $(`seat-${seat}`).querySelector('.seat-name').onclick = () => showSeatDetails(seat);
$('own-seat-details').onclick = () => showSeatDetails(0);
$('hand-details').onclick = () => { renderDetails(); openDialog('hand-detail'); };
$('close-seat-details').onclick = () => { $('seat-details').close(); detailSeat = null; };
$('close-hand-detail').onclick = () => $('hand-detail').close();
$('hand-layout').onclick = () => {
  expandedHand = !expandedHand;
  preferences = savePreferences({...preferences, expandedHand});
  $('hand-layout').setAttribute('aria-pressed', String(expandedHand));
  $('hand-layout').textContent = expandedHand ? 'Tiivistä kortit' : 'Levitä kortit';
  layoutHand();
};
$('hand-layout').setAttribute('aria-pressed', String(expandedHand));
$('hand-layout').textContent = expandedHand ? 'Tiivistä kortit' : 'Levitä kortit';
$('settings-toggle').onclick = () => {
  if ($('settings').open) { $('settings').close(); return; }
  $('settings-status').textContent = '';
  $('turn-sound').checked = preferences.turnSound;
  openDialog('settings'); $('settings-toggle').setAttribute('aria-expanded', 'true'); refreshStorage();
};
$('close-settings').onclick = () => $('settings').close();
$('settings').onclose = () => {
  if (!$('settings').open) { $('settings').hidden = true; $('settings-toggle').setAttribute('aria-expanded', 'false'); }
};
$('pacing').onchange = () => post('delay', {delay: Number($('pacing').value)});
$('new-game').onclick = () => newLocalMatch();
$('worlds').onchange = async () => { if (!await newLocalMatch() && lastSave) $('worlds').value = String(lastSave.worlds); };
$('retry').onclick = () => { if (writeAccess) resumeLocal(lastSave).catch(localFailure); else location.reload(); };
$('export').onclick = async () => {
  if (!lastSave) return;
  const blob = new Blob([JSON.stringify(await envelope(lastSave), null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = 'tuppi-tallennus.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$('import').onchange = async event => {
  try {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 10 * 1024 * 1024) throw new Error('Tallennustiedosto on liian suuri.');
    const save = await unwrap(JSON.parse(await file.text()));
    if (confirm('Avataanko tallennus? Nykyinen ottelu siirtyy palautuskopioksi ja korvaa aiemman palautuskopion.')) {
      await resumeLocal(save, true); $('settings').close();
    }
  } catch (error) { status(error.message, true); }
  event.target.value = '';
};

// Recovery always uses the current interface. A compatible older engine stays
// in its own module worker; its runtime, search budget and RNG save are intact.
function renderLocalChoices() {
  const blocked = changingLocal || Boolean(networkClient) || !writeAccess;
  const currentIdentity = offline.activeStatus?.identity ?? packagedRuntimeIdentity;
  $('local-version').textContent = activeIdentity && activeIdentity !== currentIdentity ?
    'Käytössä: tallennuksen aiempi peliversio' : 'Käytössä: nykyinen asennettu peliversio';
  $('local-save-version').textContent = lastSave ? lastSave.identity === currentIdentity ?
    'Tallennettu ottelu käyttää nykyistä asennettua peliversiota.' : 'Tallennettu ottelu tarvitsee aiemman peliversion.' : 'Ei avattua ottelua.';
  $('local-update').textContent = offline.state.updateReady ? 'Päivitys odottaa. Sulje kaikki Tuppi-ikkunat ja avaa peli uudelleen, jotta se tulee käyttöön.' : '';
  $('local-continue').disabled = blocked || !lastSave;
  $('local-new').disabled = blocked || !localReadable;
  $('local-load').disabled = blocked;
  $('local-repair').disabled = blocked || !offline.serviceWorker;
  $('local-export').disabled = !lastSave && !hasLocalRecord;
  $('previous-export').disabled = !previousRecord;
  $('previous-restore').disabled = blocked || !previousSave || !localReadable;
  $('previous-status').textContent = previousSave ? 'Yksi aiempi ottelu on palautettavissa tällä laitteella.' :
    previousRecord ? 'Palautuskopion tarkistus epäonnistui. Voit ladata sen talteen.' : 'Ei aiempaa palautuskopiota.';
}
function showLocalChoices(message = '') {
  startup({ready: true});
  if (!worker && !view) {
    $('prompt').textContent = $('table-status').textContent = 'Valitse tallennus tai aloita uusi ottelu.';
  }
  if (message) $('local-status').textContent = message;
  renderLocalChoices();
  if (!$('local-games').open) openDialog('local-games');
}
function localFailure(error) {
  status(error.message, true); showLocalChoices(error.message);
  if (screen === 'home') $('home-recovery').hidden = false;
}
async function refreshRecoveryCopy() {
  recoveryKnown = false;
  try {
    previousRecord = await readLocalRecord('previous'); previousSave = null;
    if (previousRecord) previousSave = await unwrap(previousRecord);
    recoveryKnown = true;
  } catch { /* Keep raw data exportable; refuse cache cleanup while unverified. */ }
  renderLocalChoices();
}
async function reloadLocalSave() {
  // Never interpret a failed database read as an empty device.
  entryReady = false; localReadable = false; saveIdentityKnown = false;
  const record = await readLocalRecord(); localReadable = true; hasLocalRecord = Boolean(record);
  lastSave = record ? await unwrap(record) : null;
  replacementPending = false;
  durableIdentity = lastSave?.identity ?? null; saveIdentityKnown = true;
  await refreshRecoveryCopy();
  entryReady = writeAccess;
  $('home-status').textContent = ''; $('home-status').classList.toggle('error', false); $('home-recovery').hidden = true;
}
async function resumeLocal(save, replace = false) {
  if (!writeAccess || changingLocal || networkClient) return;
  if (replace && !localReadable) throw new Error('Lue tämän laitteen tallennus ensin uudelleen.');
  changingLocal = true; render();
  try {
    let engine, identity = save?.identity ?? packagedRuntimeIdentity;
    repairIdentity = save?.identity ?? packagedRuntimeIdentity;
    if (!save && replace) {
      const latest = await offline.latestInstalled();
      if (latest && latest.identity !== packagedRuntimeIdentity) {
        repairIdentity = latest.identity;
        if (!latest.engine) throw new Error('Nykyisen peliversion tiedostoja puuttuu. Palauta pelitiedostot tai sulje kaikki Tuppi-ikkunat ja avaa peli uudelleen.');
        engine = new URL(latest.engine, import.meta.url); identity = latest.identity;
      }
    }
    if (save && packagedRuntimeIdentity && save.identity !== packagedRuntimeIdentity) {
      if (!offlineStarted) { offlineStarted = true; await offline.start(); }
      const release = await offline.release(save.identity);
      if (release?.launch && !release.engine && !replace) {
        // Very early packages predate the immutable engine inventory.
        location.replace(new URL(release.launch, import.meta.url)); return;
      }
      if (!release?.engine) throw new Error('Tallennuksen aiempi pelipaketti puuttuu. Palauta pelitiedostot verkkoyhteydellä tai lataa tallennus talteen. Voit myös aloittaa uuden ottelun.');
      engine = new URL(release.engine, import.meta.url);
    }
    worker?.terminate(); generation++; cancelReveal(); busy = true;
    await saveQueue;
    $('local-games').close();
    boot(save, {replace, engine, identity});
  } finally { changingLocal = false; render(); }
}
async function newLocalMatch() {
  if (!writeAccess || !localReadable || changingLocal || networkClient) return false;
  const replacing = Boolean(lastSave || hasLocalRecord);
  if (replacing && !confirm('Aloitetaanko uusi ottelu? Nykyinen ottelu siirtyy palautuskopioksi ja korvaa aiemman palautuskopion.')) return false;
  try { await resumeLocal(null, replacing); $('settings').close(); return true; }
  catch (error) { localFailure(error); return false; }
}
async function downloadRecord(record, name) {
  if (!record) throw new Error('Tallennusta ei löydy tältä laitteelta.');
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('local-manage').onclick = async () => { await refreshRecoveryCopy(); showLocalChoices(); };
$('close-local-games').onclick = () => $('local-games').close();
$('local-new').onclick = () => newLocalMatch();
$('local-continue').onclick = () => resumeLocal(lastSave).catch(localFailure);
$('local-load').onclick = async () => {
  if (changingLocal || !writeAccess || networkClient) return;
  changingLocal = true; worker?.terminate(); generation++; cancelReveal(); busy = true; render();
  try { await saveQueue; await reloadLocalSave(); showLocalChoices(lastSave ? 'Tallennus luettu. Voit jatkaa ottelua.' : 'Tältä laitteelta ei löydy tallennusta. Avaa varmuuskopio asetuksista tai aloita uusi ottelu.'); }
  catch (error) { localFailure(error); }
  finally { changingLocal = false; render(); }
};
$('local-export').onclick = async () => {
  try { await downloadRecord(lastSave ? await envelope(lastSave) : await readLocalRecord(), 'tuppi-tallennus.json'); }
  catch (error) { localFailure(error); }
};
$('previous-export').onclick = () => downloadRecord(previousRecord, 'tuppi-aiempi-ottelu.json').catch(localFailure);
$('previous-restore').onclick = async () => {
  if (confirm('Palautetaanko aiempi ottelu? Nykyinen ottelu siirtyy sen tilalle palautuskopioksi.'))
    try { await resumeLocal(previousSave, true); } catch (error) { localFailure(error); }
};
$('local-repair').onclick = async () => {
  if (changingLocal || !writeAccess || networkClient) return;
  changingLocal = true; renderLocalChoices(); $('local-status').textContent = 'Tarkistetaan ja palautetaan pelitiedostoja…';
  try {
    if (!offlineStarted) { offlineStarted = true; await offline.start(); }
    await offline.repair(repairIdentity);
    $('local-status').textContent = 'Pelitiedostot palautettu. Voit jatkaa tallennettua ottelua.';
  } catch (error) { $('local-status').textContent = error.message; }
  finally { changingLocal = false; renderLocalChoices(); }
};

function openReplay(deal) { replayDeal = deal; replayIndex = 0; showReplay(); openDialog('replay'); }
function showReplay() {
  const size = replayDeal.result.trickSize, total = Math.ceil(replayDeal.history.length / size);
  const plays = replayDeal.history.slice(replayIndex * size, (replayIndex + 1) * size);
  $('replay-title').textContent = `Jako ${replayDeal.index + 1}`;
  $('replay-trick').replaceChildren(...plays.map(playedCard));
  $('replay-info').textContent = `Tikki ${replayIndex + 1} / ${total} · ${plays.map(play => seatNames[play.seat]).join(' → ')}`;
  $('replay-prev').disabled = replayIndex <= 0; $('replay-next').disabled = replayIndex >= total - 1;
}
$('replay-prev').onclick = () => { replayIndex--; showReplay(); };
$('replay-next').onclick = () => { replayIndex++; showReplay(); };
$('close-replay').onclick = () => $('replay').close();
$('previous-trick').onclick = () => {
  if (!view?.history.length) return;
  const size = view.trickSize, count = view.history.length, start = count - (count % size || size) - size;
  if (start >= 0) openReplay({index: view.dealNumber - 1, result: {trickSize: size}, history: view.history.slice(start, start + size)});
};

async function ownMatch(lock) {
  if (!lock) {
    startup({error: 'Peli on avoinna toisessa välilehdessä. Sulje se ja yritä uudelleen.'});
    $('prompt').textContent = 'Peli on avoinna toisessa välilehdessä.';
    status('Sulje toinen pelivälilehti ja yritä uudelleen.'); $('retry').hidden = false;
    return;
  }
  writeAccess = true;
  const untilLeave = new Promise(resolve => addEventListener('pagehide', () => {
    writeAccess = false; entryReady = false; navigationToken++; generation++;
    cancelReveal(); worker?.terminate(); networkClient?.close(); renderHome(); resolve();
  }, {once: true}));
  try {
    startup({message: 'Avataan tämän laitteen tallennus…'});
    await reloadLocalSave(); if (!writeAccess) return;
    const saved = lastSave;
    if (networkEnabled) try { savedNetwork = await loadNetwork(); } catch (error) { $('network-status').textContent = error.message; }
    if (!writeAccess) return;
    $('network-code').value = (networkEntry.get('room') || '').toUpperCase();
    entryReady = true; $('home-status').textContent = ''; renderHome(); startup({ready: true});
    if (networkEnabled && (startsOnline || savedNetwork?.active)) {
      $('network-local').hidden = false;
      busy = true; render();
      openRoomEntry({invite: /^[A-Z0-9]{6}$/.test($('network-code').value)});
      const route = navigationToken;
      await networkReady;
      if (route === navigationToken && savedNetwork?.active && savedNetwork.base === networkAddress &&
          (!networkEntry.get('room') || savedNetwork.room_code === networkEntry.get('room').toUpperCase())) await startNetwork('resume');
    } else if (!networkEnabled || networkEntry.get('play') === 'offline') {
      if (saved && packagedRuntimeIdentity && saved.identity !== packagedRuntimeIdentity) {
        if (!offlineStarted) { offlineStarted = true; await offline.start(); }
        repairIdentity = saved.identity;
        showLocalChoices('Tallennettu ottelu käyttää aiempaa peliversiota. Jatka sillä tai aloita uusi ottelu tämän julkaisun peliversiolla.');
      } else boot(saved);
    } else showHome();
  } catch (error) { localFailure(error); }
  await untilLeave;
}
addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
const offline = new OfflineSetup({paths: [globalThis.location?.pathname ?? '/', new URL(import.meta.url).pathname,
  new URL('./engine.ba679a5bb2e66563.mjs', import.meta.url).pathname], onChange: state => {
  const downloading = state.state === 'downloading', failed = state.state === 'error';
  const bytes = (state.completedBytes ?? 0) + (state.receivedBytes ?? 0), total = state.totalBytes ?? 1;
  $('offline-progress').max = total; $('offline-progress').value = bytes;
  $('offline-progress').hidden = !downloading;
  $('offline-download').hidden = !downloading && !failed;
  $('offline-retry').hidden = !failed;
  $('offline-prepare').hidden = offlineStarted || state.ready;
  $('offline-status').textContent = state.updateReady ? 'Päivitys valmis: sulje Tuppi ja avaa se uudelleen.' :
    downloading ? `Offline-paketti ${Math.min(100, Math.floor(bytes / total * 100))} % · ${(bytes / 1e6).toFixed(1)} / ${(total / 1e6).toFixed(1)} Mt` :
    failed ? `${state.error ?? 'Lataus jäi kesken.'}${state.ready ? ' Aiempi offline-peli on käytettävissä.' : ''}` :
    state.ready ? 'Valmis pelaamaan ilman verkkoyhteyttä' : state.error ?? 'Lataa peli tälle laitteelle, kun haluat pelata ilman verkkoa.';
}});
$('offline-retry').onclick = () => offline.retry();
async function refreshStorage(requestPersistence = false) {
  const health = await storageHealth({requestPersistence});
  $('persist-storage').disabled = !health.canRequest || health.persistent === true;
  $('storage-status').textContent = health.persistent === true ? 'Selain on myöntänyt pysyvän tallennustilan. Voit silti ladata varmuuskopion.' :
    'Tallennus on tämän selaimen tilassa. Lataa varmuuskopio; selain voi vapauttaa tilaa poistamalla tietoja.';
  if (health.available !== null) $('storage-status').textContent += ` Arvioitu vapaa tila: ${(health.available / 1e6).toFixed(0)} Mt.`;
  if (requestPersistence && health.persistent === false) $('storage-status').textContent += ' Pysyvää tilaa ei myönnetty; nykyinen peli säilyy ennallaan.';
  return health;
}
$('persist-storage').onclick = () => refreshStorage(true);
if (navigator.locks) navigator.locks.request('tuppi-current-match', {mode: 'exclusive', ifAvailable: true}, ownMatch)
  .catch(error => { writeAccess = false; startup({error: error.message}); });
else startup({error: 'Selain ei tue tämän peliversion tallennusta. Päivitä selain ja avaa peli HTTPS- tai localhost-osoitteesta.'});
// Retain only after the saved identity is known and the active release is ready.
// A waiting update is never activated or pruned beneath an active match.
addEventListener('online', () => { networkClient?.wake(); if (offlineStarted) offline.retry(); });
addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { networkClient?.wake(); if (offlineStarted) offline.refresh(); refreshStorage(); } });
$('saved').addEventListener?.('click', () => refreshStorage());
const previousOfflineChange = offline.onChange;
offline.onChange = state => {
  previousOfflineChange(state);
  renderLocalChoices();
  if (writeAccess && saveIdentityKnown && recoveryKnown && state.ready && !pendingWrites && !saveFailed) {
    const identities = [...new Set([durableIdentity, previousSave?.identity, lastSave?.identity].filter(Boolean))];
    offline.retain(identities);
  }
};
offline.refresh();

const lobbyView = new LobbyView([$('network-our-team'), $('network-their-team')], seat =>
  networkClient?.toggleBot(seat).catch(networkFailure));
function networkFailure(error) {
  $('network-status').textContent = error.message; status(error.message, true); renderConnection();
}
function renderConnection() {
  const labels = {connecting: 'Yhdistetään…', synchronising: 'Päivitetään pelitilannetta…',
    connected: 'Yhteys kunnossa', pending: 'Varmistetaan siirtoasi…', reconnecting: 'Yhteys katkesi · yhdistetään uudelleen…',
    restarting: 'Palvelin päivittyy · peli jatkuu hetken kuluttua…',
    authentication: 'Kirjautuminen tarvitsee vahvistuksen · huoneesi säilyy',
    failed: 'Yhteys tarvitsee huomiota', superseded: 'Paikkasi on avoinna toisessa välilehdessä'};
  const phase = connectionState.phase;
  $('network-connection').hidden = !networkEnabled || phase === 'local';
  $('connection-label').textContent = labels[phase] || 'Yhdistetään…';
  $('network-connection').dataset.phase = phase;
  for (const id of ['network-retry', 'network-retry-lobby']) {
    $(id).hidden = !['reconnecting', 'restarting', 'failed', 'superseded'].includes(phase);
    $(id).disabled = !networkClient?.session;
  }
  for (const id of ['network-reauth', 'network-reauth-lobby']) {
    $(id).hidden = phase !== 'authentication';
    $(id).disabled = Boolean(networkClient?.session?.pending);
  }
}
// Host pause/resume during a match and rematch after it, when the server
// supports them; other players see the state and who can act on it.
function renderNetworkControls() {
  const client = networkClient, lobby = client?.session?.lobby, host = Boolean(client?.session?.host);
  const features = client?.features ?? new Set(), terminal = Boolean(view?.terminal);
  const active = Boolean(view) && !terminal && lobby?.lifecycle === 'playing';
  $('network-pause').hidden = !(host && features.has('pause') && active && !lobby.paused);
  $('network-unpause').hidden = !(host && features.has('pause') && active && lobby.paused);
  $('network-rematch').hidden = !(host && features.has('rematch') && terminal);
  for (const id of ['network-pause', 'network-unpause', 'network-rematch'])
    $(id).disabled = !client?.connected || client.authRequired;
  $('network-controls').hidden = ['network-pause', 'network-unpause', 'network-rematch'].every(id => $(id).hidden);
  $('network-rematch-note').hidden = !(client && !host && features.has('rematch') && terminal);
}
// Server standings by nickname; fetched at most every few seconds.
async function refreshLeaderboard(force = false) {
  if (!networkClient?.connected || leaderboardLoading || (!force && Date.now() - leaderboardFetched < 5000)) return;
  leaderboardLoading = true;
  try {
    const entries = await networkClient.leaderboard();
    leaderboardFetched = Date.now();
    if (entries) { leaderboardEntries = entries; renderLeaderboard(); }
  } catch {} finally { leaderboardLoading = false; }
}
function renderLeaderboard() {
  const own = networkClient?.session?.lobby?.seats?.find(s => s.seat === networkClient.session.seat)?.display_name?.trim().toLowerCase();
  const rows = () => (leaderboardEntries ?? []).map((entry, index) => {
    const item = document.createElement('li');
    item.textContent = `${entry.name}: ${entry.wins} ${entry.wins === 1 ? 'voitto' : 'voittoa'}, ${entry.losses} ${entry.losses === 1 ? 'tappio' : 'tappiota'} (${entry.win_percent} %)`;
    if (entry.name.trim().toLowerCase() === own) { item.className = 'own'; item.setAttribute('aria-current', 'true'); }
    return item;
  });
  const shown = Boolean(leaderboardEntries?.length);
  $('network-leaderboard').hidden = !shown; $('network-leaderboard-list').replaceChildren(...rows());
  $('summary-leaderboard').hidden = !shown || !view?.terminal || !networkClient; $('summary-leaderboard-list').replaceChildren(...rows());
}
function previousMatchesText(lobby, seat) {
  const previous = lobby.previous_matches ?? [], team = seat % 2;
  const first = (lobby.match_number ?? previous.length + 1) - previous.length;
  return previous.map((match, index) => `Ottelu ${first + index}: ${match.final_score[team]}–${match.final_score[1 - team]}, ` +
    `${match.winner_team === team ? 'te voititte' : 'vastustajat voittivat'} (${match.deals} ${match.deals === 1 ? 'jako' : 'jakoa'})`).join(' · ');
}
function showNetworkLobby(lobby) {
  if (!lobby) return;
  const model = lobbyPresentation(lobby, networkClient?.session.seat ?? 0), playing = model.playing;
  if (!playing && view && networkClient) {
    // A rematch reopened the room: leave the finished table for the lobby.
    cancelReveal(); networkRevealDeal = null; view = null; selectedCard = null; keyboard.reset(); awaitingNetworkGame = true; render();
    if (!$('network-dialog').open) openDialog('network-dialog');
  }
  if (!playing || lobby.lifecycle === 'completed') refreshLeaderboard();
  const previous = previousMatchesText(lobby, networkClient?.session.seat ?? 0);
  $('network-previous').hidden = !previous; $('network-previous').textContent = previous ? `Aiemmat ottelut tässä huoneessa: ${previous}` : '';
  $('network-entry').hidden = true; $('network-lobby').hidden = false; $('network-local').hidden = false;
  $('network-title').textContent = 'Pelihuone';
  $('network-dialog').dataset.stage = 'lobby';
  $('network-room').textContent = lobby.match_number ? `Huone ${lobby.room_code} · ottelu ${lobby.match_number}` : `Huone ${lobby.room_code}`;
  const available = Boolean(networkClient?.connected && !networkClient.authRequired);
  const configuring = Boolean(networkClient?.configuring);
  lobbyView.render(model, {host: networkClient?.session.host, connected: available, configuring});
  if (lobbyRoom === lobby.room_code && lobbyConfiguration && lobbyConfiguration !== model.configuration && !playing) {
    $('network-changed').textContent = 'Paikkajako muuttui. Vahvistakaa valmius uudelleen.';
  }
  if (lobbyRoom !== lobby.room_code || model.ownReady || playing) $('network-changed').textContent = '';
  lobbyRoom = lobby.room_code; lobbyConfiguration = model.configuration;
  $('network-summary').textContent = `${model.humans} ${model.humans === 1 ? 'pelaaja' : 'pelaajaa'} · ${model.bots} ${model.bots === 1 ? 'botti' : 'bottia'}`;
  $('network-readiness').textContent = configuring ? 'Päivitetään bottipaikkoja…' : model.readyText;
  $('network-fill').hidden = $('network-open').hidden = !networkClient?.session.host || playing;
  $('network-fill').disabled = $('network-open').disabled = !available || configuring;
  $('network-ready').hidden = playing;
  $('network-ready').disabled = !available || configuring || model.open > 0 || model.ownReady;
  $('network-ready').textContent = model.ownReady ? 'Olet valmis' : 'Olen valmis';
  $('network-seat-guide').hidden = !networkClient?.session.host || playing || model.humans > 1;
  $('network-invite').value = invitationURL(location.href, lobby.room_code);
  if (playing && screen === 'game') $('mode-label').textContent = `· Verkkopeli ${lobby.room_code}`;
}
// The room-creation passcode field appears only when this host asks for it.
async function showPasscodeIfRequired() {
  if (!networkAddress) return;
  passcodeCheck ??= new NetworkSession().createPasscodeRequired(networkAddress)
    .then(required => { passcodeRequired = required; })
    .catch(() => { passcodeCheck = null; });
  await passcodeCheck;
  if (!$('network-entry').hidden) renderRoomEntry();
}
async function startNetwork(command) {
  if (!networkEnabled || entryPending || navigationPending) return;
  if (!writeAccess || !networkAddress) { $('network-status').textContent = 'Verkkopeli ei ole vielä valmis. Yritä hetken kuluttua.'; return; }
  if (command === 'resume' && (!savedNetwork || savedNetwork.base !== networkAddress)) return;
  if (command === 'join') {
    try { $('network-code').value = roomCodeFromInput($('network-code').value, location.href); }
    catch (error) { $('network-status').textContent = error.message; $('network-code').focus?.(); return; }
  }
  entryPending = true; awaitingNetworkGame = true; navigationToken++; renderRoomEntry(); renderHome();
  await saveQueue.catch(() => {});
  if (saveFailed) {
    entryPending = false; awaitingNetworkGame = false; renderRoomEntry(); renderHome();
    $('network-status').textContent = 'Paikallisen pelin tallennus ei onnistunut. Lataa siitä varmuuskopio asetuksista ennen pelitavan vaihtoa.';
    return;
  }
  busy = true; worker?.terminate(); worker = null;
  generation++; cancelReveal(); networkRevealDeal = null; keyboard.reset(); selectedCard = null;
  lobbyConfiguration = null; lobbyRoom = null;
  pendingWrites = 0; saveFailed = false;
  networkClient?.close(); view = null; render(); startup({ready: true});
  networkClient = new NetworkSession({persist: async session => { await storeNetwork(session); savedNetwork = structuredClone(session); },
    onConnection: state => {
      connectionState = state; renderConnection();
      if (networkClient?.session && !networkClient.session.lobby) {
        $('network-entry').hidden = $('network-lobby').hidden = true;
        $('network-title').textContent = `Yhdistetään huoneeseen ${networkClient.session.room_code}`;
      }
    },
    // The server may have restarted for an update: fetch a newer release in
    // the background; it is used after Tuppi is closed and opened again.
    onReconnect: () => { offline.checkForUpdate(); },
    onLobby: showNetworkLobby,
    onStatus: (message, error) => {
      $('network-status').textContent = message; status(message, error);
      busy = !networkClient.connected || Boolean(networkClient.session?.pending);
      showNetworkLobby(networkClient.session?.lobby); render();
      if (error && networkClient.stopped) $('network-resume').hidden = !savedNetwork;
    },
    onView: next => {
      const old = view;
      if (old?.dealNumber !== next.dealNumber) {
        cancelReveal(); bidContract = legalCards(next, 0).length ? 0 : 1;
      }
      const reveal = old?.phase === 0 && next.phase !== 0 && old.dealNumber === next.dealNumber && next.bids.length && networkRevealDeal !== next.dealNumber;
      if (reveal) networkRevealDeal = next.dealNumber;
      next.revealing = Boolean(reveal || (revealFrame && old?.dealNumber === next.dealNumber));
      view = next; busy = !networkClient.connected || Boolean(networkClient.session.pending);
      if (awaitingNetworkGame) { awaitingNetworkGame = false; showGame(); $('network-dialog').close(); }
      if (!next.waitingHuman || old?.phase !== next.phase || old?.dealNumber !== next.dealNumber) { selectedCard = null; keyboard.reset(); }
      if (reveal) startReveal(); else render();
    }});
  $('mode-label').textContent = '· Verkkopeli'; $('saved').textContent = 'Huone tallentuu palveluun. Paikkasi muistetaan tällä selaimella.';
  try {
    if (command === 'resume') await networkClient.begin({...savedNetwork, active: true});
    else {
      const nickname = $('network-name').value.trim() || 'Pelaaja';
      preferences = savePreferences({...preferences, nickname});
      if (command === 'create') {
        await networkClient.create(networkAddress, nickname, ($('network-passcode').value ?? '').trim());
        $('network-passcode').value = '';
      } else await networkClient.join(networkAddress, $('network-code').value, nickname);
    }
  } catch (error) {
    networkClient.close(); networkClient = null;
    if (connectionState.phase !== 'authentication') connectionState = {phase: 'failed'};
    renderConnection(); $('network-resume').hidden = !savedNetwork || savedNetwork.base !== networkAddress;
    $('network-status').textContent = error.message; $('network-entry').hidden = false; $('network-lobby').hidden = true;
    if (['room_passcode_required', 'invalid_room_passcode'].includes(error.code)) {
      passcodeRequired = true; roomIntent = 'create';
    }
    status(error.message, true); $('network-local').hidden = false;
  } finally {
    entryPending = false; renderRoomEntry(); renderHome();
  }
}
async function returnToLocal() {
  const session = networkClient?.session ?? savedNetwork;
  networkClient?.close(); networkClient = null;
  connectionState = {phase: 'local'}; renderConnection();
  if (session) { session.active = false; await storeNetwork(session); savedNetwork = session; }
  $('network-dialog').close(); $('network-entry').hidden = false; $('network-lobby').hidden = true;
  $('network-local').hidden = true; $('network-resume').hidden = !savedNetwork;
  if (!offlineStarted) { offlineStarted = true; offline.start(); }
  await resumeLocal(lastSave);
}
$('network-toggle').onclick = () => {
  if (!networkEnabled) return;
  if (networkClient?.session) { showNetworkLobby(networkClient.session.lobby); openDialog('network-dialog'); }
  else openRoomEntry();
};
$('network-toggle').disabled = !networkEnabled;
$('home-toggle').onclick = showHome;
$('home-local').onclick = enterLocalPlay;
$('home-online').onclick = async () => {
  if (!entryReady || !networkEnabled || entryPending || navigationPending) return;
  navigationToken++;
  if (networkClient?.session) {
    if (view) { showGame(); render(); }
    else { awaitingNetworkGame = true; showNetworkLobby(networkClient.session.lobby); openDialog('network-dialog'); }
  } else {
    openRoomEntry();
    if (savedNetwork?.active && savedNetwork.base === networkAddress) await startNetwork('resume');
  }
};
$('home-retry').onclick = () => location.reload();
$('network-reload').onclick = async () => {
  networkResolved = false; $('network-reload').hidden = true; $('network-status').textContent = 'Yhdistetään verkkopeliin…';
  networkAddress = await readNetworkConfiguration(); networkResolved = true; renderHome(); renderRoomEntry();
  $('network-status').textContent = networkAddress ? '' : 'Yhteyttä ei saatu. Tarkista verkkoyhteys ja yritä uudelleen.';
};
$('network-name').value = preferences.nickname;
$('turn-sound').checked = preferences.turnSound;
$('help-toggle').onclick = () => openDialog('help');
$('close-help').onclick = () => $('help').close();
$('turn-sound').onchange = () => {
  preferences = savePreferences({...preferences, turnSound: Boolean($('turn-sound').checked)});
  if (preferences.turnSound) enableTurnAudio();
};
addEventListener('pointerdown', () => { if (preferences.turnSound && !turnAudio) enableTurnAudio(); }, {once: true});
$('network-name').onchange = () => { preferences = savePreferences({...preferences, nickname: $('network-name').value}); };
$('close-network').onclick = () => $('network-dialog').close();
$('network-dialog').onclose = () => { if (screen === 'home') awaitingNetworkGame = false; };
$('network-form').onsubmit = event => { event.preventDefault(); return startNetwork(roomIntent); };
$('network-resume').onclick = () => startNetwork('resume');
$('network-switch').onclick = async () => {
  if (entryPending) return;
  invitation = false; roomIntent = roomIntent === 'create' ? 'join' : 'create';
  $('network-status').textContent = ''; renderRoomEntry();
  if (roomIntent === 'create') await showPasscodeIfRequired();
};
$('network-ready').onclick = () => networkClient?.ready();
$('network-fill').onclick = () => networkClient?.fillEmptySeats().catch(networkFailure);
$('network-pause').onclick = () => networkClient?.pause();
$('network-unpause').onclick = () => networkClient?.resume();
$('network-rematch').onclick = () => networkClient?.rematch();
$('network-open').onclick = () => networkClient?.openSeats().catch(networkFailure);
$('network-local').onclick = enterLocalPlay;
$('network-copy').onclick = async () => {
  if (!networkClient?.session) return;
  const link = invitationURL(location.href, networkClient.session.room_code);
  try { await navigator.clipboard.writeText(link); $('network-status').textContent = 'Kutsulinkki kopioitu.'; }
  catch {
    $('network-invite').value = link; $('network-invite-fallback').hidden = false;
    $('network-invite').focus?.(); $('network-invite').select?.();
    $('network-status').textContent = 'Kopioi kutsulinkki alla olevasta kentästä tai jaa huonekoodi.';
  }
};
for (const id of ['network-retry', 'network-retry-lobby']) $(id).onclick = () => networkClient?.retryNow();
for (const id of ['network-reauth', 'network-reauth-lobby']) $(id).onclick = async () => {
  if (networkClient?.session?.pending) return;
  await saveQueue.catch(() => {}); await networkClient?.queue;
  // A deliberate same-origin navigation renews the browser login. Never put a
  // credential into a URL, discard the room, or automatically repeat a POST.
  location.reload();
};
$('offline-prepare').onclick = async () => { offlineStarted = true; $('offline-prepare').hidden = true; await offline.start(); };
