// Source: capabilities.mjs
// The release packager selects this flag; local development includes networking.
const networkEnabled = true;

// Source: preferences.mjs
const preferenceKey = 'tuppi.ui.preferences.v1';
const defaults = {nickname: 'Pelaaja', expandedHand: false, turnSound: false, shareResults: true, suitOrder: [0, 1, 2, 3]};
// The suits in the hand from left to right (0 ♥, 1 ♦, 2 ♣, 3 ♠), as in the Mac app.
function validSuitOrder(order) {
  return Array.isArray(order) && order.length === 4 && [0, 1, 2, 3].every(suit => order.includes(suit));
}
function cleanPreferences(value) {
  return {nickname: typeof value?.nickname === 'string' && value.nickname.trim() ? value.nickname.trim().slice(0, 40) : defaults.nickname,
    expandedHand: value?.expandedHand === true, turnSound: value?.turnSound === true,
    // Anonymous offline match results for research (opt-out).
    shareResults: value?.shareResults !== false,
    suitOrder: validSuitOrder(value?.suitOrder) ? [...value.suitOrder] : [...defaults.suitOrder]};
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
// Suits in the player's chosen order (Settings; ♥ ♦ ♣ ♠ by default), ranks
// rising, with the ace lowest in sooli.
function sortedHand(view, suitOrder = [0, 1, 2, 3]) {
  const aceLow = view.soolaaja >= 0 || [4, 5, 6].includes(view.phase);
  const rank = card => aceLow && card % 13 === 12 ? -1 : card % 13;
  const place = card => suitOrder.indexOf(Math.floor(card / 13));
  return view.hand.toSorted((a, b) => place(a) - place(b) || rank(a) - rank(b));
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
  adjacent(selected, direction, view, contract, suitOrder) {
    if (!view?.waitingHuman || view.revealing || selected === null) return null;
    const hand = sortedHand(view, suitOrder), start = hand.indexOf(selected), allowed = legalCards(view, contract);
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

// An anonymous report of a finished offline match for the server's research
// results (no names, cards or hands): the bot level, the winner and final
// score from the player's team's view, deal and concession counts. Its id is
// a hash of the first deal's shuffled deck, so a match is reported once.
async function offlineResultReport(save) {
  const deals = save?.completed ?? [], last = deals.at(-1)?.result, id = await offlineMatchId(save);
  if (!id) return null;
  return {id, worlds: save.worlds, ...(save.bot ? {bot: save.bot} : {}), winner_team: last.score0 >= 52 ? 0 : 1, final_score: [last.score0, last.score1],
    deals: deals.length, conceded: deals.filter(deal => deal.conceded).length};
}
async function offlineMatchId(save) {
  const deals = save?.completed ?? [], last = deals.at(-1)?.result;
  if (!last?.terminal || !(save.bot === 'dan11' ? save.worlds === 64 : [128, 1024].includes(save.worlds)) || !deals[0]?.cards) return null;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([deals[0].cards, deals[0].dealer])));
  return [...new Uint8Array(digest)].slice(0, 16).map(byte => byte.toString(16).padStart(2, '0')).join('');
}
// A finished offline match with every card, for developing the bots (the
// server checks it by replaying it): each deal's dealt cards, dealer, score
// before it and actions in order, and the bot's runtime. Same id as the
// result above; no names or anything else about the player.
async function offlineMatchRecord(save) {
  const id = await offlineMatchId(save);
  if (!id || typeof save.identity !== 'string') return null;
  return {id, worlds: save.worlds, ...(save.bot ? {bot: save.bot} : {}), runtime: save.identity, deals: save.completed.map(deal => ({cards: [...deal.cards],
    dealer: deal.dealer, score: [...deal.score], actions: [...deal.actions],
    ...(deal.conceded ? {conceded: {afterTricks: deal.conceded.afterTricks}} : {})}))};
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
      ...(best ? [`Suurin jakovoittonne: ${best} pistettä.`] : []),
      ...(deals.some(deal => deal.conceded) ? [`Luovutettuja jakoja: ${deals.filter(deal => deal.conceded).length}.`] : [])]};
}

// A finished deal's analysis (session.mjs analyseDeal) as the player reads it.
// Gaps are in the bot's match-value units (−1…+1); the search samples deals,
// so differences below 0.01 are within its noise and count as good.
const analysisGrades = {good: 'Hyvä', inaccuracy: 'Epätarkka', mistake: 'Virhe', unknown: 'Ei arviota'};
function analysisAction(id) {
  if (id >= 158) return `vaihtokortti ${cardLabel(id - 158)}`;
  if (id === 156) return 'ei soolia';
  if (id === 157) return 'sooli';
  if (id >= 52) return `${id >= 104 ? 'RAMI' : 'NOLO'} ${cardLabel(id % 52)}`;
  return cardLabel(id);
}
function analysisPresentation(result) {
  const items = result.decisions.map(decision => {
    const where = decision.phase === 0 ? 'Tarjous' : decision.phase === 3 ? 'Soolitarjous' :
      [4, 5].includes(decision.phase) ? 'Soolivaihto' : `Tikki ${Math.floor(decision.played / decision.trickSize) + 1}`;
    const grade = decision.loss === null ? 'unknown' : decision.loss < 0.01 ? 'good' : decision.loss < 0.04 ? 'inaccuracy' : 'mistake';
    const text = decision.chosen === decision.best ? `${where}: ${analysisAction(decision.chosen)}, sama kuin botin valinta.` :
      `${where}: ${analysisAction(decision.chosen)}; botti valitsisi ${analysisAction(decision.best)}` +
      (decision.loss === null ? '.' : ` (ero ${decision.loss.toFixed(3).replace('.', ',')}).`);
    return {grade, label: analysisGrades[grade], text};
  });
  const count = grade => items.filter(item => item.grade === grade).length;
  const summary = items.length ? `${items.length} ${items.length === 1 ? 'ratkaisu' : 'ratkaisua'}: ${count('good')} hyvää, ` +
    `${count('inaccuracy')} epätarkkaa, ${count('mistake')} virhettä.` : 'Tässä jaossa ei ollut valittavaa: jokainen siirto oli ainoa sallittu.';
  return {items, summary};
}

// Every player's dealt hand in a finished deal (deck positions seat*13…), from
// the viewer's seat round the table, by suit (in the player's suit order) from
// the ace down, with high-card points (A 4, K 3, Q 2, J 1). Offline it is the
// saved deal; online, the cards each seat played (every card is played by the
// end of a non-sooli deal).
function dealHands(deal, ownSeat = 0, suitOrder = [0, 1, 2, 3]) {
  return [0, 1, 2, 3].map(position => {
    const seat = (ownSeat + position) % 4, cards = deal.cards.slice(seat * 13, seat * 13 + 13);
    const bySuit = suitOrder.map(suit => ({suit: suits[suit],
      ranks: cards.filter(card => Math.floor(card / 13) === suit).sort((a, b) => b - a).map(cardRank)}));
    return {position, label: seatNames[position], suits: bySuit,
      highCardPoints: cards.reduce((sum, card) => sum + Math.max(0, card % 13 - 8), 0),
      text: bySuit.map(item => `${item.suit} ${item.ranks.join(' ') || '–'}`).join('  ')};
  });
}

// Source: offline.mjs
// The packager pins this value without changing runtime/model save identity.
const packagedRuntimeIdentity = "ab2b37c6fa31035c211fab2fbf99505dd7b5d4f562dc9fc2a4d1db333f5773bc";

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
  invalid_bot_profile:'Valittu botti ei ole käytettävissä tässä verkkopelissä.',
  heidi_busy:'Heidi pelaa jo toisessa pöydässä. Voit odottaa sen päättymistä tai luoda pelin toisella botilla.',
  invalid_session:'Tallennettua paikkaa ei löydy. Voit luoda uuden huoneen.',
  settings_locked:'Ottelu on jo alkanut. Paikat on lukittu.', host_required:'Vain huoneen luoja voi vaihtaa bottipaikkoja.',
  server_busy:'Palvelu on täynnä. Jatka huoneeseen myöhemmin.',
  room_passcode_required:'Huoneen luominen tällä palvelimella vaatii luontikoodin.',
  invalid_room_passcode:'Luontikoodi ei kelpaa. Tarkista koodi.',
  too_many_attempts:'Liian monta väärää koodia. Odota minuutti ja yritä uudelleen.',
  storage_unavailable:'Palvelimen tallennus ei juuri nyt toimi. Siirtoasi ei tallennettu; peli jatkuu, kun palvelu on käynnistynyt uudelleen.',
  storage_low:'Palvelimen tallennustila on vähissä, joten uusia huoneita ei nyt voi luoda. Käynnissä olevat pelit jatkuvat.',
  match_not_active:'Ottelu ei ole käynnissä.', match_not_complete:'Uuden ottelun voi aloittaa, kun ottelu on päättynyt.',
  invalid_display_name:'Kirjoita nimimerkki (1–40 merkkiä).',
  seat_taken:'Paikka ehdittiin jo varata. Valitse toinen paikka.',
  player_cannot_move:'Pelaajan sovellus ei tue paikan vaihtoa. Pyydä häntä sulkemaan ja avaamaan Tuppi uudelleen.',
  seat_not_releasable:'Tätä paikkaa ei voi vapauttaa.',
  seat_not_coverable:'Pääset peliin seuraavan jaon alussa.',
  watchers_full:'Huonetta katsoo jo kahdeksan ihmistä. Yritä myöhemmin uudelleen.',
  spectator_cannot_act:'Katsojana et voi tehdä siirtoja.'};
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
// The deal's result is already 0-0 (same rule as session.mjs decidedForZero
// and the server's concede_available): in NOLO the team ahead has 7 tricks,
// in RAMI the team behind has 7. Own-team-first scores and tricks.
function networkDecided(view) {
  if (view.phase !== 1 || (!view.score0 && !view.score1)) return false;
  const tricks = [view.tricks0, view.tricks1], ahead = view.score0 > 0 ? 0 : 1;
  return view.contract === 1 ? tricks[1 - ahead] >= 7 : tricks[ahead] >= 7;
}
// A finished online deal for local analysis. Once it is over every card has
// been played, so each seat's hand is the cards it played; bids and sooli
// decisions are public. A deal played as sooli is not supported (the sitting-out
// partner's hand is never shown), nor is anything that does not add up.
function networkDealForAnalysis(deal) {
  if (!deal || !Array.isArray(deal.tricks) || !Array.isArray(deal.show_actions) || !Array.isArray(deal.score_before)) return null;
  if (deal.sooli && deal.sooli.soolaaja !== null) return null;
  const plays = deal.tricks.flatMap(trick => trick.plays), hands = [[], [], [], []];
  try {
    for (const play of plays) hands[play.seat].push(networkCard(play.card));
    if (plays.length !== 52 || hands.some(hand => hand.length !== 13)) return null;
    const actions = [...deal.show_actions.map(show => networkActionID({type: 'show', ...show})),
      ...(deal.sooli?.decisions ?? []).map(decision => decision.play_sooli ? 157 : 156),
      ...plays.map(play => networkCard(play.card))];
    return {cards: hands.flat(), dealer: deal.dealer, score: [...deal.score_before], actions, expectedTricks: [...deal.team_tricks]};
  } catch { return null; }
}
// A spectator's update (feature watch) as the table seen from `viewpoint`:
// that seat's cards as the hand, no actions of its own, and every seat's
// cards by table position (0 = the viewpoint, then clockwise) in `tableHands`.
function spectatorPayload(payload, viewpoint = 0) {
  const hands = payload.table?.hands;
  if (!Array.isArray(hands) || hands.length !== 4) throw new Error('Palvelin lähetti puutteellisen katsojanäkymän.');
  return {...payload, bidding: payload.bidding && {...payload.bidding, options: [], own_bid: null},
    observation: {...payload.observation, observing_seat: viewpoint, own_hand: hands[viewpoint], legal_actions: [],
      team: viewpoint % 2, partner_seat: (viewpoint + 2) % 4},
    tableHands: [0, 1, 2, 3].map(position => hands[(viewpoint + position) % 4].map(networkCard))};
}
function networkView(payload, completed = [], summary = null, conceded = new Map()) {
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
      winnerTeam: deal.deal_score.winner_team === team ? 0 : 1, points: deal.deal_score.points},
    conceded: conceded.has(deal.deal_number) ? {afterTricks: conceded.get(deal.deal_number).after_tricks,
      seat: networkSeat(conceded.get(deal.deal_number).seat, own)} : null}));
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
    ...(payload.tableHands ? {watching: true, tableHands: payload.tableHands} : {}),
    prompt: legal.length ? null : phase === 0 ? 'Tarjous lukittu. Odotetaan muita pelaajia…' :
      observation.current_actor === null ? 'Ottelu päättyi.' : 'Odotetaan siirtoa…'};
}

const chatHistory = 50;
function chatItem(item) {
  // seat null: a spectator (feature watch).
  return Number.isInteger(item?.id) && (Number.isInteger(item.seat) || item.seat === null) && typeof item.display_name === 'string' &&
    typeof item.text === 'string' && Number.isInteger(item.sent_at);
}
// The host's seat: 0 unless the host left and another player hosts
// (feature leave_seat; older servers do not say).
function hostSeat(lobby) {
  return Number.isInteger(lobby?.host_seat) ? lobby.host_seat : 0;
}

