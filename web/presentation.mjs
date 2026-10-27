import {cardLabel, cardRank, seatNames, suits} from './table.mjs';

// Only consume the adapter's public view, never infer a hidden bid or hand.
export function seatPresentation(view, seat, nickname = seatNames[seat]) {
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

// A report without names of a finished offline match for the server's research
// results (no names, cards or hands): the bot level, the winner and final
// score from the player's team's view, deal and concession counts. Its id is
// a hash of the first deal's shuffled deck, so a match is reported once.
export async function offlineResultReport(save) {
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
export async function offlineMatchRecord(save) {
  const id = await offlineMatchId(save);
  if (!id || typeof save.identity !== 'string') return null;
  return {id, worlds: save.worlds, ...(save.bot ? {bot: save.bot} : {}), runtime: save.identity, deals: save.completed.map(deal => ({cards: [...deal.cards],
    dealer: deal.dealer, score: [...deal.score], actions: [...deal.actions],
    ...(deal.conceded ? {conceded: {afterTricks: deal.conceded.afterTricks}} : {})}))};
}

// End-of-match summary from the public completed-deal results only.
export function matchSummary(view) {
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
export const analysisGrades = {good: 'Hyvä', inaccuracy: 'Epätarkka', mistake: 'Virhe', unknown: 'Ei arviota'};
function analysisAction(id) {
  if (id >= 158) return `vaihtokortti ${cardLabel(id - 158)}`;
  if (id === 156) return 'ei soolia';
  if (id === 157) return 'sooli';
  if (id >= 52) return `${id >= 104 ? 'RAMI' : 'NOLO'} ${cardLabel(id % 52)}`;
  return cardLabel(id);
}
export function analysisPresentation(result) {
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
export function dealHands(deal, ownSeat = 0, suitOrder = [0, 1, 2, 3]) {
  return [0, 1, 2, 3].map(position => {
    const seat = (ownSeat + position) % 4, cards = deal.cards.slice(seat * 13, seat * 13 + 13);
    const bySuit = suitOrder.map(suit => ({suit: suits[suit],
      ranks: cards.filter(card => Math.floor(card / 13) === suit).sort((a, b) => b - a).map(cardRank)}));
    return {position, label: seatNames[position], suits: bySuit,
      highCardPoints: cards.reduce((sum, card) => sum + Math.max(0, card % 13 - 8), 0),
      text: bySuit.map(item => `${item.suit} ${item.ranks.join(' ') || '–'}`).join('  ')};
  });
}
