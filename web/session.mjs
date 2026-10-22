// The deal's result is already 0-0: in the rising score a deal won by the team
// behind resets the match, and that is certain once, in NOLO (contract 0), the
// team ahead has 7 tricks or, in RAMI (1), the team behind has 7. Normal trick
// play (phase 1) only. The server's rule is match_runner.concede_available;
// network.mjs keeps the same rule for online views (separate bundles).
export function decidedForZero({phase, contract, tricks0, tricks1, score0, score1}) {
  if (phase !== 1 || (!score0 && !score1)) return false;
  const tricks = [tricks0, tricks1], ahead = score0 > 0 ? 0 : 1;
  return contract === 1 ? tricks[1 - ahead] >= 7 : tricks[ahead] >= 7;
}

/* LocalSession is independent of DOM, workers and persistence adapters. */
export class LocalSession {
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
      ...(this.runtime.bot === 'heidi10' ? {inference: this.runtime.inferenceCandidates ?? 4} : {}),
      cards: [...this.cards], dealer: this.dealer, score: [...this.score], actions: [...this.actions],
      context: this.runtime.context(), humanBid: this.humanBid, completed: structuredClone(this.completed),
      archived: this.archived};
  }

  restore(save) {
    if (save?.schema !== 'tuppi.browser.save.v1' || save.identity !== this.runtime.identity ||
        save.worlds !== this.runtime.worlds || (save.bot ?? 'legacy') !== (this.runtime.bot ?? 'legacy') ||
        (save.bot === 'heidi10' && (save.inference ?? 4) !== (this.runtime.inferenceCandidates ?? 4)))
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
export function analyseDeal(runtime, deal, seat, {context = null, stopAfterPlayed = 52, expectedTricks = null, progress = () => {}} = {}) {
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

export function shuffledDeck() {
  const cards = Array.from({length: 52}, (_, i) => i), buffer = new Uint32Array(1);
  for (let i = 51; i > 0; i--) {
    const limit = Math.floor(0x100000000 / (i + 1)) * (i + 1);
    do { crypto.getRandomValues(buffer); } while (buffer[0] >= limit);
    const j = buffer[0] % (i + 1);
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }
  return cards;
}
