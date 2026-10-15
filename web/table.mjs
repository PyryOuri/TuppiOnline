// Presentation and keyboard rules mirror the Swift table, without deciding legality.
export const suits = ['♥', '♦', '♣', '♠'];
const suitCodes = ['H', 'D', 'C', 'S'];
export const suitNames = ['hertta', 'ruutu', 'risti', 'pata'];
export const seatNames = ['Sinä', 'Vasen vastustaja', 'Pari', 'Oikea vastustaja'];
export const revealTiming = {step: 700, hold: 1800, fade: 400};
const suitShapes = [
  '<path d="M16 28S3 19.2 3 10.5C3 3.6 11.8 1.5 16 7.5c4.2-6 13-3.9 13 3C29 19.2 16 28 16 28Z"/>',
  '<path d="M16 2 29 16 16 30 3 16Z"/>',
  '<circle cx="16" cy="8" r="6"/><circle cx="8" cy="17" r="6.7"/><circle cx="24" cy="17" r="6.7"/><path d="M13 15h6c-1 5-1 9 3 14H10c4-5 4-9 3-14Z"/>',
  '<path d="M16 2C12 8 3 12 3 19a7 7 0 0 0 11.5 5.3L11 30h10l-3.5-5.7A7 7 0 0 0 29 19C29 12 20 8 16 2Z"/>',
];
export function suitSVG(suit) {
  return `<svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" focusable="false">${suitShapes[suit]}</svg>`;
}

export function cardRank(card) {
  const n = card % 13 + 2;
  return n < 11 ? String(n) : ['J', 'Q', 'K', 'A'][n - 11];
}
export function cardLabel(card) { return `${cardRank(card)}${suits[Math.floor(card / 13)]}`; }
export function cardAction(card, phase, contract = 0) {
  return card + (phase === 0 ? 52 + 52 * contract : [4, 5].includes(phase) ? 158 : 0);
}
export function legalCards(view, contract) {
  return view.hand.filter(card => view.legal.includes(cardAction(card, view.phase, contract)));
}
export function sortedHand(view) {
  const aceLow = view.soolaaja >= 0 || [4, 5, 6].includes(view.phase);
  const rank = card => aceLow && card % 13 === 12 ? -1 : card % 13;
  return view.hand.toSorted((a, b) => Math.floor(a / 13) - Math.floor(b / 13) || rank(a) - rank(b));
}
export function bidRevealFrame(bids, elapsed) {
  const last = revealTiming.step * Math.max(0, bids.length - 1);
  return {cards: bids.slice(0, Math.min(bids.length, 1 + Math.floor(elapsed / revealTiming.step))),
    contractPending: elapsed < last, fading: elapsed >= last + revealTiming.hold,
    finished: elapsed >= last + revealTiming.hold + revealTiming.fade};
}

export class TableKeyboardSelection {
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