class NetworkSession {
  constructor({persist, onView = () => {}, onLobby = () => {}, onStatus = () => {}, onConnection = () => {},
    onReconnect = () => {}, onChat = () => {}, fetcher = (...args) => globalThis.fetch(...args), Socket = globalThis.WebSocket,
    timers = globalThis} = {}) {
    Object.assign(this, {persist, onView, onLobby, onStatus, onConnection, onReconnect, onChat, fetcher, Socket, timers});
    // Room chat (feature chat): the latest messages, oldest first. Memory only;
    // the server sends them again when this seat reconnects.
    this.chat = [];
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
    // Deals finished by concession (the server's conceded_deals), by number.
    this.conceded = new Map();
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
  // The game viewer (round 16, feature deal_records): the current match's
  // finished deals in full (every hand and bid); null on older servers.
  async dealRecords() {
    if (!this.features.has('deal_records') || !this.session) return null;
    return this.request(`/v1/rooms/${this.session.room_code}/records`, {session_token: this.session.session_token});
  }
  async check(base) {
    const result = await this.request('/v1/compatibility', null, base);
    if (result.protocol_version !== networkProtocol || result.ruleset_id !== 'project_target_v3')
      throw new Error('Palvelin tarvitsee yhteensopivan peliversion.');
  }
  // Public hosts may require a room-creation passcode; joining never does.
  async createPasscodeRequired(base) {
    const compatibility = await this.request('/v1/compatibility', null, base);
    this.botOptions = compatibility.bot_options ?? [];
    return Boolean(compatibility.create_passcode_required);
  }
  async create(base, displayName, passcode = '', botProfile = null) {
    await this.check(base);
    const result = await this.request('/v1/rooms', {display_name: displayName, ai_seats: [],
      ...(passcode ? {room_passcode: passcode} : {}), ...(botProfile ? {bot_profile: botProfile} : {})}, base);
    await this.begin({...result, base: networkBase(base), host: true, pending: null, cursor: -1,
      schema: 'tuppi.browser.network.v1', active: true});
  }
  // Before joining (feature seat_choice): who sits where and the host's seat;
  // null if the server cannot say. The host's partner sits opposite them.
  // During a match (feature leave_seat) the seats players left are open.
  async seatPreview(base, code) {
    if (!/^[A-Z0-9]{6}$/.test(code)) return null;
    const compatibility = await this.request('/v1/compatibility', null, base);
    if (!compatibility.features?.includes('seat_choice')) return null;
    const result = await this.request(`/v1/rooms/${code}/seats`, {}, base);
    return Array.isArray(result.seats) && result.joinable ? {seats: result.seats, hostSeat: hostSeat(result)} : null;
  }
  // Watch a room (feature watch): every hand and the chat, no seat. The
  // table is shown from seat 0 until another viewpoint is chosen.
  async watch(base, code, displayName) {
    if (!/^[A-Z0-9]{6}$/.test(code)) throw new Error('Huonekoodi on kuusi kirjainta tai numeroa.');
    await this.check(base);
    const result = await this.request(`/v1/rooms/${code}/watch`, {display_name: displayName}, base);
    await this.begin({...result, base: networkBase(base), host: false, pending: null, cursor: -1,
      schema: 'tuppi.browser.network.v1', active: true, watching: true, viewpoint: 0, display_name: displayName});
  }
  // A spectator's credential is kept in server memory only: after a server
  // restart (or when a full room forgot it) the app asks to watch again.
  async rewatch() {
    const result = await this.request(`/v1/rooms/${this.session.room_code}/watch`, {display_name: this.session.display_name || 'Katsoja'});
    this.session.session_token = result.session_token; this.session.lobby = result.lobby;
    await this.persist(this.session);
  }
  setViewpoint(seat) {
    if (!this.session?.watching || !Number.isInteger(seat) || seat < 0 || seat > 3) return;
    this.session.viewpoint = seat; this.persist(this.session).catch(() => {});
    this.onLobby(this.session.lobby); this.emitView();
  }
  async join(base, code, displayName, seat = null) {
    if (!/^[A-Z0-9]{6}$/.test(code)) throw new Error('Huonekoodi on kuusi kirjainta tai numeroa.');
    await this.check(base);
    const result = await this.request(`/v1/rooms/${code}/join`,
      {display_name: displayName, ...(Number.isInteger(seat) ? {seat} : {})}, base);
    await this.begin({...result, base: networkBase(base), host: false, pending: null, cursor: -1,
      schema: 'tuppi.browser.network.v1', active: true});
  }
  async begin(session) {
    if (session?.schema !== 'tuppi.browser.network.v1' || !/^[A-Z0-9]{6}$/.test(session.room_code) ||
        typeof session.session_token !== 'string' || session.session_token.length < 20 ||
        !Number.isInteger(session.seat) || session.seat < 0 || session.seat > 3)
      throw new Error('Verkkopelin tallennus ei ole yhteensopiva.');
    networkBase(session.base);
    this.close(); this.session = structuredClone(session); this.completed.clear(); this.conceded.clear(); this.latest = null;
    this.chat = []; this.onChat(this.chat, null);
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
      if ([4002, 4003, 4004].includes(event.code)) {
        // The host freed this seat (4002), this player left the room in
        // another tab (4003), or the last player left and the room closed
        // (4004, spectators); the credential no longer works.
        this.stopped = true; this.session.active = false; this.session.released = true;
        this.persist(this.session).catch(() => {});
        this.connection({4002: 'released', 4003: 'left', 4004: 'closed'}[event.code]);
        this.onStatus({4002: 'Huoneen luoja vapautti paikkasi. Voit liittyä huoneeseen uudelleen kutsulinkillä.',
          4003: 'Poistuit huoneesta toisessa välilehdessä.', 4004: 'Huone suljettiin, koska viimeinen pelaaja poistui.'}[event.code], true); return;
      }
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
      // A seat the host moved while this app was away (feature seat_swap): the
      // server holds the authoritative seat of this credential.
      if (payload.protocol_version === networkProtocol && payload.room_code === this.session.room_code &&
          payload.seat !== this.session.seat && Array.isArray(payload.features) && payload.features.includes('seat_swap')) {
        this.session.seat = payload.seat; await this.persist(this.session);
      }
      if (payload.protocol_version !== networkProtocol || payload.seat !== this.session.seat || payload.room_code !== this.session.room_code ||
          Boolean(payload.watching) !== Boolean(this.session.watching))
        throw new Error('Verkkopelin paikka tai versio muuttui.');
      this.retryCount = 0; this.timers.clearTimeout(this.deadline); this.beat();
      const resumed = this.interrupted; this.restarting = this.interrupted = false;
      if (resumed) this.onReconnect();
      this.features = new Set(Array.isArray(payload.features) ? payload.features : []);
      // The browser never reads the full terminal match result, and takes a new
      // seat if the host moves it; say so only to servers that list these.
      const options = {...(this.features.has('compact_results') ? {omit_match_result: true} : {}),
        ...(this.features.has('seat_swap') ? {seat_updates: true} : {})};
      if (Object.keys(options).length) this.send('client_options', options);
    } else if (message.message_type === 'seat_update' && !this.session.watching) {
      // The host moved this player before the match (feature seat_swap).
      if (!Number.isInteger(payload.seat) || payload.seat < 0 || payload.seat > 3) throw new Error('Palvelin lähetti virheellisen paikan.');
      this.session.seat = payload.seat; await this.persist(this.session);
      this.onStatus('Huoneen luoja vaihtoi paikkaasi.', false);
    } else if (message.message_type === 'chat_history') {
      if (!Array.isArray(payload.messages)) return;
      this.chat = payload.messages.filter(chatItem).slice(-chatHistory); this.onChat(this.chat, null);
    } else if (message.message_type === 'chat_message') {
      if (!chatItem(payload) || this.chat.some(item => item.id === payload.id)) return;
      this.chat = [...this.chat, payload].slice(-chatHistory); this.onChat(this.chat, payload);
    } else if (message.message_type === 'chat_refused') {
      this.onChat(this.chat, null, payload.code === 'chat_rate_limited' ? 'Odota hetki ennen seuraavaa viestiä.' : 'Viestissä voi olla 1–200 merkkiä.');
    } else if (message.message_type === 'compatibility_result') throw new Error('Päivitä Tuppi ennen verkkopeliä.');
    else if (message.message_type === 'protocol_error' && payload.code === 'invalid_session' && this.session.watching && !this.rewatching) {
      // The server no longer knows this spectator: watch again, once.
      this.rewatching = true;
      try { await this.rewatch(); } finally { this.rewatching = false; }
      this.socket?.close();
    } else if (message.message_type === 'protocol_error') throw new Error(networkErrors[payload.code] || 'Verkkopelin yhteyttä ei voitu jatkaa. Paikkasi on tallennettu.');
    else if (message.message_type === 'lobby_snapshot') {
      this.lobbyRevision++;
      if (this.latest && !['playing','completed'].includes(payload.lifecycle)) {
        // The host started a rematch: the finished match's view and cursor
        // belong to the previous match. The next match starts from event 0.
        this.latest = null; this.completed.clear(); this.conceded.clear(); this.placed = null;
        Object.assign(this.session, {cursor: -1, match_ref: null, pending: null, summaryDeal: null, summary: null});
      }
      // The next player hosts when the host leaves (feature leave_seat).
      if (Number.isInteger(payload.host_seat)) this.session.host = !this.session.watching && payload.host_seat === this.session.seat;
      this.session.lobby = payload; await this.persist(this.session); this.onLobby(payload);
      this.emitView();
      if (!['playing','completed'].includes(payload.lifecycle)) { this.connected = true; this.connection('connected'); this.onStatus('', false); }
    } else if (['match_update','reconnect_result'].includes(message.message_type)) {
      if (payload.observation.observing_seat !== this.session.seat || Boolean(payload.table) !== Boolean(this.session.watching))
        throw new Error('Palvelin lähetti väärän paikan havainnon.');
      for (const deal of payload.completed_deals ?? []) this.completed.set(deal.deal_number, deal);
      for (const item of payload.conceded_deals ?? []) this.conceded.set(item.deal_number, item);
      this.latest = payload;
      const events = payload.event_batch ?? payload.event_delta ?? [];
      this.session.cursor = payload.last_event_index ?? events.at(-1)?.event_index ?? this.session.cursor;
      this.session.match_ref = payload.match_ref ?? payload.observation.match_ref;
      if (this.session.pending && this.session.cursor > this.session.pending.expected_event_index)
        this.placed = this.session.pending.client_action_id;
      if (!this.session.watching && payload.observation.phase === 'SHOWING' && this.session.summaryDeal !== payload.observation.deal_ref) {
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
    if (this.session.watching) { this.onView(this.spectatorView()); return; }
    const view = networkView(this.latest, [...this.completed.values()].sort((a,b) => a.deal_number-b.deal_number),
      this.session.summaryDeal === this.latest.observation.deal_ref ? this.session.summary : null, this.conceded);
    const paused = Boolean(this.session.lobby?.paused) && !view.terminal;
    // A bot is playing this seat while its player was away (feature seat_bot).
    const own = this.session.lobby?.seats?.find(s => s.seat === this.session.seat);
    const covered = own?.kind === 'ai' && !view.terminal;
    view.covered = covered;
    // Joined a seat its player left (feature leave_seat): the bot finishes this deal.
    view.joining = covered && Boolean(own.joining);
    if (!this.connected || this.stopped || this.session.pending || paused || covered) view.waitingHuman = false;
    view.paused = paused;
    view.concedeAvailable = this.features.has('concede') && this.connected && !this.stopped && !this.session.pending &&
      !paused && !covered && networkDecided(view);
    if (!this.connected) view.prompt = 'Yhdistetään verkkopeliin…';
    else if (paused) view.prompt = this.session.host ? 'Peli on tauolla. Jatka, kun kaikki ovat valmiita.' : 'Peli on tauolla. Huoneen luoja jatkaa peliä.';
    else if (view.joining) view.prompt = 'Liityit kesken ottelun. Botti pelaa tämän jaon loppuun, ja sinä pelaat seuraavasta jaosta alkaen.';
    else if (covered) view.prompt = 'Botti pelaa paikallasi. Voit ottaa paikkasi takaisin.';
    else if (this.session.pending && view.phase !== 2 &&
        (!this.placedPending() || this.latest.observation.current_actor === this.session.seat)) view.prompt = 'Käsitellään siirtoasi…';
    else if (!view.waitingHuman && ![0,2].includes(view.phase)) {
      const participant = this.session.lobby?.seats.find(s => s.seat === this.latest.observation.current_actor);
      view.prompt = participant?.kind === 'ai' ? `${participant.covering ? `Botti (${participant.covering})` : participant.display_name || 'Botti'} miettii…` :
        participant ? `${participant.display_name}: odotetaan siirtoa…` : 'Odotetaan siirtoa…';
    }
    this.onView(view);
  }
  // A spectator's table (feature watch): every hand, nothing to do.
  spectatorView() {
    const viewpoint = this.session.viewpoint ?? 0;
    const view = networkView(spectatorPayload(this.latest, viewpoint),
      [...this.completed.values()].sort((a,b) => a.deal_number-b.deal_number), null, this.conceded);
    const seats = this.session.lobby?.seats ?? [], name = seat => {
      const item = seats.find(s => s.seat === seat);
      return item?.covering ? `Botti (${item.covering})` : item?.display_name || 'Botti';
    };
    const observation = this.latest.observation, team = viewpoint % 2;
    Object.assign(view, {waitingHuman: false, covered: false, concedeAvailable: false, paused: Boolean(this.session.lobby?.paused) && !view.terminal});
    view.prompt = !this.connected ? 'Yhdistetään verkkopeliin…' : view.terminal ?
      `Ottelu päättyi: ${(view.score0 >= view.score1 ? [team, team + 2] : [1 - team, 3 - team]).map(name).join(' ja ')} voittivat.` :
      view.paused ? 'Peli on tauolla.' : view.phase === 0 ? 'Katsot peliä. Pelaajat lukitsevat tarjouksiaan.' :
      observation.current_actor === null ? 'Katsot peliä.' : `Katsot peliä. Vuorossa: ${name(observation.current_actor)}.`;
    return view;
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
  // Any player: finish a deal whose result is already 0-0.
  concede() {
    if (!this.features.has('concede') || !this.connected || this.stopped || this.session.pending || !this.latest) return false;
    return this.send('concede', {});
  }
  // A bot plays for an absent player (host), or a covered seat is taken back
  // (host, or that seat's own player).
  seatBot(seat, bot) {
    if (!this.features.has('seat_bot') || !this.connected || this.stopped || !this.session) return false;
    if (bot ? !this.session.host : !this.session.host && seat !== this.session.seat) return false;
    return this.send('seat_bot', {seat, bot: Boolean(bot)});
  }
  // A message to everyone in the room (feature chat). One line, at most 200
  // characters; the server answers with the message (or chat_refused).
  sendChat(text) {
    const line = String(text ?? '').replace(/\s+/g, ' ').trim();
    if (!line || !this.features.has('chat') || !this.connected || this.stopped) return false;
    return this.send('chat_send', {text: line.slice(0, 200)});
  }
  pause() { return this.hostCommand('pause'); }
  resume() { return this.hostCommand('resume'); }
  rematch() { return this.hostCommand('rematch'); }
  ready() { if (this.connected && !this.stopped && !this.configuring && !this.authRequired && !this.session.watching) this.send('ready', {session_token: this.session.session_token}); }
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
  // Lobby commands answered with the new lobby; a newer WebSocket snapshot
  // received meanwhile wins (as for bot configuration).
  async lobbyCommand(command, payload) {
    if (!this.connected || this.stopped || this.configuring || this.authRequired) return false;
    const epoch = this.epoch, revision = this.lobbyRevision;
    this.configuring = true; this.onLobby(this.session.lobby);
    try {
      const result = await this.request(`/v1/rooms/${this.session.room_code}/${command}`,
        {session_token: this.session.session_token, ...payload});
      if (epoch !== this.epoch || this.stopped) return false;
      if (revision === this.lobbyRevision) { this.session.lobby = result.lobby; await this.persist(this.session); }
      return true;
    } finally { this.configuring = false; if (epoch === this.epoch && !this.stopped) this.onLobby(this.session.lobby); }
  }
  // Leave the room for good (feature leave_seat). In the lobby the seat is
  // freed; during a match a bot plays it until someone joins it. The next
  // player hosts if the host leaves; the last player closes the room. With
  // an older server, or a room or seat that is already gone, the room is
  // only forgotten on this device. Returns {closed} from the server, or null.
  // `forget`: only forget the room here, e.g. when the server cannot be reached.
  async leave({forget = false} = {}) {
    if (!this.session) return null;
    let result = null;
    // A saved room this app is not connected to: ask the server what it offers.
    const features = this.features.size || forget ? this.features :
      new Set((await this.request('/v1/compatibility', null).catch(() => null))?.features ?? []);
    if (!forget && features.has('leave_seat') && !this.session.released) {
      try {
        result = await this.request(`/v1/rooms/${this.session.room_code}/leave`, {session_token: this.session.session_token});
      } catch (error) { if (!['room_not_found', 'invalid_session'].includes(error.code)) throw error; }
    }
    this.close(); this.session.active = false; this.session.released = true;
    await this.persist(this.session);
    return result;
  }
  // Host: swap two of the other seats before the match (feature seat_swap).
  async swapSeats(a, b) {
    if (!this.session?.host || !this.features.has('seat_swap')) return false;
    return this.lobbyCommand('swap', {seats: [a, b]});
  }
  // Your own nickname, before the match starts.
  async rename(displayName) {
    const name = String(displayName ?? '').trim();
    if (!name || name.length > 40) throw new Error(networkErrors.invalid_display_name);
    if (!this.features.has('rename')) return false;
    return this.lobbyCommand('name', {display_name: name});
  }
  // Host: free another player's seat, e.g. one left behind after rejoining.
  async releaseSeat(seat) {
    if (!this.session?.host || !this.features.has('release_seat') || seat === this.session.seat) return false;
    return this.lobbyCommand('release', {seat});
  }
  async toggleBot(seat) {
    const current = this.session.lobby.seats.find(s => s.seat === seat);
    if (!current || seat === hostSeat(this.session.lobby) || !['open','ai'].includes(current.kind)) throw new Error('Paikka on jo pelaajan käytössä.');
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

// A spectator's (feature watch) names for table positions from the viewpoint.
const watcherSeatNames = ['Alhaalla', 'Vasemmalla', 'Ylhäällä', 'Oikealla'];
function lobbyPresentation(lobby, ownSeat = 0, {watching = false} = {}) {
  const seats = lobby.seats.map(seat => ({...seat, position: networkSeat(seat.seat, ownSeat)}));
  const teams = [0, 1].map(team => seats.filter(seat => seat.position % 2 === team)
    .sort((a, b) => a.position - b.position));
  const humans = seats.filter(seat => seat.kind === 'human');
  const open = seats.filter(seat => seat.kind === 'open').length;
  const waiting = humans.filter(seat => !seat.ready);
  const playing = ['playing', 'completed'].includes(lobby.lifecycle);
  const label = seat => seat.position === 0 ? 'sinä' : seat.display_name || seatNames[seat.position];
  const readyText = watching ? (playing ? 'Katsot ottelua. Kaikkien kortit näkyvät.' :
    'Katsot huonetta. Ottelu alkaa, kun pelaajat ovat valmiita.') : playing ? 'Ottelu on alkanut. Paikat on lukittu.' : open ?
    `${open} ${open === 1 ? 'vapaa paikka' : 'vapaata paikkaa'}. Kutsu ystävä tai lisää botti ennen valmiuden vahvistamista.` :
    waiting.length ? `Valmiutta odotetaan: ${waiting.map(label).join(', ')}.` : 'Kaikki ovat valmiina. Ottelu alkaa…';
  return {teams, humans: humans.length, bots: seats.filter(seat => seat.kind === 'ai').length,
    // Seat kinds only: a renamed player does not change the seating, and the
    // server keeps everyone's readiness through a rename.
    open, playing, readyText, configuration: JSON.stringify(seats.map(seat => [seat.seat, seat.kind])),
    ownReady: Boolean(humans.find(seat => seat.seat === ownSeat)?.ready)};
}

function invitationURL(page, room) {
  if (!/^[A-Z0-9]{6}$/.test(room)) throw new Error('Virheellinen huonekoodi.');
  const link = new URL(page); link.search = ''; link.hash = '';
  link.searchParams.set('play', 'online'); link.searchParams.set('room', room);
  return link.href;
}

// Per seat: the host adds/removes bots on open seats and frees other
// players' seats; each player renames their own seat. Only before the match,
// and only what the server lists in its features.
function seatAction(seat, {host, playing, features = new Set()}) {
  if (playing) return null;
  if (seat.kind === 'human' && seat.position === 0) return features.has('rename') ? 'rename' : null;
  if (seat.kind === 'human') return host && features.has('release_seat') ? 'release' : null;
  return host ? 'toggle' : null;
}

// During a match (feature seat_bot): the host may let a bot play for a player
// who is not connected, and give a covered seat back; a covered player may
// take their own seat back. Never a bot for the host's seat, and not back
// while a newcomer waits for the next deal (feature leave_seat).
function standInActions(lobby, {host, ownSeat, features = new Set(), active}) {
  if (!active || !features.has('seat_bot') || !lobby?.seats) return [];
  return lobby.seats.flatMap(seat => {
    if (seat.kind === 'human' && seat.connected === false && host && seat.seat !== hostSeat(lobby))
      return [{seat: seat.seat, bot: true, text: `Botti pelaa: ${seat.display_name}`}];
    if (seat.kind === 'ai' && seat.covering && !seat.joining && (host || seat.seat === ownSeat))
      return [{seat: seat.seat, bot: false, text: seat.seat === ownSeat ? 'Ota paikkasi takaisin' : `Palauta paikka: ${seat.covering}`}];
    return [];
  });
}
// Choosing a seat before joining (feature seat_choice): one option per free
// seat, named by the team it joins. The host's partner sits opposite the host
// (seat 2 unless another player hosts); the other two are partners.
function seatChoices(seats, host = 0) {
  const at = seat => seats.find(item => item.seat === seat);
  const name = item => item?.kind === 'human' ? item.display_name : item?.kind === 'ai' ? 'botti' : null;
  return seats.filter(item => item.kind === 'open' && item.seat !== host).map(item => {
    const partner = at((item.seat + 2) % 4);
    const text = item.seat === (host + 2) % 4 ? `Samaan joukkueeseen: ${at(host)?.display_name ?? 'huoneen luoja'}` :
      name(partner) ? `Vastustajaksi (pari: ${name(partner)})` : 'Vastustajaksi';
    return {seat: item.seat, text};
  });
}
// The host's move in the lobby (feature seat_swap): an opponent seat into the
// partner seat opposite the host, or the partner out to it.
function moveAction(seat, {host, playing, features = new Set(), lobby}) {
  const own = hostSeat(lobby), partnerSeat = (own + 2) % 4;
  if (!host || playing || !features.has('seat_swap') || (seat.seat - own + 4) % 2 !== 1) return null;
  const partner = lobby?.seats?.find(item => item.seat === partnerSeat);
  if (seat.kind === 'open' && (!partner || partner.kind === 'open')) return null;
  return {seats: [seat.seat, partnerSeat], text: seat.kind === 'open' ? 'Siirrä parisi tähän' : 'Siirrä pariksi'};
}

// Seats a spectator could take (feature watch): a free seat before the match,
// or one a player left during it (the newcomer plays from the next deal).
function takeableSeats(lobby) {
  const playing = ['playing', 'completed'].includes(lobby?.lifecycle);
  if (lobby?.lifecycle === 'completed') return [];
  return (lobby?.seats ?? []).filter(seat => playing ? seat.vacant : seat.kind === 'open').map(seat => seat.seat);
}
// A seat's name at the table: a stand-in bot says whom it plays for.
function seatDisplayName(seat) {
  return seat?.covering ? `Botti (${seat.covering})` : seat?.display_name;
}

class LobbyView {
  constructor(teams, onToggle, {onRename = () => {}, onRelease = () => {}, onMove = () => {}} = {}) {
    this.teams = teams; this.onToggle = onToggle; this.onRename = onRename; this.onRelease = onRelease; this.onMove = onMove;
    this.nodes = new Map();
  }
  render(model, {host, connected, configuring = false, features = new Set(), lobby = null, watching = false}) {
    model.teams.forEach((seats, index) => {
      const nodes = seats.map(seat => {
        if (!this.nodes.has(seat.seat)) {
          const item = document.createElement('li'); item.className = 'lobby-seat';
          const position = document.createElement('span'); position.className = 'lobby-position';
          const name = document.createElement('strong'); name.className = 'lobby-name';
          const state = document.createElement('span'); state.className = 'lobby-state';
          const button = document.createElement('button'); button.type = 'button';
          button.onclick = () => {
            const node = this.nodes.get(seat.seat);
            if (node.action === 'rename') return this.onRename(node.seat);
            if (node.action === 'release') return this.onRelease(node.seat);
            if (node.action === 'toggle') return this.onToggle(seat.seat);
          };
          const move = document.createElement('button'); move.type = 'button';
          move.onclick = () => { const node = this.nodes.get(seat.seat); if (node.move_action) return this.onMove(node.move_action.seats); };
          item.append(position, name, state, move, button);
          this.nodes.set(seat.seat, {item, position, name, state, button, move});
        }
        const node = this.nodes.get(seat.seat), label = (watching ? watcherSeatNames : seatNames)[seat.position];
        node.position.textContent = label;
        node.name.textContent = seat.display_name || (seat.kind === 'ai' ? 'Botti' : 'Vapaa paikka');
        node.state.textContent = seat.kind === 'ai' ? 'Botti' : seat.kind === 'open' ? 'Odottaa pelaajaa' : seat.ready ? 'Pelaaja · valmis' : 'Pelaaja · ei vielä valmis';
        node.item.dataset.kind = seat.kind;
        node.action = watching ? null : seatAction(seat, {host, playing: model.playing, features}); node.seat = seat;
        node.button.hidden = !node.action;
        node.button.disabled = !connected || configuring;
        node.button.textContent = node.action === 'rename' ? 'Vaihda nimi' : node.action === 'release' ? 'Vapauta paikka' :
          seat.kind === 'ai' ? 'Avaa ystävälle' : 'Lisää botti';
        node.button.setAttribute('aria-label', `${node.button.textContent}: ${label}`);
        node.move_action = watching ? null : moveAction(seat, {host, playing: model.playing, features, lobby});
        node.move.hidden = !node.move_action; node.move.disabled = !connected || configuring;
        node.move.textContent = node.move_action?.text ?? '';
        if (node.move_action) node.move.setAttribute('aria-label', `${node.move_action.text}: ${label}`);
        return node.item;
      });
      const list = this.teams[index];
      if (nodes.length !== list.children.length || nodes.some((node, i) => node !== list.children[i])) list.replaceChildren(...nodes);
    });
  }
}

// Source: replay.mjs
// The game viewer (round 16): replays a match one decision at a time, with
// every hand, the trick on the table, the bids and the score, and a sentence
// for each step, so a person can follow it. The steps come from the engine
// (timeline.mjs, in a worker); this module only converts inputs and draws.
const viewerCompass = ['Etelä', 'Länsi', 'Pohjoinen', 'Itä'];
const viewerLocalNames = ['Sinä', 'Vasen vastustaja', 'Pari', 'Oikea vastustaja'];
const VIEWER_POSITIONS = ['south', 'west', 'north', 'east'];
const viewerSpeeds = {slow: 1800, normal: 1000, fast: 450};

// --- inputs --------------------------------------------------------------

// A local offline save: its finished deals and the deal in progress.
function viewerMatchFromSave(save, {title = 'Oma ottelu'} = {}) {
  if (!Array.isArray(save?.completed)) return null;
  const deals = save.completed.map(deal => ({cards: [...deal.cards], dealer: deal.dealer, score: [...deal.score],
    actions: [...deal.actions], ...(deal.conceded ? {concededAfterTricks: deal.conceded.afterTricks} : {})}));
  if (Array.isArray(save.cards) && save.cards.length === 52 && !save.archived && save.actions?.length)
    deals.push({cards: [...save.cards], dealer: save.dealer, score: [...save.score], actions: [...save.actions]});
  if (!deals.length) return null;
  return {title, source: 'local', seatNames: [...viewerLocalNames], humans: [0], deals};
}

// The engine action id of a research record's move (`[seat, who, action]`,
// `action` as the server's action data, or already an id).
function viewerActionId(action) { return Number.isInteger(action) ? action : networkActionID(action); }

// One research_match_v1 record (the owner's download, one JSON line each) or
// a browser offline match record ({deals: [{cards, dealer, score, actions}]}).
function viewerMatchFromRecord(record, index = 0) {
  if (!Array.isArray(record?.deals) || !record.deals.length) throw new Error('Tiedostossa ei ole jakoja.');
  const humans = new Set();
  const deals = record.deals.map(deal => {
    if (Array.isArray(deal.hands)) {
      const cards = deal.hands.flatMap(hand => hand.map(card => Number.isInteger(card) ? card : networkCard(card)));
      const actions = [], who = [];
      for (const [seat, by, action] of deal.actions ?? []) {
        actions.push(viewerActionId(action)); who.push(by);
        if (by === 'human') humans.add(seat);
      }
      return {cards, dealer: deal.dealer, score: [...deal.score_before], actions, who,
        ...(Number.isInteger(deal.conceded_after_tricks) ? {concededAfterTricks: deal.conceded_after_tricks} : {})};
    }
    return {cards: [...deal.cards], dealer: deal.dealer, score: [...(deal.score ?? deal.score_before)], actions: deal.actions.map(viewerActionId),
      ...(deal.conceded ? {concededAfterTricks: deal.conceded.afterTricks} : {})};
  });
  const where = record.source === 'online' || String(record.id ?? '').startsWith('online') ? 'Verkko-ottelu' :
    record.source === 'offline' || String(record.id ?? '').startsWith('offline') ? 'Offline-ottelu' : 'Ottelu';
  const bot = record.bot ? ` · botti ${record.bot}` : record.worlds ? ` · botti W${record.worlds}` : '';
  const seatNames = viewerCompass.map((name, seat) => humans.size ? `${name} (${humans.has(seat) ? 'ihminen' : 'botti'})` : name);
  return {title: record.title ?? `${where} ${index + 1}${record.day ? ` · ${record.day}` : ''}${bot}`, source: 'record',
    seatNames: record.seatNames ?? seatNames, humans: [...humans], deals};
}

// The text of a replay file, a research download (JSON lines) or a single
// record: every match in it.
function viewerMatchesFromText(text) {
  const trimmed = text.trim();
  if (!trimmed) throw new Error('Tiedosto on tyhjä.');
  let records;
  if (trimmed.startsWith('[')) records = JSON.parse(trimmed);
  else {
    try { records = [JSON.parse(trimmed)]; }
    catch { records = trimmed.split('\n').filter(line => line.trim()).map(line => JSON.parse(line)); }
  }
  if (records.length === 1 && records[0]?.schema === 'tuppi.replay.v1') records = records[0].matches;
  if (!Array.isArray(records) || !records.length) throw new Error('Tiedostossa ei ole otteluita.');
  return records.map((record, index) => viewerMatchFromRecord(record, index));
}

// A replay file of matches (engine ids; no names unless the match has them).
function viewerReplayFile(matches) {
  return {schema: 'tuppi.replay.v1', matches: matches.map(match => ({title: match.title, seatNames: match.seatNames,
    deals: match.deals.map(deal => ({cards: deal.cards, dealer: deal.dealer, score: deal.score, actions: deal.actions,
      ...(deal.concededAfterTricks !== undefined ? {conceded: {afterTricks: deal.concededAfterTricks}} : {})}))}))};
}

// One gzip member; rejects (never throws uncaught) on anything else.
async function viewerGunzip(bytes) {
  const stream = new DecompressionStream('gzip'), writer = stream.writable.getWriter(), reader = stream.readable.getReader();
  const written = writer.write(bytes).then(() => writer.close()).catch(() => {});
  const chunks = [];
  try {
    for (;;) { const {value, done} = await reader.read(); if (done) break; chunks.push(value); }
  } finally { await written; }
  const out = new Uint8Array(chunks.reduce((n, chunk) => n + chunk.length, 0));
  let at = 0; for (const chunk of chunks) { out.set(chunk, at); at += chunk.length; }
  return new TextDecoder().decode(out);
}

// Gzip is read with the browser's own decompressor. The research download is
// one gzip member per match, one after another, which it reads one member at
// a time: split at the gzip headers, merging a part with the next whenever
// the split was not a real member boundary.
async function viewerReadFile(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
  const starts = [];
  for (let i = 0; i + 3 < bytes.length; i++)
    if (bytes[i] === 0x1f && bytes[i + 1] === 0x8b && bytes[i + 2] === 8) starts.push(i);
  starts.push(bytes.length);
  let text = '', from = 0;
  for (let k = 1; k < starts.length; k++) {
    try { text += await viewerGunzip(bytes.subarray(starts[from], starts[k])); from = k; }
    catch (error) { if (k === starts.length - 1) throw error; }
  }
  return text;
}

// --- words ---------------------------------------------------------------

function viewerCard(card) { return `${cardRank(card)}${suits[Math.floor(card / 13)]}`; }
const viewerContractName = contract => contract === 1 ? 'RAMI' : 'NOLO';
function viewerTeamName(names, team) { return `${names[team]} + ${names[team + 2]}`; }

// The sentence for a step. `names` are the four seats' names.
function viewerStepText(step, names, info) {
  const name = seat => names[seat];
  const s = step.state;
  switch (step.kind) {
    case 'start':
      return `Jako ${step.deal + 1}. Jakaja ${name(info.dealer)}. Tilanne ${info.score[0]}–${info.score[1]}.`;
    case 'bid': {
      const text = `${name(step.seat)} näyttää ${viewerCard(step.card)} – ${viewerContractName(step.contract)}.`;
      if (!step.revealed) return text;
      return `${text} Tarjoukset paljastetaan: ${s.contract === 1 ? `${name(s.declarer)} ramaa` : 'pelataan noloa'}.`;
    }
    case 'sooli': return step.accept ? `${name(step.seat)} pelaa soolin.` : `${name(step.seat)}: ei soolia.`;
    case 'give': return step.card === null ? `${name(step.seat)} antaa parilleen kortin (ei näy sinulle).` : `${name(step.seat)} antaa parilleen kortin ${viewerCard(step.card)}.`;
    case 'return': return step.card === null ? `${name(step.seat)} palauttaa kortin (ei näy sinulle).` : `${name(step.seat)} palauttaa kortin ${viewerCard(step.card)}.`;
    case 'card': {
      let text = `${name(step.seat)} pelaa ${viewerCard(step.card)}${step.forced ? ' (luovutettu jako)' : ''}.`;
      if (step.winner !== null) text += ` ${name(step.winner)} voittaa tikin ${step.trickNumber}.`;
      if (step.result) {
        const r = step.result;
        text += ` Jako päättyy: ${viewerTeamName(names, r.winnerTeam)} ${r.points} pistettä (tikit ${r.tricks[0]}–${r.tricks[1]}). Tilanne ${r.scoreAfter[0]}–${r.scoreAfter[1]}.`;
      }
      return text;
    }
    default: return '';
  }
}

// --- the viewer ----------------------------------------------------------

/* The viewer screen. `el(id)` finds its elements; `timeline(match)` returns a
   promise of the engine's timeline for a match. Every hand is shown; "only"
   (Näytä vain tämän pelaajan kortit) hides all but the viewpoint's, to
   follow one player's decisions. */
class ReplayViewer {
  constructor({el, timeline, suitOrder = () => [0, 1, 2, 3], onClose = () => {}, onLive = null, onSpeed = null}) {
    this.el = el; this.requestTimeline = timeline; this.suitOrder = suitOrder; this.onClose = onClose;
    this.onLive = onLive; this.onSpeed = onSpeed; this.match = null; this.data = null; this.position = 0; this.viewpoint = 0;
    this.only = false; this.timer = null; this.speed = 'normal'; this.live = false; this.choicesKey = null;
    this.wire();
  }

  wire() {
    const e = this.el, go = fn => () => { this.pause(); fn(); this.render(); };
    e('viewer-close').onclick = () => { this.pause(); this.onClose(); };
    e('viewer-step-prev').onclick = go(() => this.step(-1));
    e('viewer-step-next').onclick = go(() => this.step(1));
    e('viewer-trick-prev').onclick = go(() => this.trick(-1));
    e('viewer-trick-next').onclick = go(() => this.trick(1));
    e('viewer-deal-prev').onclick = go(() => this.deal(-1));
    e('viewer-deal-next').onclick = go(() => this.deal(1));
    e('viewer-play').onclick = () => { this.timer ? this.pause() : this.play(); this.render(); };
    e('viewer-speed').onchange = () => {
      this.speed = e('viewer-speed').value; this.onSpeed?.(viewerSpeeds[this.speed]);
      if (this.timer) { this.pause(); this.play(); }
    };
    e('viewer-position').onchange = () => { this.pause(); this.setDealPosition(Number(e('viewer-position').value)); this.render(); };
    e('viewer-deal').onchange = () => { this.pause(); this.position = this.data.deals[Number(e('viewer-deal').value)].start; this.render(); };
    e('viewer-viewpoint').onchange = () => { this.viewpoint = Number(e('viewer-viewpoint').value); this.render(); };
    e('viewer-only').onchange = () => { this.only = e('viewer-only').checked; this.render(); };
    // Live games: back to the newest step (and following again), or the host's own action.
    e('viewer-live').onclick = () => {
      this.pause();
      if (this.onLive) { this.onLive(); return; }
      if (this.data?.steps.length) this.position = this.data.steps.length - 1;
      this.render();
    };
  }

  // Loads a match; `deal` and `index` choose the first step shown.
  async load(match, {deal = 0, index = -1, viewpoint = 0, live = false} = {}) {
    this.pause(); this.match = match; this.viewpoint = viewpoint; this.live = live; this.data = null; this.choicesKey = null;
    this.el('viewer-status').textContent = 'Valmistellaan toistoa…';
    this.render();
    const data = await this.requestTimeline(match);
    if (this.match !== match) return;  // another load replaced it
    this.data = data;
    const info = data.deals[Math.min(deal, data.deals.length - 1)];
    this.position = index < 0 ? info.start : Math.min(info.end, info.start + 1 + index);
    this.el('viewer-status').textContent = '';
    this.renderChoices(); this.render();
  }

  // A game that is still being played (bot games): `data` grows in place.
  startLive(match, data, {label = 'Uusimpaan siirtoon'} = {}) {
    this.pause(); this.match = match; this.data = data; this.live = true; this.position = 0; this.choicesKey = null;
    this.following = true; this.el('viewer-live').textContent = label;
    this.renderChoices(); this.render();
  }

  // The live timeline grew: follow the newest step unless the person has
  // stepped back (then the live button brings them back).
  update() {
    if (!this.data?.steps.length) return;
    const last = this.data.steps.length - 1;
    if (this.following || this.position > last) this.position = last;
    this.renderChoices(); this.render();
  }

  get current() { return this.data?.steps[this.position] ?? null; }
  // Following a live game means standing at its newest step.
  get following() { return this.live && (this.followFlag ?? true); }
  set following(value) { this.followFlag = value; }
  dealInfo(step = this.current) { return step ? this.data.deals[step.deal] : null; }
  atLive() { return this.data && this.position === this.data.steps.length - 1; }

  step(delta) {
    if (!this.data) return false;
    const next = Math.max(0, Math.min(this.data.steps.length - 1, this.position + delta));
    const moved = next !== this.position; this.position = next; return moved;
  }
  // To the end of the previous or next completed trick, or a deal's start.
  trick(delta) {
    if (!this.data) return;
    const steps = this.data.steps;
    for (let i = this.position + delta; i >= 0 && i < steps.length; i += delta) {
      if (steps[i].winner !== null || steps[i].kind === 'start') { this.position = i; return; }
    }
    this.position = delta < 0 ? 0 : steps.length - 1;
  }
  // Back: to this deal's start, or the previous deal's if already there.
  deal(delta) {
    if (!this.data) return;
    const here = this.current.deal;
    if (delta < 0 && this.position !== this.data.deals[here].start) { this.position = this.data.deals[here].start; return; }
    this.position = this.data.deals[Math.max(0, Math.min(this.data.deals.length - 1, here + delta))].start;
  }
  setDealPosition(offset) {
    const info = this.dealInfo();
    if (info) this.position = Math.max(info.start, Math.min(info.end, info.start + offset));
  }

  play() {
    if (!this.data) return;
    if (this.atLive() && !this.live) this.position = this.dealInfo().start;
    const tick = () => {
      const step = this.current;
      if (!this.step(1)) { this.pause(); this.render(); return; }  // the end (live games keep following)
      this.render();
      const wait = viewerSpeeds[this.speed] * (step?.winner !== null || step?.result ? 1.6 : 1);
      this.timer = setTimeout(tick, wait);
    };
    this.timer = setTimeout(tick, viewerSpeeds[this.speed] / 2);
  }
  pause() { if (this.timer) clearTimeout(this.timer); this.timer = null; }

  handleKey(event) {
    const keys = {ArrowLeft: () => this.step(-1), ArrowRight: () => this.step(1), ArrowUp: () => this.trick(-1),
      ArrowDown: () => this.trick(1), PageUp: () => this.deal(-1), PageDown: () => this.deal(1),
      Home: () => { this.position = this.dealInfo()?.start ?? 0; }, End: () => { this.position = this.dealInfo()?.end ?? 0; }};
    if (event.key === ' ') { event.preventDefault(); this.timer ? this.pause() : this.play(); this.render(); return true; }
    if (!keys[event.key] || !this.data) return false;
    event.preventDefault(); this.pause(); keys[event.key](); this.render(); return true;
  }

  renderChoices() {
    const e = this.el, names = this.match.seatNames;
    // Rebuilt only when a deal starts or ends.
    const key = this.data ? `${this.data.deals.length}:${this.data.deals.filter(info => info.complete).length}` : null;
    if (!this.data || key === this.choicesKey) return;
    this.choicesKey = key;
    e('viewer-deal').replaceChildren(...this.data.deals.map((info, d) => {
      const option = document.createElement('option');
      option.value = String(d);
      option.textContent = `Jako ${d + 1}${info.result ? ` · ${viewerTeamName(names, info.result.winnerTeam)} +${info.result.points}` : ' · kesken'}`;
      return option;
    }));
    e('viewer-viewpoint').replaceChildren(...names.map((name, seat) => {
      const option = document.createElement('option'); option.value = String(seat); option.textContent = name; return option;
    }));
  }

  render() {
    const e = this.el, step = this.current, names = this.match?.seatNames ?? viewerCompass;
    if (this.live && this.data) this.followFlag = this.position === this.data.steps.length - 1;
    e('viewer-title').textContent = this.match?.title ?? 'Toisto';
    const ready = Boolean(step);
    for (const id of ['viewer-step-prev', 'viewer-step-next', 'viewer-trick-prev', 'viewer-trick-next',
      'viewer-deal-prev', 'viewer-deal-next', 'viewer-play', 'viewer-position', 'viewer-deal', 'viewer-viewpoint', 'viewer-only'])
      e(id).disabled = !ready;
    e('viewer-live').hidden = !this.live;
    e('viewer-live').disabled = !ready || this.atLive();
    e('viewer-play').textContent = this.timer ? 'Tauko' : 'Toista';
    e('viewer-play').setAttribute('aria-pressed', String(Boolean(this.timer)));
    if (!ready) { e('viewer-narration').textContent = ''; return; }
    const info = this.dealInfo(), s = step.state;
    e('viewer-step-prev').disabled = this.position === 0;
    e('viewer-step-next').disabled = this.position === this.data.steps.length - 1;
    e('viewer-deal').value = String(step.deal);
    e('viewer-viewpoint').value = String(this.viewpoint);
    e('viewer-only').checked = this.only;
    e('viewer-position').max = String(info.end - info.start);
    e('viewer-position').value = String(this.position - info.start);
    e('viewer-position').setAttribute('aria-valuetext', `Jako ${step.deal + 1}, siirto ${this.position - info.start}/${info.end - info.start}`);
    e('viewer-deal-label').textContent = `Jako ${step.deal + 1}/${this.data.deals.length} · siirto ${this.position - info.start}/${info.end - info.start}`;
    e('viewer-narration').textContent = viewerStepText(step, names, info);
    const bidding = s.phase === 0;
    e('viewer-contract').textContent = bidding ? 'Tarjoukset' : s.soolaaja >= 0 ? `Sooli: ${names[s.soolaaja]}` :
      s.contract === 1 ? `RAMI: ${names[s.declarer]}` : 'NOLO';
    const score = step.result?.scoreAfter ?? info.score;
    e('viewer-score').textContent = `${viewerTeamName(names, 0)} ${score[0]} – ${score[1]} ${viewerTeamName(names, 1)}`;
    e('viewer-tricks').textContent = bidding ? '' : `Tikit ${s.tricks0}–${s.tricks1}`;
    this.renderSeats(step, names, info);
    this.renderTrick(step, names);
    this.renderTrickList(step, names);
  }

  renderSeats(step, names, info) {
    const s = step.state, order = this.suitOrder(), aceLow = s.soolaaja >= 0;
    for (let seat = 0; seat < 4; seat++) {
      const box = this.el(`viewer-seat-${(seat - this.viewpoint + 4) % 4}`);
      const title = document.createElement('strong'), meta = document.createElement('span'), hand = document.createElement('div');
      title.textContent = names[seat];
      const bid = step.bids.find(item => item.seat === seat);
      meta.textContent = [seat === info.dealer ? 'jakaja' : '',
        s.phase !== 0 && s.contract === 1 && s.declarer === seat ? 'ramaaja' : '',
        s.soolaaja === seat ? 'soolaaja' : s.soolaaja >= 0 && seat === (s.soolaaja + 2) % 4 ? 'ei pelaa' : '',
        bid ? `näytti ${viewerCard(bid.card)} ${viewerContractName(bid.contract)}${s.phase === 0 ? ' (lukittu)' : ''}` : ''].filter(Boolean).join(' · ');
      hand.className = 'viewer-hand';
      // null: a hand this person may not see (the deal in play online).
      const cards = step.hands[seat];
      if (cards === null || (this.only && seat !== this.viewpoint)) {
        hand.textContent = `${cards?.length ?? step.counts[seat]} korttia`;
      } else {
        const rank = card => aceLow && card % 13 === 12 ? -1 : card % 13;
        for (const suit of order) {
          const inSuit = cards.filter(card => Math.floor(card / 13) === suit).sort((a, b) => rank(b) - rank(a));
          const row = document.createElement('span');
          row.className = `viewer-suit suit-${suit}`;
          row.textContent = `${suits[suit]} ${inSuit.length ? inSuit.map(cardRank).join(' ') : '–'}`;
          hand.append(row);
        }
      }
      box.className = `viewer-seat ${VIEWER_POSITIONS[(seat - this.viewpoint + 4) % 4]}`;
      box.classList.toggle('moved', step.seat === seat);
      box.classList.toggle('to-move', s.phase !== 2 && s.actor === seat);
      box.replaceChildren(title, meta, hand);
    }
  }

  renderTrick(step, names) {
    const trick = this.el('viewer-trick');
    trick.replaceChildren(...step.trick.map(play => {
      const card = document.createElement('span');
      card.className = `viewer-played ${VIEWER_POSITIONS[(play.seat - this.viewpoint + 4) % 4]} suit-${Math.floor(play.card / 13)}`;
      card.classList.toggle('winner', step.winner === play.seat);
      card.textContent = viewerCard(play.card);
      card.setAttribute('aria-label', `${names[play.seat]}: ${viewerCard(play.card)}`);
      return card;
    }));
  }

  // The deal's completed tricks so far; a click jumps to that trick.
  renderTrickList(step, names) {
    const info = this.dealInfo(), items = [];
    for (let i = info.start; i <= this.position; i++) {
      const done = this.data.steps[i];
      if (done.winner === null) continue;
      const item = document.createElement('li'), button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${done.trickNumber}. ${done.trick.map(play => viewerCard(play.card)).join(' ')} → ${names[done.winner]}`;
      button.onclick = () => { this.pause(); this.position = i; this.render(); };
      item.append(button); items.push(item);
    }
    this.el('viewer-trick-list').replaceChildren(...items);
  }
}

// Source: live.mjs
// Going back in live online games (round 16): viewer steps for a deal from
// what this client may see, without the engine. Finished deals normally come
// in full from the server (feature deal_records) and are replayed on the
// engine; this builds the deal in play, and finished deals on servers without
// that feature. A hand this client may not see is null (the viewer shows only
// its card count). A spectator sees every hand; a player only their own.
//
// Seats are the server's (0-3). Cards are engine numbers.
const liveCard = code => networkCard(code);
const liveContract = value => value === 'RAMI' ? 1 : 0;

// The common shape of a deal in play (an observation) and a finished deal
// (a public deal result): bids, sooli, tricks in order and the hands held now.
// In a sooli deal the soolaaja gives a card (`gave`), then the partner
// returns one (`back`); either card is known only to the two of them.
function livePublicDeal({dealer, score, shows, sooli, tricks, current, held, contract, declarer, actor = null, result = null, phase = null}) {
  const solo = sooli?.soolaaja ?? null, exchanged = solo !== null && (Boolean(sooli.exchanged) || Boolean(result));
  return {dealer, score: [...score], shows: shows.map(show => ({seat: show.seat, card: liveCard(show.shown_card), contract: liveContract(show.declared_contract)})),
    decisions: (sooli?.decisions ?? []).map(item => ({seat: item.seat, accept: item.play_sooli})),
    soolaaja: solo, gave: exchanged || (solo !== null && phase === 'SOOLI_RETURN'), back: exchanged,
    given: sooli?.given_card ? liveCard(sooli.given_card) : null, returned: sooli?.returned_card ? liveCard(sooli.returned_card) : null,
    tricks: [...tricks.map(trick => ({plays: trick.plays.map(play => ({seat: play.seat, card: liveCard(play.card)})), winner: trick.winner})),
      ...(current.length ? [{plays: current.map(play => ({seat: play.seat, card: liveCard(play.card)})), winner: null}] : [])],
    held, contract: contract === null || contract === undefined ? null : liveContract(contract), declarer: declarer ?? null, actor, result};
}

// The deal in play, from a live update's observation. `hands` are the four
// seats' cards now if this client may see them all (a spectator's table),
// otherwise only the observing seat's own cards are known.
function liveDealFromObservation(observation, hands = null, scoreBefore = null) {
  const held = hands ? hands.map(hand => hand.map(liveCard)) :
    [0, 1, 2, 3].map(seat => seat === observation.observing_seat ? observation.own_hand.map(liveCard) : null);
  return livePublicDeal({dealer: observation.dealer, score: scoreBefore ?? observation.match_score, shows: observation.show_actions,
    sooli: observation.sooli, tricks: observation.completed_tricks, current: observation.current_trick, held,
    contract: observation.contract, declarer: observation.declarer, actor: observation.current_actor, phase: observation.phase});
}

// A finished deal's public result: a hand is known when all 13 of its cards
// were played (a sooli deal may end early, and the sitting-out partner plays
// none); the exchange is never known.
function liveDealFromResult(deal) {
  const played = [0, 1, 2, 3].map(seat => deal.tricks.reduce((n, trick) => n + trick.plays.filter(play => play.seat === seat).length, 0));
  const held = played.map(count => count === 13 ? [] : null);
  return livePublicDeal({dealer: deal.dealer, score: deal.score_before, shows: deal.show_actions, sooli: deal.sooli, tricks: deal.tricks,
    current: [], held, contract: deal.contract, declarer: deal.declarer,
    result: {winnerTeam: deal.deal_score.winner_team, points: deal.deal_score.points, tricks: [...deal.team_tricks],
      scoreAfter: [...deal.score_after]}});
}

// Viewer steps for deal number `d` (shape as timeline.mjs). Hands are
// rebuilt backwards: the cards held now plus those played since, with the
// sooli exchange undone where this client knows it; where it does not (a
// spectator), the soolaaja and the partner are shown with their cards after it.
function liveDealSteps(deal, d, {concededAfterTricks = null} = {}) {
  const solo = deal.soolaaja, partner = solo === null ? null : (solo + 2) % 4;
  const plays = deal.tricks.flatMap(trick => trick.plays);
  const dealt = deal.held.map((hand, seat) => hand && [...hand, ...plays.filter(play => play.seat === seat).map(play => play.card)]);
  // Undo the exchange where its cards are known (to the soolaaja and partner).
  const giveKnown = deal.gave && deal.given !== null, backKnown = deal.back && deal.returned !== null;
  const transfer = (from, to, c) => {
    if (dealt[from]) dealt[from] = dealt[from].filter(x => x !== c);
    if (dealt[to]) dealt[to] = [...dealt[to], c];
  };
  if (backKnown) transfer(solo, partner, deal.returned);
  if (giveKnown) transfer(partner, solo, deal.given);
  const hands = dealt.map(hand => hand && [...hand]), counts = dealt.map(hand => hand ? hand.length : 13);
  const steps = [], bids = [];
  let state = {phase: 0, actor: -1, dealer: deal.dealer, contract: 0, declarer: -1, soolaaja: -1, trickSize: 4, tricks0: 0, tricks1: 0};
  const push = fields => {
    const step = {deal: d, index: steps.length - 1, seat: null, action: null, who: null, trick: [], winner: null,
      hands: hands.map(hand => hand && [...hand]), counts: [...counts], bids: bids.map(bid => ({...bid})), state: {...state}, ...fields};
    steps.push(step); return step;
  };
  push({kind: 'start'});
  deal.shows.forEach((show, i) => {
    bids.push(show);
    const last = i === deal.shows.length - 1 && deal.contract !== null;
    if (last) state = {...state, phase: deal.decisions.length ? 3 : 1, contract: deal.contract, declarer: deal.declarer ?? -1};
    push({kind: 'bid', seat: show.seat, card: show.card, contract: show.contract, revealed: last});
  });
  for (const decision of deal.decisions) push({kind: 'sooli', seat: decision.seat, accept: decision.accept});
  // An exchange card this client does not know: the hands already hold the
  // cards after it, and only the counts move.
  const move = (from, to, c, known) => {
    counts[from]--; counts[to]++;
    if (!known) return;
    if (hands[from]) hands[from] = hands[from].filter(x => x !== c);
    if (hands[to]) hands[to] = [...hands[to], c];
  };
  if (solo !== null) state = {...state, phase: 4, soolaaja: solo, trickSize: 3};
  if (deal.gave) { move(solo, partner, deal.given, giveKnown); state = {...state, phase: 5}; push({kind: 'give', seat: solo, card: giveKnown ? deal.given : null}); }
  if (deal.back) { move(partner, solo, deal.returned, backKnown); push({kind: 'return', seat: partner, card: backKnown ? deal.returned : null}); }
  if (deal.contract !== null && (solo === null || deal.back)) state = {...state, phase: solo !== null ? 6 : 1};
  deal.tricks.forEach((trick, t) => {
    trick.plays.forEach((play, p) => {
      counts[play.seat]--;
      if (hands[play.seat]) hands[play.seat] = hands[play.seat].filter(c => c !== play.card);
      const won = p === trick.plays.length - 1 && trick.winner !== null && trick.winner !== undefined;
      if (won) state = {...state, [`tricks${trick.winner % 2}`]: state[`tricks${trick.winner % 2}`] + 1};
      const next = trick.plays[p + 1]?.seat ?? (won ? trick.winner : deal.actor);
      state = {...state, actor: next ?? -1};
      push({kind: 'card', seat: play.seat, card: play.card, trick: trick.plays.slice(0, p + 1), winner: won ? trick.winner : null,
        trickNumber: t + 1, ...(concededAfterTricks !== null && t + 1 > concededAfterTricks ? {forced: true} : {})});
    });
  });
  const info = {start: 0, end: steps.length - 1, dealer: deal.dealer, score: [...deal.score], complete: Boolean(deal.result),
    result: null, concededAfterTricks, live: !deal.result};
  if (deal.result) {
    const last = steps.at(-1), result = {...deal.result};
    last.result = result; last.state = {...last.state, phase: 2}; info.result = result;
  } else steps.at(-1).state = {...steps.at(-1).state, actor: deal.actor ?? -1};
  return {steps, info};
}

// One timeline from deals built separately ({steps, info} each, in deal
// order): steps renumbered to their deal, deal starts and ends offset.
function liveTimeline(parts) {
  const steps = [], deals = [];
  parts.forEach(({steps: own, info}, d) => {
    const start = steps.length;
    for (const step of own) steps.push({...step, deal: d});
    deals.push({...info, start, end: steps.length - 1});
  });
  return {steps, deals};
}

// Deal `d` of an engine timeline as a part for liveTimeline.
function timelinePart(timeline, d) {
  const info = timeline.deals[d];
  return {steps: timeline.steps.slice(info.start, info.end + 1), info};
}

// Source: app.mjs
const $ = id => document.getElementById(id);
// Heidi 1.1 is Heidi 1.0's search on the faster engine; saves and replays from
// the earlier engine keep the name Heidi 1.0. Nelli 1.0 is the lite bot once
// called Heidi 0.5 (id heidi05, profile tuppi_ai_lite_c1h_v1): only the name changed.
// Heidi 1.2 and Nelli 1.1 are Heidi 1.1 and Nelli 1.0 with the new base network.
// Dan 1.1 adds his guarded NOLO habit and conservative bidding beside those two.
// The older ids stay selectable for their saves.
const heidiNames = {heidi05: 'Nelli 1.0', nelli11: 'Nelli 1.1', heidi10: 'Heidi 1.0', heidi11: 'Heidi 1.1', heidi12: 'Heidi 1.2', dan11: 'Dan 1.1'};
const onlineHeidiNames = {tuppi_ai_lite_c1h_v1: 'Nelli 1.0', tuppi_ai_lite_c1h_v2: 'Nelli 1.1',
  tuppi_ai_heidi10_pib8_v1: 'Heidi 1.1', tuppi_ai_heidi12_pib8_v1: 'Heidi 1.2', tuppi_ai_dan11_v1: 'Dan 1.1'};
// A new game started from an older bot's selection plays that bot's current version.
const currentLocalBots = {heidi05: 'nelli11', heidi10: 'heidi12', heidi11: 'heidi12'};
const liteLocalBots = ['heidi05', 'nelli11'];  // W128; the Heidi search bots are W1024
// The online bots new rooms may choose, shown when the server lists them in bot_options.
const onlineBotChoices = [['network-nelli11-option', 'tuppi_ai_lite_c1h_v2'], ['network-heidi12-option', 'tuppi_ai_heidi12_pib8_v1'], ['network-dan11-option', 'tuppi_ai_dan11_v1']];
function botSelection(save = null) {
  let value = save ? (save.bot ?? String(save.worlds)) : $('worlds').value;
  if (!save) value = currentLocalBots[value] ?? value;
  return value in heidiNames ? {bot: value, worlds: value === 'dan11' ? 64 : liteLocalBots.includes(value) ? 128 : 1024} :
    {bot: 'legacy', worlds: save?.worlds ?? Number(value)};
}
function botSelectionValue(save) { return save?.bot ?? String(save?.worlds ?? 128); }
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
let liveViewer = null;  // the viewer over a live online game (round 16)
let networkClient = null, savedNetwork = null, networkAddress = null, offlineStarted = false, networkRevealDeal = null;
let screen = 'home', entryReady = false, networkResolved = false, navigationPending = false, navigationToken = 0;
let roomIntent = 'join', invitation = false, entryPending = false, passcodeRequired = null, passcodeCheck = null;
let awaitingNetworkGame = false;
// Room chat (feature chat): messages from the network session, unread count
// while the chat is closed, and the dialog to return to when it closes.
let chatMessages = [], chatUnread = 0, chatReturn = null, chatToastTimer = null;
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
  networkAddress = address; networkResolved = true; sendOfflineResults();
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
  const resumable = Boolean(session?.active && !session.released && session.base === networkAddress);
  $('home-online').textContent = resumable ? `Jatka huoneessa ${session.room_code}` : 'Pelaa verkossa';
  $('home-online-other').hidden = !networkEnabled || !resumable;
  $('home-online-other').disabled = $('home-online').disabled;
  $('home-local').disabled = !entryReady || !writeAccess || !localReadable || changingLocal || navigationPending || entryPending;
  $('home-local').textContent = lastSave || (worker && !networkClient) ? 'Jatka omaa peliä' : 'Pelaa botteja vastaan';
  $('home-viewer-own').disabled = !viewerMatchFromSave(lastSave);
  $('home-local-copy').textContent = lastSave ? 'Tallennettu ottelusi jatkuu siitä, mihin jäit.' : 'Pelaa omaan tahtiin. Ottelu tallentuu tälle laitteelle.';
  $('network-toggle').hidden = !networkEnabled || !networkClient?.session;
  renderViewerToggle();
  renderChatButtons();
}
function showGame() {
  screen = 'game'; $('home').hidden = true; $('viewer').hidden = true; $('game').hidden = $('game-footer').hidden = false;
  renderViewerToggle();
  $('mode-label').textContent = !networkClient?.session ? '· Paikallinen peli' :
    `· ${networkClient.session.watching ? 'Katsot huonetta' : 'Verkkopeli'} ${networkClient.session.room_code}`;
  const botName = networkClient?.session ?
    (onlineHeidiNames[networkClient.session.lobby?.bot_profile] ?? '') :
    heidiNames[view?.bot ?? lastSave?.bot];
  if (botName) $('mode-label').textContent += ` · ${botName}`;
}
function showHome() {
  navigationToken++; awaitingNetworkGame = false;
  document.querySelector('dialog[open]')?.close();
  screen = 'home'; $('home').hidden = false; $('viewer').hidden = true; $('game').hidden = $('game-footer').hidden = true;
  renderViewerToggle();
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
  $('network-bot-row').hidden = !creating;
  $('network-bot').disabled = entryPending;
  $('network-passcode-row').hidden = !creating || passcodeRequired === false;
  $('network-submit').textContent = entryPending ? 'Yhdistetään…' : creating ? 'Luo huone' : 'Liity huoneeseen';
  $('network-submit').disabled = !entryReady || !writeAccess || !networkAddress || entryPending;
  // Watching (feature watch) is offered next to joining; a server without it refuses.
  $('network-watch').hidden = creating || !networkAddress; $('network-watch').disabled = $('network-submit').disabled;
  $('network-reload').hidden = !networkResolved || Boolean(networkAddress);
  for (const id of ['network-name', 'network-code', 'network-passcode', 'network-switch', 'network-resume', 'network-leave']) $(id).disabled = entryPending;
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
  $('network-local').hidden = false; $('network-leave').hidden = true;
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
  const nickname = seatDisplayName(networkClient?.session?.lobby?.seats.find(s => networkSeat(s.seat, viewSeat()) === seat));
  const name = !networkClient && seat !== 0 && heidiNames[view?.bot] ?
    heidiNames[view.bot] : seatNames[seat];
  return seatPresentation(view, seat, nickname || name);
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
    `Alkukäsi: ${preferences.suitOrder.map(suit => `${suitNames[suit]} ${summary.suitLengths[suit]}`).join(', ')}. HCP ${summary.highCardPoints}. HCP laskee kuvakorttipisteet: ässä 4, kuningas 3, rouva 2 ja jätkä 1.` :
    'Alkukäden yhteenveto ei ole saatavilla tässä pelissä.';
}

function renderHistory(completed) {
  const rows = completed.toReversed().map(deal => {
    if (!historyRows.has(deal.index)) {
      const row = document.createElement('div'); row.className = 'history-row';
      const label = document.createElement('span'), button = document.createElement('button');
      // Offline deals open in the viewer (every hand); online ones keep the trick replay.
      button.textContent = 'Toista jako'; button.onclick = () => networkClient ? openReplay(row.deal) : openOwnViewer(row.deal.index);
      const analyse = document.createElement('button'); analyse.textContent = 'Analysoi';
      analyse.onclick = () => openAnalysis(row.deal);
      row.append(label, button, analyse); historyRows.set(deal.index, row);
    }
    const row = historyRows.get(deal.index); row.deal = deal;
    row.children[0].textContent = `Jako ${deal.index + 1} · ${deal.result.soolaaja >= 0 ? 'SOOLI' : deal.result.contract ? 'RAMI' : 'NOLO'} · ${deal.result.winnerTeam === 0 ? 'meille' : 'vastustajille'} ${deal.result.points} p` +
      (deal.conceded ? ` · luovutettu ${deal.conceded.afterTricks} tikin jälkeen` : '');
    row.children[1].setAttribute('aria-label', `Toista jako ${deal.index + 1}`);
    row.children[2].setAttribute('aria-label', `Analysoi jako ${deal.index + 1}`);
    row.children[2].hidden = !analysisRequest(deal);
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
  renderViewerToggle();
  renderLocalChoices(); renderNetworkControls(); renderHome();
  $('export').disabled = !lastSave;
  for (const id of ['worlds', 'pacing', 'new-game', 'import']) $(id).disabled = Boolean(networkClient);
  for (const id of ['worlds', 'new-game', 'import']) $(id).disabled ||= changingLocal || !writeAccess || !localReadable;
  if (!view) {
    $('history-section').hidden = true;
    handView.render([], {allowed: []}); layoutHand(); $('bid-reveal').replaceChildren(); $('trick').replaceChildren(); delete $('trick').dataset.cards;
    $('own-seat-details').disabled = $('hand-details').disabled = true;
    $('starting-hand').hidden = true;
    for (const id of ['bid-controls', 'card-controls', 'concede-controls', 'sooli-controls', 'next-controls', 'trick-panel']) $(id).hidden = true;
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
  // A spectator sees the teams by name; a player sees their own team first.
  const teamLabels = view.watching ? [teamName([0, 2]), teamName([1, 3])].map(name => name.toUpperCase()) : ['SINÄ + PARI', 'VASTUSTAJAT'];
  $('our-score-label').textContent = teamLabels[0]; $('their-score-label').textContent = teamLabels[1];
  renderStair('our-tricks', teamLabels[0], view.tricks0);
  renderStair('their-tricks', teamLabels[1], view.tricks1);
  for (let seat = 0; seat < 4; seat++) {
    const panel = $(`seat-${seat}`);
    const name = panel.querySelector('.seat-name');
    const info = seatInfo(seat);
    if (name) { name.textContent = info.name; name.setAttribute('aria-label', `${info.name}: ${info.detail}${info.active ? ' · Vuorossa' : ''}. Näytä tiedot`); }
    panel.classList.toggle('active', info.active);
    // A spectator sees the other seats' cards; players see how many.
    panel.querySelector('.seat-cards').textContent = view.watching && seat ? [handText(view.tableHands[seat]), info.position].filter(Boolean).join(' · ') :
      [info.count, info.position].filter(Boolean).join(' · ');
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
  $('analyse-deal').hidden = !analysisRequest(view.completed?.at(-1));
  // A decided deal (result 0-0 whatever is played) can be conceded: online by
  // any player at any time, offline on the player's turn (the bots are idle).
  $('concede-controls').hidden = !view.concedeAvailable || revealing || (!networkClient && !canSelect());
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
    const lengths = preferences.suitOrder.map(suit => { const count = summary.suitLengths[suit];
      const item = document.createElement('span'); item.className = `suit-length suit-${suit}`;
      item.innerHTML = `<span class="summary-suit" aria-hidden="true">${suitSVG(suit)}</span>`;
      const number = document.createElement('span'); number.textContent = count; item.append(number); return item;
    });
    const points = document.createElement('span'); points.className = 'hand-points'; points.textContent = `HCP ${summary.highCardPoints}`;
    $('starting-hand').replaceChildren(...lengths, points);
    $('starting-hand').setAttribute('aria-label', `Alkukäsi: ${preferences.suitOrder.map(suit => `${suitNames[suit]} ${summary.suitLengths[suit]}`).join(', ')}, HCP ${summary.highCardPoints}`);
  }
  const allowedCards = legalCards(view, bidContract);
  handView.render(sortedHand(view, preferences.suitOrder), {allowed: allowedCards});
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
  const result = view.watching ? null : matchSummary(view);
  if (result && !networkClient && lastSave) queueOfflineResult(lastSave);
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
// Anonymous offline results and match records (Settings › Tutkimus, on unless
// turned off): queued on this device and sent to this site's server when it
// accepts them. A record holds every card and move (about 3 KB a deal), so
// fewer wait at a time.
const resultsKey = 'tuppi.results.v1', recordsKey = 'tuppi.matchrecords.v1';
const outboxes = [{key: resultsKey, path: '/v1/results', keep: 20}, {key: recordsKey, path: '/v1/research/matches', keep: 5}];
function resultsQueue(key = resultsKey) {
  const keep = outboxes.find(box => box.key === key).keep;
  try { const value = JSON.parse(globalThis.localStorage?.getItem(key) ?? 'null');
    return {pending: Array.isArray(value?.pending) ? value.pending.slice(-keep) : [], sent: Array.isArray(value?.sent) ? value.sent.slice(-100) : []}; }
  catch { return {pending: [], sent: []}; }
}
function storeResults(queue, key = resultsKey) { try { globalThis.localStorage?.setItem(key, JSON.stringify(queue)); } catch {} }
let reportedResult = null, resultsSending = false;
async function queueOfflineResult(save) {
  if (!preferences.shareResults) return;
  const report = await offlineResultReport(save).catch(() => null);
  if (!report || report.id === reportedResult) return;
  reportedResult = report.id;
  const record = await offlineMatchRecord(save).catch(() => null);
  for (const [key, item] of [[resultsKey, report], [recordsKey, record]]) {
    const queue = resultsQueue(key);
    if (item && !queue.sent.includes(item.id) && !queue.pending.some(waiting => waiting.id === item.id)) {
      queue.pending.push(item); storeResults(queue, key);
    }
  }
  sendOfflineResults();
}
async function sendOfflineResults() {
  if (resultsSending || !networkAddress || !preferences.shareResults) return;
  resultsSending = true;
  try {
    for (const {key, path} of outboxes) {
      for (const report of resultsQueue(key).pending) {
        let status;
        try {
          status = (await fetch(new URL(path, networkAddress), {method: 'POST', cache: 'no-store', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(report)})).status;
        } catch { return; }  // offline: try again later
        if (status === 429 || status >= 500) break;
        const queue = resultsQueue(key);  // sent (200) or refused (4xx, e.g. an older server): never retried
        queue.pending = queue.pending.filter(item => item.id !== report.id);
        if (status === 200) queue.sent.push(report.id);
        storeResults(queue, key);
      }
    }
  } finally { resultsSending = false; }
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

function boot(save = null, {replace = false, engine = new URL('./engine.4b565d59f821d534.mjs', import.meta.url), identity = save?.identity ?? packagedRuntimeIdentity} = {}) {
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
  const {worlds, bot} = botSelection(save); $('worlds').value = bot === 'legacy' ? String(worlds) : bot;
  $('mode-label').textContent = `· Paikallinen peli${heidiNames[bot] ? ' · ' + heidiNames[bot] : ''}`;
  worker.postMessage({type: 'init', generation, worlds, bot, delay: Number($('pacing').value), save});
}

document.querySelectorAll('[data-contract]').forEach(button => { button.onclick = () => selectContract(Number(button.dataset.contract)); });
document.querySelectorAll('[data-action]').forEach(button => { button.onclick = () => {
  const action = Number(button.dataset.action);
  if (canSelect() && view.legal.includes(action)) post('submit', {action});
}});
$('lock-bid').onclick = submitSelected;
$('play-card').onclick = submitSelected;
$('next-deal').onclick = () => { if (!busy && view?.phase === 2 && !view.terminal) post('next'); };
$('concede').onclick = () => {
  if (!view?.concedeAvailable) return;
  selectedCard = null; keyboard.reset();
  if (networkClient) { if (networkClient.concede()) { $('concede-controls').hidden = true; } return; }
  if (canSelect()) post('concede');
};
document.addEventListener('keydown', event => {
  if (screen === 'viewer') {
    if (!event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.altKey && !document.querySelector('dialog[open]') &&
        !event.target?.closest?.('input, textarea, select')) viewer.handleKey(event);
    return;
  }
  if (event.defaultPrevented || event.repeat || event.isComposing || event.metaKey || event.ctrlKey || event.altKey ||
      event.target?.closest('input, textarea, select, [contenteditable="true"], #settings, dialog, .masthead, .history-section') ||
      document.querySelector('dialog[open]') || !canSelect()) return;
  if (event.key === 'Enter') {
    if (selectedCard === null || !legalCards(view, bidContract).includes(selectedCard)) return;
    event.preventDefault(); submitSelected(); return;
  }
  if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    const card = keyboard.adjacent(selectedCard, event.key === 'ArrowLeft' ? -1 : 1, view, bidContract, preferences.suitOrder);
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
$('worlds').onchange = async () => { if (!await newLocalMatch() && lastSave) $('worlds').value = botSelectionValue(lastSave); };
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
// Analysis of a finished deal on this device with the best bot (full search,
// 1024 worlds), in a second instance of the engine worker that plays no game:
// offline from the saved deal, online rebuilt from the public deal record.
let analysisWorker = null, analysisId = 0, analysisShown = null;
const analysisCache = new Map(), analysisPending = new Set(), analysisHandlers = new Map();
function analysisRequest(deal) {
  if (!deal) return null;
  if (networkClient) {
    const rebuilt = networkDealForAnalysis(networkClient.completed.get(deal.index));
    if (!rebuilt || !networkClient.session) return null;
    const conceded = networkClient.conceded.get(deal.index);
    return {key: `${networkClient.session.match_ref}:${deal.index}:${networkClient.session.seat}`, deal: rebuilt,
      seat: networkClient.session.seat, expectedTricks: rebuilt.expectedTricks, stopAfterPlayed: conceded ? conceded.after_tricks * 4 : 52};
  }
  const saved = lastSave?.completed?.[deal.index];
  if (!Array.isArray(saved?.cards) || !Array.isArray(saved.actions)) return null;
  return {key: `local:${saved.dealer}:${saved.cards.join(',')}`, seat: 0,
    deal: {cards: saved.cards, dealer: saved.dealer, score: saved.score, actions: saved.actions},
    stopAfterPlayed: saved.conceded ? saved.conceded.afterTricks * 4 : 52};
}
function showAnalysis(result) {
  const shown = analysisPresentation(result);
  $('analysis-status').textContent = ''; $('analysis-progress').hidden = true;
  $('analysis-summary').textContent = shown.summary;
  $('analysis-list').replaceChildren(...shown.items.map(item => {
    const entry = document.createElement('li'), grade = document.createElement('strong'), text = document.createElement('span');
    entry.dataset.grade = item.grade; grade.textContent = item.label; text.textContent = item.text; entry.append(grade, text); return entry;
  }));
}
function openAnalysis(deal) {
  const request = analysisRequest(deal);
  if (!request) return;
  $('analysis-title').textContent = `Jaon ${deal.index + 1} analyysi`;
  // Everyone's dealt hand, on request; available before the analysis finishes.
  $('analysis-hands').replaceChildren(...dealHands(request.deal, request.seat, preferences.suitOrder).map(hand => {
    const row = document.createElement('div'), name = document.createElement('strong'), cards = document.createElement('span');
    row.className = 'analysis-hand'; name.textContent = `${hand.label} · ${hand.highCardPoints} HCP`; cards.textContent = hand.text;
    row.append(name, cards); return row;
  }));
  showHands(false);
  analysisShown = request.key; openDialog('analysis');
  if (analysisCache.has(request.key)) { showAnalysis(analysisCache.get(request.key)); return; }
  $('analysis-list').replaceChildren(); $('analysis-summary').textContent = '';
  $('analysis-status').textContent = 'Analysoidaan botin täydellä haulla…';
  $('analysis-progress').hidden = false; $('analysis-progress').value = 0;
  if (analysisPending.has(request.key)) return;
  analysisPending.add(request.key);
  if (!analysisWorker) {
    analysisWorker = new Worker(new URL('./engine.4b565d59f821d534.mjs', import.meta.url), {type: 'module'});
    analysisWorker.onmessage = ({data}) => analysisHandlers.get(data?.id)?.(data);
  }
  const id = ++analysisId;
  analysisHandlers.set(id, data => {
    const visible = analysisShown === request.key && $('analysis').open;
    if (data.type === 'analysis-progress') {
      if (!visible) return;
      if (data.total) { $('analysis-progress').max = data.total; $('analysis-progress').value = data.done;
        $('analysis-status').textContent = `Analysoidaan botin täydellä haulla… ${Math.round(100 * data.done / data.total)} %`; }
      else if (data.message) $('analysis-status').textContent = data.message;
      return;
    }
    analysisHandlers.delete(id); analysisPending.delete(request.key);
    if (data.error) { if (visible) { $('analysis-status').textContent = data.error; $('analysis-progress').hidden = true; } }
    else { analysisCache.set(request.key, data.result); if (visible) showAnalysis(data.result); }
    releaseAnalysis();
  });
  analysisWorker.postMessage({type: 'analyse', id, deal: request.deal, seat: request.seat,
    stopAfterPlayed: request.stopAfterPlayed, expectedTricks: request.expectedTricks ?? null});
}
// The full-search engine is large: free it when nothing is waiting for it.
function releaseAnalysis() {
  if (!analysisPending.size && !$('analysis').open) { analysisWorker?.terminate(); analysisWorker = null; analysisHandlers.clear(); }
}
function showHands(visible) {
  $('analysis-hands').hidden = !visible; $('analysis-show-hands').setAttribute('aria-expanded', String(visible));
  $('analysis-show-hands').textContent = visible ? 'Piilota kädet' : 'Näytä kaikkien kädet';
}
$('analysis-show-hands').onclick = () => showHands($('analysis-hands').hidden);
$('close-analysis').onclick = () => { $('analysis').close(); analysisShown = null; releaseAnalysis(); };
$('analysis').addEventListener?.('close', () => { analysisShown = null; releaseAnalysis(); });
$('analyse-deal').onclick = () => openAnalysis(view?.completed?.at(-1));
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
    // A seat the host freed is not offered for resuming; join again instead.
    if (networkEnabled) try { savedNetwork = await loadNetwork(); if (savedNetwork?.released) savedNetwork = null; } catch (error) { $('network-status').textContent = error.message; }
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
  new URL('./engine.4b565d59f821d534.mjs', import.meta.url).pathname], onChange: state => {
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
  networkClient?.toggleBot(seat).catch(networkFailure), {
  onRename: seat => {
    const name = globalThis.prompt?.('Uusi nimimerkki', seat.display_name ?? '');
    if (name === null || name === undefined || name.trim() === seat.display_name) return;
    return networkClient?.rename(name).catch(networkFailure);
  },
  onMove: seats => networkClient?.swapSeats(...seats).catch(networkFailure),
  onRelease: seat => {
    if (globalThis.confirm && !globalThis.confirm(`Vapautetaanko paikka ${seat.display_name ?? ''}? Pelaaja voi liittyä uudelleen kutsulinkillä.`)) return;
    return networkClient?.releaseSeat(seat.seat).catch(networkFailure);
  }});
function networkFailure(error) {
  $('network-status').textContent = error.message; status(error.message, true); renderConnection();
}
function renderConnection() {
  const labels = {connecting: 'Yhdistetään…', synchronising: 'Päivitetään pelitilannetta…',
    connected: 'Yhteys kunnossa', pending: 'Varmistetaan siirtoasi…', reconnecting: 'Yhteys katkesi · yhdistetään uudelleen…',
    restarting: 'Palvelin päivittyy · peli jatkuu hetken kuluttua…',
    authentication: 'Kirjautuminen tarvitsee vahvistuksen · huoneesi säilyy',
    failed: 'Yhteys tarvitsee huomiota', superseded: 'Paikkasi on avoinna toisessa välilehdessä',
    released: 'Huoneen luoja vapautti paikkasi', left: 'Poistuit huoneesta', closed: 'Huone suljettiin'};
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
let standInKey = '';
function renderNetworkControls() {
  const client = networkClient, lobby = client?.session?.lobby, host = Boolean(client?.session?.host);
  const features = client?.features ?? new Set(), terminal = Boolean(view?.terminal);
  const active = Boolean(view) && !terminal && lobby?.lifecycle === 'playing';
  $('network-pause').hidden = !(host && features.has('pause') && active && !lobby.paused);
  $('network-unpause').hidden = !(host && features.has('pause') && active && lobby.paused);
  $('network-rematch').hidden = !(host && features.has('rematch') && terminal);
  for (const id of ['network-pause', 'network-unpause', 'network-rematch'])
    $(id).disabled = !client?.connected || client.authRequired;
  // Bot stand-ins for players who are away (and taking a seat back).
  const standIns = standInActions(lobby, {host, ownSeat: client?.session?.seat, features, active});
  const key = JSON.stringify(standIns);
  if (key !== standInKey) {
    standInKey = key;
    $('network-standins').replaceChildren(...standIns.map(action => {
      const button = document.createElement('button'); button.textContent = action.text;
      button.onclick = () => networkClient?.seatBot(action.seat, action.bot);  // repeats are harmless
      return button;
    }));
  }
  for (const button of $('network-standins').children) button.disabled = !client?.connected || client.authRequired;
  $('network-standins').hidden = !standIns.length;
  $('network-controls').hidden = ['network-pause', 'network-unpause', 'network-rematch'].every(id => $(id).hidden) && !standIns.length;
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
  const spectator = watching(), model = lobbyPresentation(lobby, viewSeat(), {watching: spectator}), playing = model.playing;
  if (!playing && view && networkClient) {
    // A rematch reopened the room: leave the finished table for the lobby.
    cancelReveal(); networkRevealDeal = null; view = null; selectedCard = null; keyboard.reset(); awaitingNetworkGame = true; render();
    if (!$('network-dialog').open) openDialog('network-dialog');
  }
  if (!playing || lobby.lifecycle === 'completed') refreshLeaderboard();
  const previous = previousMatchesText(lobby, networkClient?.session.seat ?? 0);
  $('network-previous').hidden = !previous; $('network-previous').textContent = previous ? `Aiemmat ottelut tässä huoneessa: ${previous}` : '';
  $('network-entry').hidden = true; $('network-lobby').hidden = false; $('network-local').hidden = false;
  $('network-leave').hidden = !networkClient?.session; $('network-leave').disabled = entryPending;
  $('network-title').textContent = 'Pelihuone';
  $('network-dialog').dataset.stage = 'lobby';
  $('network-room').textContent = lobby.match_number ? `Huone ${lobby.room_code} · ottelu ${lobby.match_number}` : `Huone ${lobby.room_code}`;
  const available = Boolean(networkClient?.connected && !networkClient.authRequired);
  const configuring = Boolean(networkClient?.configuring);
  lobbyView.render(model, {host: networkClient?.session.host, connected: available, configuring, features: networkClient?.features, lobby,
    watching: spectator});
  $('network-our-label').textContent = spectator ? teamName([0, 2]) : 'Sinä ja parisi';
  $('network-their-label').textContent = spectator ? teamName([1, 3]) : 'Vastustajat';
  // Who is watching (feature watch); a spectator chooses the viewpoint and may take a free seat.
  $('network-watchers').hidden = !lobby.watchers?.length;
  $('network-watchers').textContent = lobby.watchers?.length ? `Katsomassa: ${lobby.watchers.join(', ')}` : '';
  $('network-viewpoint-row').hidden = !spectator;
  if (spectator) {
    $('network-viewpoint').replaceChildren(...[0, 1, 2, 3].map(seat => {
      const option = document.createElement('option'); option.value = String(seat);
      option.textContent = seatDisplayName(lobby.seats.find(item => item.seat === seat)) || 'Vapaa paikka'; return option;
    }));
    $('network-viewpoint').value = String(viewSeat());
  }
  $('network-take-seat').hidden = !spectator || !takeableSeats(lobby).length;
  $('network-take-seat').disabled = !available;
  $('network-leave').textContent = spectator ? 'Lopeta katsominen' : 'Poistu huoneesta';
  if (lobbyRoom === lobby.room_code && lobbyConfiguration && lobbyConfiguration !== model.configuration && !playing) {
    $('network-changed').textContent = 'Paikkajako muuttui. Vahvistakaa valmius uudelleen.';
  }
  if (lobbyRoom !== lobby.room_code || model.ownReady || playing) $('network-changed').textContent = '';
  lobbyRoom = lobby.room_code; lobbyConfiguration = model.configuration;
  $('network-summary').textContent = `${model.humans} ${model.humans === 1 ? 'pelaaja' : 'pelaajaa'} · ${model.bots} ${model.bots === 1 ? 'botti' : 'bottia'}`;
  $('network-readiness').textContent = configuring ? 'Päivitetään huonetta…' : model.readyText;
  $('network-fill').hidden = $('network-open').hidden = !networkClient?.session.host || playing;
  $('network-fill').disabled = $('network-open').disabled = !available || configuring;
  $('network-ready').hidden = playing || spectator;
  $('network-ready').disabled = !available || configuring || model.open > 0 || model.ownReady;
  $('network-ready').textContent = model.ownReady ? 'Olet valmis' : 'Olen valmis';
  $('network-seat-guide').hidden = !networkClient?.session.host || playing || model.humans > 1 || spectator;
  $('network-invite').value = invitationURL(location.href, lobby.room_code);
  if (playing && screen === 'game') $('mode-label').textContent =
    (spectator ? `· Katsot huonetta ${lobby.room_code}` : `· Verkkopeli ${lobby.room_code}`) +
    (onlineHeidiNames[lobby.bot_profile] ? ' · ' + onlineHeidiNames[lobby.bot_profile] : '');
}
// The room-creation passcode field appears only when this host asks for it.
async function showPasscodeIfRequired() {
  if (!networkAddress) return;
  const probe = new NetworkSession();
  passcodeCheck ??= probe.createPasscodeRequired(networkAddress)
    .then(required => {
      passcodeRequired = required;
      for (const [id, profile] of onlineBotChoices) {
        const offered = probe.botOptions.find(bot => bot.profile === profile);
        $(id).disabled = $(id).hidden = !offered;
        $(id).textContent = typeof offered?.name === 'string' && offered.name ? offered.name : onlineHeidiNames[profile];
      }
      if ($('network-bot').value && !probe.botOptions.some(bot => bot.profile === $('network-bot').value))
        $('network-bot').value = '';
    })
    .catch(() => { passcodeCheck = null; });
  await passcodeCheck;
  if (!$('network-entry').hidden) renderRoomEntry();
}
// The free seats to choose from before joining; choosing one joins at once.
let chosenSeat;
function showSeatChoice(choices) {
  $('network-seat-options').replaceChildren(...choices.map(choice => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = choice.text;
    button.onclick = () => { chosenSeat = choice.seat; return startNetwork('join'); };
    return button;
  }));
  $('network-seat-choice').hidden = false;
  $('network-status').textContent = 'Valitse, kenen kanssa pelaat.';
}
async function startNetwork(command) {
  if (!networkEnabled || entryPending || navigationPending) return;
  if (!writeAccess || !networkAddress) { $('network-status').textContent = 'Verkkopeli ei ole vielä valmis. Yritä hetken kuluttua.'; return; }
  if (command === 'resume' && (!savedNetwork || savedNetwork.base !== networkAddress)) return;
  if (command === 'join' || command === 'watch') {
    try { $('network-code').value = roomCodeFromInput($('network-code').value, location.href); }
    catch (error) { $('network-status').textContent = error.message; $('network-code').focus?.(); return; }
    // Feature seat_choice: with more than one free seat, the player picks one first.
    if (command === 'join' && chosenSeat === undefined) {
      // Repeated submits wait here too: one preview, then at most one join.
      entryPending = true; renderRoomEntry();
      let preview = null;
      try { preview = await new NetworkSession().seatPreview(networkAddress, $('network-code').value).catch(() => null); }
      finally { entryPending = false; }
      const choices = preview ? seatChoices(preview.seats, preview.hostSeat) : [];
      if (choices.length > 1) { renderRoomEntry(); showSeatChoice(choices); return; }
      chosenSeat = choices.length === 1 ? choices[0].seat : null;
    }
  }
  // Another room this app still holds a seat in: leave it first (or resume it).
  const held = networkClient?.session ?? savedNetwork;
  if (command !== 'resume' && held && !held.released) {
    if (['join', 'watch'].includes(command) && held.room_code === $('network-code').value && held.base === networkAddress) {
      chosenSeat = undefined; $('network-seat-choice').hidden = true;
      return startNetwork('resume');
    }
    if (!await leaveRoom({switching: true})) return;
  }
  const joinSeat = chosenSeat ?? null; chosenSeat = undefined; $('network-seat-choice').hidden = true;
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
  networkClient = new NetworkSession({persist: async session => { await storeNetwork(session); savedNetwork = session.released ? null : structuredClone(session); },
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
    onChat: receiveChat,
    onStatus: (message, error) => {
      $('network-status').textContent = message; status(message, error);
      busy = !networkClient.connected || Boolean(networkClient.session?.pending);
      showNetworkLobby(networkClient.session?.lobby); render();
      if (error && networkClient.stopped) $('network-resume').hidden = !savedNetwork;
    },
    onView: next => {
      if (liveViewer) refreshLiveViewer();
      const old = view;
      if (old?.dealNumber !== next.dealNumber) {
        cancelReveal(); bidContract = legalCards(next, 0).length ? 0 : 1;
      }
      const reveal = old?.phase === 0 && next.phase !== 0 && old.dealNumber === next.dealNumber && next.bids.length && networkRevealDeal !== next.dealNumber;
      if (reveal) networkRevealDeal = next.dealNumber;
      next.revealing = Boolean(reveal || (revealFrame && old?.dealNumber === next.dealNumber));
      view = next; busy = !networkClient.connected || Boolean(networkClient.session.pending);
      if (awaitingNetworkGame) { awaitingNetworkGame = false; chatReturn = null; showGame(); $('network-dialog').close(); }
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
        await networkClient.create(networkAddress, nickname, ($('network-passcode').value ?? '').trim(), $('network-bot').value || null);
        $('network-passcode').value = '';
      } else if (command === 'watch') await networkClient.watch(networkAddress, $('network-code').value, nickname);
      else await networkClient.join(networkAddress, $('network-code').value, nickname, joinSeat);
    }
  } catch (error) {
    networkClient.close(); networkClient = null;
    if (connectionState.phase !== 'authentication') connectionState = {phase: 'failed'};
    renderConnection(); $('network-resume').hidden = !savedNetwork || savedNetwork.base !== networkAddress;
    $('network-leave').hidden = !savedNetwork || savedNetwork.released;
    $('network-status').textContent = error.message; $('network-entry').hidden = false; $('network-lobby').hidden = true;
    if (['room_passcode_required', 'invalid_room_passcode'].includes(error.code)) {
      passcodeRequired = true; roomIntent = 'create';
    }
    status(error.message, true); $('network-local').hidden = false;
  } finally {
    entryPending = false; renderRoomEntry(); renderHome();
  }
}
// Leave the room for good: in the lobby the seat is freed; during a match a
// bot plays it until someone joins it, and the next player hosts if the host
// leaves. With an older server, or one that cannot be reached, the room is
// only forgotten here. `switching`: before joining or creating another room.
// Returns whether the room was left.
async function leaveRoom({switching = false, ask = true} = {}) {
  const session = networkClient?.session ?? savedNetwork;
  if (!session || session.released) return true;
  const client = networkClient?.session ? networkClient : Object.assign(new NetworkSession({persist: storeNetwork}),
    {session: structuredClone(session)});
  const lobby = session.lobby, seats = lobby?.seats ?? [];
  const people = seats.filter(seat => seat.kind === 'human' || seat.covering).length;
  const playing = lobby?.lifecycle === 'playing';
  const known = client.features.size ? client.features.has('leave_seat') : true;
  const consequence = !known ? ' Paikkasi jää huoneeseen, kunnes huoneen luoja vapauttaa sen.' :
    people <= 1 ? ' Olet huoneen ainoa pelaaja, joten huone suljetaan.' :
    (playing ? ' Botti pelaa paikkasi, ja huonekoodin saanut voi liittyä siihen seuraavasta jaosta alkaen.' : ' Paikkasi vapautuu muille.') +
    (session.host ? ' Toinen pelaaja tulee huoneen luojaksi.' : '');
  const question = session.watching ? (switching ? `Lopetetaanko huoneen ${session.room_code} katsominen?` : null) :
    `${switching ? `Olet vielä huoneessa ${session.room_code}. Poistutaanko siitä?` : `Poistutaanko huoneesta ${session.room_code}?`}${consequence}`;
  if (ask && question && globalThis.confirm && !globalThis.confirm(question)) return false;
  entryPending = true; renderRoomEntry();
  try {
    try { await client.leave(); }
    catch (error) {
      if (globalThis.confirm && !globalThis.confirm(`Poistuminen ei onnistunut: ${error.message} Unohdetaanko huone ${session.room_code} tältä laitteelta?`)) return false;
      await client.leave({forget: true});
    }
  } finally { entryPending = false; }
  if (networkClient === client) {
    networkClient = null; busy = false;
    cancelReveal(); networkRevealDeal = null; view = null; selectedCard = null; keyboard.reset();
    lobbyConfiguration = null; lobbyRoom = null;
  }
  savedNetwork = null; connectionState = {phase: 'local'}; renderConnection();
  if (!switching) {
    showHome(); openRoomEntry();
    $('network-status').textContent = session.watching ? `Lopetit huoneen ${session.room_code} katsomisen.` :
      `Poistuit huoneesta ${session.room_code}. Liity toiseen huoneeseen tai luo uusi.`;
  }
  renderRoomEntry(); renderHome();
  return true;
}
// Watching (feature watch): the table is seen from a chosen seat.
function watching() { return Boolean(networkClient?.session?.watching); }
function viewSeat() { return watching() ? networkClient.session.viewpoint ?? 0 : networkClient?.session?.seat ?? 0; }
// Two players' names, e.g. for a team seen by a spectator.
function teamName(positions) {
  const seats = networkClient?.session?.lobby?.seats ?? [];
  return positions.map(position => seatDisplayName(seats.find(s => networkSeat(s.seat, viewSeat()) === position)) || 'Botti').join(' + ');
}
// Another seat's cards as text by suit, in the player's suit order (spectators).
function handText(cards) {
  return preferences.suitOrder.map(suit => {
    const ranks = cards.filter(card => Math.floor(card / 13) === suit).sort((a, b) => b - a).map(cardRank);
    return ranks.length ? `${suits[suit]} ${ranks.join(' ')}` : '';
  }).filter(Boolean).join('  ') || '–';
}
// Room chat (feature chat): one list for everyone in the room, in the lobby
// and during play. Messages are shown as text only and kept in memory.
function chatAvailable() {
  return Boolean(networkEnabled && networkClient?.session && networkClient.features.has('chat'));
}
function renderChatButtons() {
  const label = chatUnread ? `Viestit (${chatUnread})` : 'Viestit';
  for (const id of ['chat-toggle', 'network-chat']) {
    $(id).hidden = !chatAvailable(); $(id).textContent = label;
    $(id).setAttribute('aria-label', chatUnread ? `Viestit, ${chatUnread} lukematonta` : 'Viestit');
  }
  if (!chatAvailable()) {
    $('chat-toast').hidden = true;
    if ($('chat').open) { chatReturn = null; $('chat').close(); }
  }
}
// Your own message: from your seat, or as a spectator (no seat) under your name.
function ownChat(message) {
  const session = networkClient?.session;
  return session?.watching ? message.seat === null && message.display_name === session.display_name : message.seat === session?.seat;
}
function renderChat() {
  $('chat-list').replaceChildren(...chatMessages.map(message => {
    const item = document.createElement('li'), name = document.createElement('strong'),
      time = document.createElement('time'), text = document.createElement('span');
    item.className = 'chat-item'; item.dataset.own = String(ownChat(message));
    name.textContent = ownChat(message) ? `${message.display_name} (sinä)` : message.seat === null ? `${message.display_name} (katsoja)` : message.display_name;
    const sent = new Date(message.sent_at * 1000);
    time.textContent = sent.toLocaleTimeString('fi-FI', {hour: '2-digit', minute: '2-digit'});
    time.setAttribute('datetime', sent.toISOString());
    text.textContent = message.text; item.append(name, time, text); return item;
  }));
  $('chat-empty').hidden = chatMessages.length > 0;
  const list = $('chat-list'); list.scrollTop = list.scrollHeight;
  $('chat-send').disabled = !networkClient?.connected;
}
function receiveChat(messages, latest, refused) {
  chatMessages = messages;
  if (refused) $('chat-status').textContent = refused;
  if (latest && !ownChat(latest) && !$('chat').open) {
    chatUnread++;
    // A short notice, so a message is seen without opening the chat.
    $('chat-toast-open').textContent = `${latest.display_name}: ${latest.text}`;
    $('chat-toast').hidden = false;
    clearTimeout(chatToastTimer); chatToastTimer = setTimeout(() => { $('chat-toast').hidden = true; }, 6000);
  }
  if (!messages.length) chatUnread = 0;
  renderChat(); renderChatButtons();
}
function openChat() {
  if (!chatAvailable()) return;
  chatReturn = document.querySelector('dialog[open]') === $('network-dialog') ? 'network-dialog' : null;
  chatUnread = 0; $('chat-toast').hidden = true; $('chat-status').textContent = '';
  renderChat(); renderChatButtons(); openDialog('chat'); $('chat-input').focus?.();
}
async function returnToLocal() {
  const session = networkClient?.session ?? savedNetwork;
  networkClient?.close(); networkClient = null;
  connectionState = {phase: 'local'}; renderConnection();
  if (session) { session.active = false; await storeNetwork(session); savedNetwork = session.released ? null : session; }
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
$('home-online-other').onclick = () => {
  if (!entryReady || !networkEnabled || entryPending || navigationPending) return;
  openRoomEntry();
};
$('network-leave').onclick = () => leaveRoom().catch(networkFailure);
$('network-watch').onclick = () => startNetwork('watch');
$('network-viewpoint').onchange = () => networkClient?.setViewpoint(Number($('network-viewpoint').value));
// A spectator takes a free seat: stop watching, then join (choosing the seat if several are free).
$('network-take-seat').onclick = async () => {
  const code = networkClient?.session?.room_code;
  if (!code || !watching() || !await leaveRoom({switching: true, ask: false}).catch(error => { networkFailure(error); return false; })) return;
  showHome(); openRoomEntry(); $('network-code').value = code; await startNetwork('join');
};
$('home-retry').onclick = () => location.reload();
$('chat-toggle').onclick = openChat;
$('network-chat').onclick = openChat;
$('chat-toast-open').onclick = openChat;
$('close-chat').onclick = () => $('chat').close();
$('chat').onclose = () => {
  const back = chatReturn; chatReturn = null;
  if (back && networkClient?.session && !document.querySelector('dialog[open]')) openDialog(back);
};
$('chat-form').onsubmit = event => {
  event.preventDefault();
  if (networkClient?.sendChat($('chat-input').value)) { $('chat-input').value = ''; $('chat-status').textContent = ''; }
  else if ($('chat-input').value.trim()) $('chat-status').textContent = 'Viestiä ei voitu lähettää. Odota, että yhteys palautuu.';
};
$('network-reload').onclick = async () => {
  networkResolved = false; $('network-reload').hidden = true; $('network-status').textContent = 'Yhdistetään verkkopeliin…';
  networkAddress = await readNetworkConfiguration(); networkResolved = true; renderHome(); renderRoomEntry();
  $('network-status').textContent = networkAddress ? '' : 'Yhteyttä ei saatu. Tarkista verkkoyhteys ja yritä uudelleen.';
};
$('network-name').value = preferences.nickname;
$('turn-sound').checked = preferences.turnSound;
$('help-toggle').onclick = () => openDialog('help');
$('close-help').onclick = () => $('help').close();
$('share-results').checked = preferences.shareResults;
$('share-results').onchange = () => {
  preferences = savePreferences({...preferences, shareResults: Boolean($('share-results').checked)});
  if (preferences.shareResults) sendOfflineResults();
  else for (const {key} of outboxes) storeResults({pending: [], sent: resultsQueue(key).sent}, key);
};
// The suits in the hand from left to right (Settings › Kortit), saved on this
// device; online and offline alike. Ranks always rise left to right.
function renderSuitOrder() {
  const order = preferences.suitOrder;
  $('suit-order').replaceChildren(...order.map((suit, index) => {
    const item = document.createElement('li'); item.className = `suit-order-item suit-${suit}`;
    const symbol = document.createElement('span'); symbol.className = 'summary-suit'; symbol.setAttribute('aria-hidden', 'true'); symbol.innerHTML = suitSVG(suit);
    const name = document.createElement('span'); name.className = 'suit-order-name';
    name.textContent = suitNames[suit][0].toUpperCase() + suitNames[suit].slice(1);
    const move = (by, text, where) => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = text;
      button.disabled = index + by < 0 || index + by > 3;
      button.setAttribute('aria-label', `Siirrä ${suitNames[suit]} ${where}`);
      button.onclick = () => moveSuit(index, by); return button;
    };
    item.append(symbol, name, move(-1, '↑', 'vasemmalle'), move(1, '↓', 'oikealle')); return item;
  }));
  $('suit-order-reset').disabled = order.join() === '0,1,2,3';
}
function setSuitOrder(order) {
  preferences = savePreferences({...preferences, suitOrder: order});
  renderSuitOrder(); keyboard.reset();
  if (view) render();
}
function moveSuit(index, by) {
  const order = [...preferences.suitOrder];
  [order[index], order[index + by]] = [order[index + by], order[index]];
  setSuitOrder(order);
  // Keep the keyboard on the moved suit's same arrow while it can move further.
  const row = $('suit-order').children[index + by], button = row?.children[by < 0 ? 2 : 3];
  (button?.disabled ? row?.children[by < 0 ? 3 : 2] : button)?.focus?.();
}
$('suit-order-reset').onclick = () => setSuitOrder([0, 1, 2, 3]);
renderSuitOrder();
$('turn-sound').onchange = () => {
  preferences = savePreferences({...preferences, turnSound: Boolean($('turn-sound').checked)});
  if (preferences.turnSound) enableTurnAudio();
};
addEventListener('pointerdown', () => { if (preferences.turnSound && !turnAudio) enableTurnAudio(); }, {once: true});
$('network-name').onchange = () => { preferences = savePreferences({...preferences, nickname: $('network-name').value}); };
$('close-network').onclick = () => $('network-dialog').close();
// Opening the chat from the room dialog keeps waiting for the match to start.
$('network-dialog').onclose = () => { if (screen === 'home' && chatReturn !== 'network-dialog') awaitingNetworkGame = false; };
$('network-form').onsubmit = event => { event.preventDefault(); return startNetwork(roomIntent); };
$('network-resume').onclick = () => startNetwork('resume');
$('network-switch').onclick = async () => {
  if (entryPending) return;
  invitation = false; roomIntent = roomIntent === 'create' ? 'join' : 'create';
  chosenSeat = undefined; $('network-seat-choice').hidden = true;
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

// ------------------------------------------------------------ the viewer
// Round 16: replays of offline games and of replay or record files, one
// decision at a time with every hand shown. Timelines come from a separate
// worker instance (worker.mjs `timeline`), which never plays a game.
let viewerWorker = null, viewerRequestId = 0, viewerReturn = 'home', viewerMatches = [];
const viewerRequests = new Map();
function viewerTimeline(match) {
  ensureViewerWorker();
  const id = ++viewerRequestId;
  return new Promise((resolve, reject) => {
    viewerRequests.set(id, {resolve, reject});
    viewerWorker.postMessage({type: 'timeline', id, match});
  });
}
function ensureViewerWorker() {
  if (!viewerWorker) {
    viewerWorker = new Worker(new URL('./engine.4b565d59f821d534.mjs', import.meta.url), {type: 'module'});
    viewerWorker.onmessage = ({data}) => {
      if (data.type.startsWith('botmatch')) { botMatchMessage(data); return; }
      const pending = viewerRequests.get(data.id);
      if (!pending) return;
      if (data.type === 'timeline-progress') { $('viewer-status').textContent = data.message; return; }
      viewerRequests.delete(data.id);
      if (data.error) pending.reject(new Error(data.error)); else pending.resolve(data.timeline);
    };
  }
}
// A bot-only match on this device (worker.mjs `botmatch`): four bots play to
// 52 and the viewer follows live; the match and its timeline grow as it plays.
let botMatch = null;
function startBotMatch() {
  ensureViewerWorker(); liveViewer = null;
  const id = ++viewerRequestId;
  const teams = [$('home-viewer-team0').value, $('home-viewer-team1').value];
  const names = teams.map(value => $('home-viewer-team0').querySelector(`option[value="${value}"]`).textContent.replace(/ \(hidas\)$/, ''));
  botMatch = {id, match: {title: `Bottien ottelu: ${names[0]} – ${names[1]}`, source: 'bots',
    seatNames: viewerCompass.map((name, seat) => `${name} (${names[seat % 2]})`), humans: [], deals: []},
    data: {steps: [], deals: []}};
  showViewer();
  $('viewer-match-row').hidden = true;
  $('viewer-status').textContent = 'Bottien ottelu alkaa…';
  viewer.startLive(botMatch.match, botMatch.data);
  viewerWorker.postMessage({type: 'botmatch-start', id, teams, delay: viewerSpeeds[viewer.speed]});
}
function stopBotMatch() {
  if (botMatch) viewerWorker?.postMessage({type: 'botmatch-stop', id: botMatch.id});
  botMatch = null;
}
function botMatchMessage(data) {
  if (!botMatch || data.id !== botMatch.id) return;
  const {match, data: timeline} = botMatch;
  if (data.type === 'botmatch-progress') { $('viewer-status').textContent = data.message; return; }
  if (data.type === 'botmatch-error') { $('viewer-status').textContent = `Bottien ottelu keskeytyi: ${data.error}`; return; }
  if (data.type === 'botmatch-end') {
    $('viewer-status').textContent = `Ottelu päättyi ${data.score[0]}–${data.score[1]}. Voit katsoa sen uudelleen alusta.`; return;
  }
  const {step, info} = data;
  $('viewer-status').textContent = '';
  if (step.kind === 'start') match.deals.push({...data.deal, actions: []});
  else match.deals[step.deal].actions.push(step.action);
  timeline.steps.push(step); timeline.deals[step.deal] = info;
  viewer.update();
}
function closeViewer() {
  viewer.pause(); stopBotMatch(); liveViewer = null; $('viewer').hidden = true;
  if (viewerReturn === 'game') showGame(); else showHome();
}
const viewer = new ReplayViewer({el: $, timeline: viewerTimeline, suitOrder: () => preferences.suitOrder, onClose: closeViewer,
  onSpeed: delay => { if (botMatch) viewerWorker?.postMessage({type: 'botmatch-delay', id: botMatch.id, delay}); }});
function showViewer() {
  if (screen !== 'viewer') viewerReturn = screen;
  document.querySelector('dialog[open]')?.close();
  screen = 'viewer'; $('home').hidden = $('game').hidden = $('game-footer').hidden = true; $('viewer').hidden = false;
  renderViewerToggle();
  $('mode-label').textContent = '· Katsomo';
}
async function openViewer(match, options = {}) {
  stopBotMatch(); liveViewer = null; showViewer();
  try { await viewer.load(match, options); }
  catch (error) { $('viewer-status').textContent = `Toistoa ei voitu näyttää: ${error.message}`; }
}
function openViewerMatches(matches, options = {}) {
  viewerMatches = matches;
  $('viewer-match').replaceChildren(...matches.map((match, index) => {
    const option = document.createElement('option'); option.value = String(index); option.textContent = match.title; return option;
  }));
  $('viewer-match').value = '0';
  $('viewer-match-row').hidden = matches.length < 2;
  return openViewer(matches[0], options);
}
function openOwnViewer(deal = 0) {
  const match = viewerMatchFromSave(lastSave);
  if (match) openViewerMatches([match], {deal});
}
$('viewer-match').onchange = () => openViewer(viewerMatches[Number($('viewer-match').value)]);
$('home-viewer-own').onclick = () => openOwnViewer(0);
$('home-viewer-bots').onclick = () => startBotMatch();

// Going back in a live online game (round 16): the viewer opens over the game
// and follows it. Finished deals come in full from the server (feature
// deal_records) and replay on the engine with every hand; the deal in play is
// shown as this person sees it: a player only their own hand, a spectator
// every hand. The game goes on meanwhile; closing returns to it.
function renderViewerToggle() {
  $('viewer-toggle').hidden = !(screen === 'game' && networkClient?.latest);
}
function liveSeatNames(session) {
  const seats = session.lobby?.seats ?? [];
  return viewerCompass.map((compass, seat) => {
    const item = seats.find(entry => entry.seat === seat);
    const who = !item ? '' : item.covering ? `botti, ${item.covering}` : item.display_name || (item.kind === 'ai' ? 'botti' : '');
    return who ? `${compass} (${who})` : compass;
  });
}
function openLiveViewer() {
  const client = networkClient;
  if (!client?.latest) return;
  stopBotMatch();
  const session = client.session;
  liveViewer = {client, matchRef: client.latest.match_ref, records: null, recordTimeline: null, fetching: false,
    match: {title: `${session.watching ? 'Katsot huonetta' : 'Verkko-ottelu'} ${session.room_code}`, source: 'live',
      seatNames: liveSeatNames(session), humans: [], deals: []}, data: {steps: [], deals: []}};
  showViewer();
  $('viewer-match-row').hidden = true;
  $('viewer-status').textContent = '';
  viewer.startLive(liveViewer.match, liveViewer.data);
  viewer.viewpoint = session.watching ? session.viewpoint ?? 0 : session.seat;
  refreshLiveViewer();
}
function refreshLiveViewer() {
  const live = liveViewer, client = live?.client, latest = client?.latest;
  if (!latest || client !== networkClient) return;
  if (latest.match_ref !== live.matchRef) {  // a rematch: a new match from its first deal
    Object.assign(live, {matchRef: latest.match_ref, records: null, recordTimeline: null});
  }
  const completed = [...client.completed.values()].sort((a, b) => a.deal_number - b.deal_number);
  const known = live.recordTimeline?.deals.length ?? 0;
  if (known < completed.length && !live.fetching && client.features.has('deal_records')) {
    live.fetching = true;
    const matchRef = live.matchRef;
    client.dealRecords().then(async result => {
      if (liveViewer !== live || live.matchRef !== matchRef || result?.match_ref !== matchRef || !result.deals.length) return;
      const match = viewerMatchFromRecord({deals: result.deals});
      live.recordTimeline = await viewerTimeline(match);
      live.match.deals = match.deals;
    }).catch(error => { if (liveViewer === live) $('viewer-status').textContent = `Valmiita jakoja ei saatu: ${error.message}`; })
      .finally(() => { live.fetching = false; if (liveViewer === live && (live.recordTimeline?.deals.length ?? 0) > known) refreshLiveViewer(); });
  }
  const parts = completed.map((deal, d) => d < (live.recordTimeline?.deals.length ?? 0) ? timelinePart(live.recordTimeline, d) :
    liveDealSteps(liveDealFromResult(deal), d, {concededAfterTricks: client.conceded.get(deal.deal_number)?.after_tricks ?? null}));
  const observation = latest.observation;
  if (!completed.some(deal => deal.deal_ref === observation.deal_ref))
    parts.push(liveDealSteps(liveDealFromObservation(observation, latest.table?.hands ?? null), completed.length));
  const timeline = liveTimeline(parts);
  live.data.steps.splice(0, live.data.steps.length, ...timeline.steps);
  live.data.deals.splice(0, live.data.deals.length, ...timeline.deals);
  live.match.seatNames = liveSeatNames(client.session);
  viewer.update();
}
$('viewer-toggle').onclick = () => openLiveViewer();
$('home-viewer-file').onchange = async () => {
  const input = $('home-viewer-file'), file = input.files?.[0];
  if (!file) return;
  $('home-viewer-status').textContent = 'Luetaan tiedostoa…';
  try {
    const matches = viewerMatchesFromText(await viewerReadFile(file));
    $('home-viewer-status').textContent = '';
    await openViewerMatches(matches);
  } catch (error) { $('home-viewer-status').textContent = `Tiedostoa ei voitu avata: ${error.message}`; }
  finally { input.value = ''; }
};
$('viewer-export').onclick = () => {
  if (!viewer.match) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(viewerReplayFile([viewer.match]))], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'tuppi-toisto.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
