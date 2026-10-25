// Transport and presentation of authorised seat observations. No local engine.
export const networkProtocol = 'tuppi.network.v1';
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
export function networkBase(value) {
  const url = new URL(value);
  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) ||
      url.username || url.password || url.search || url.hash || url.pathname !== '/')
    throw new Error('Verkkopalvelun osoitteen on oltava HTTPS-alkuperä.');
  return url.origin;
}
export function networkCard(code) {
  const match = /^(2|3|4|5|6|7|8|9|10|J|Q|K|A)([HDCS])$/.exec(code);
  if (!match) throw new Error('Palvelin lähetti tuntemattoman kortin.');
  return 'HDCS'.indexOf(match[2]) * 13 + ['2','3','4','5','6','7','8','9','10','J','Q','K','A'].indexOf(match[1]);
}
export function networkCardCode(card) {
  if (!Number.isInteger(card) || card < 0 || card > 51) throw new Error('Tuntematon kortti.');
  return ['2','3','4','5','6','7','8','9','10','J','Q','K','A'][card % 13] + 'HDCS'[Math.floor(card / 13)];
}
export function networkActionID(action) {
  if (action.type === 'show') return 52 + (action.declared_contract === 'RAMI' ? 52 : 0) + networkCard(action.shown_card);
  if (action.type === 'play') return networkCard(action.card);
  if (action.type === 'sooli_exchange') return 158 + networkCard(action.card);
  if (action.type === 'sooli_decision') return action.play_sooli ? 157 : 156;
  throw new Error('Palvelin lähetti tuntemattoman siirron.');
}
export function networkSeat(seat, observingSeat) {
  return seat === null || seat === undefined || seat < 0 ? -1 : (seat - observingSeat + 4) % 4;
}
// The deal's result is already 0-0 (same rule as session.mjs decidedForZero
// and the server's concede_available): in NOLO the team ahead has 7 tricks,
// in RAMI the team behind has 7. Own-team-first scores and tricks.
export function networkDecided(view) {
  if (view.phase !== 1 || (!view.score0 && !view.score1)) return false;
  const tricks = [view.tricks0, view.tricks1], ahead = view.score0 > 0 ? 0 : 1;
  return view.contract === 1 ? tricks[1 - ahead] >= 7 : tricks[ahead] >= 7;
}
// A finished online deal for local analysis. Once it is over every card has
// been played, so each seat's hand is the cards it played; bids and sooli
// decisions are public. A deal played as sooli is not supported (the sitting-out
// partner's hand is never shown), nor is anything that does not add up.
export function networkDealForAnalysis(deal) {
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
export function spectatorPayload(payload, viewpoint = 0) {
  const hands = payload.table?.hands;
  if (!Array.isArray(hands) || hands.length !== 4) throw new Error('Palvelin lähetti puutteellisen katsojanäkymän.');
  return {...payload, bidding: payload.bidding && {...payload.bidding, options: [], own_bid: null},
    observation: {...payload.observation, observing_seat: viewpoint, own_hand: hands[viewpoint], legal_actions: [],
      team: viewpoint % 2, partner_seat: (viewpoint + 2) % 4},
    tableHands: [0, 1, 2, 3].map(position => hands[(viewpoint + position) % 4].map(networkCard))};
}
export function networkView(payload, completed = [], summary = null, conceded = new Map()) {
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
export function hostSeat(lobby) {
  return Number.isInteger(lobby?.host_seat) ? lobby.host_seat : 0;
}

export class NetworkSession {
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
