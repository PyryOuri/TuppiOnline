import {cardLabel, seatNames} from './table.mjs';

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

// An anonymous report of a finished offline match for the server's research
// results (no names, cards or hands): the bot level, the winner and final
// score from the player's team's view, deal and concession counts. Its id is
// a hash of the first deal's shuffled deck, so a match is reported once.
export async function offlineResultReport(save) {
  const deals = save?.completed ?? [], last = deals.at(-1)?.result;
  if (!last?.terminal || ![128, 1024].includes(save.worlds) || !deals[0]?.cards) return null;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([deals[0].cards, deals[0].dealer])));
  const id = [...new Uint8Array(digest)].slice(0, 16).map(byte => byte.toString(16).padStart(2, '0')).join('');
  return {id, worlds: save.worlds, winner_team: last.score0 >= 52 ? 0 : 1, final_score: [last.score0, last.score1],
    deals: deals.length, conceded: deals.filter(deal => deal.conceded).length};
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
