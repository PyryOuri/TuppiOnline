// Transport and presentation of authorised seat observations. No local engine.
export const networkProtocol = 'tuppi.network.v1';
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
  invalid_display_name:'Kirjoita nimimerkki (1–40 merkkiä).',
  seat_not_releasable:'Tätä paikkaa ei voi vapauttaa.'};
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
    prompt: legal.length ? null : phase === 0 ? 'Tarjous lukittu. Odotetaan muita pelaajia…' :
      observation.current_actor === null ? 'Ottelu päättyi.' : 'Odotetaan siirtoa…'};
}

export class NetworkSession {
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
    this.close(); this.session = structuredClone(session); this.completed.clear(); this.conceded.clear(); this.latest = null;
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
      if (event.code === 4002) {
        // The host freed this seat; its credential no longer works.
        this.stopped = true; this.session.active = false; this.session.released = true;
        this.persist(this.session).catch(() => {});
        this.connection('released'); this.onStatus('Huoneen luoja vapautti paikkasi. Voit liittyä huoneeseen uudelleen kutsulinkillä.', true); return;
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
        this.latest = null; this.completed.clear(); this.conceded.clear(); this.placed = null;
        Object.assign(this.session, {cursor: -1, match_ref: null, pending: null, summaryDeal: null, summary: null});
      }
      this.session.lobby = payload; await this.persist(this.session); this.onLobby(payload);
      this.emitView();
      if (!['playing','completed'].includes(payload.lifecycle)) { this.connected = true; this.connection('connected'); this.onStatus('', false); }
    } else if (['match_update','reconnect_result'].includes(message.message_type)) {
      if (payload.observation.observing_seat !== this.session.seat) throw new Error('Palvelin lähetti väärän paikan havainnon.');
      for (const deal of payload.completed_deals ?? []) this.completed.set(deal.deal_number, deal);
      for (const item of payload.conceded_deals ?? []) this.conceded.set(item.deal_number, item);
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
      this.session.summaryDeal === this.latest.observation.deal_ref ? this.session.summary : null, this.conceded);
    const paused = Boolean(this.session.lobby?.paused) && !view.terminal;
    if (!this.connected || this.stopped || this.session.pending || paused) view.waitingHuman = false;
    view.paused = paused;
    view.concedeAvailable = this.features.has('concede') && this.connected && !this.stopped && !this.session.pending &&
      !paused && networkDecided(view);
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
  // Any player: finish a deal whose result is already 0-0.
  concede() {
    if (!this.features.has('concede') || !this.connected || this.stopped || this.session.pending || !this.latest) return false;
    return this.send('concede', {});
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
