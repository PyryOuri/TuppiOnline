import {hostSeat, networkSeat} from './network.mjs';
import {seatNames} from './table.mjs';

// Pasted links supply only a room code. Requests still use this app's configured
// server; a link to another site must be opened there rather than joined here.
export function roomCodeFromInput(value, base) {
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
export const watcherSeatNames = ['Alhaalla', 'Vasemmalla', 'Ylhäällä', 'Oikealla'];
export function lobbyPresentation(lobby, ownSeat = 0, {watching = false} = {}) {
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

export function invitationURL(page, room) {
  if (!/^[A-Z0-9]{6}$/.test(room)) throw new Error('Virheellinen huonekoodi.');
  const link = new URL(page); link.search = ''; link.hash = '';
  link.searchParams.set('play', 'online'); link.searchParams.set('room', room);
  return link.href;
}

// Per seat: the host adds/removes bots on open seats and frees other
// players' seats; each player renames their own seat. Only before the match,
// and only what the server lists in its features.
export function seatAction(seat, {host, playing, features = new Set()}) {
  if (playing) return null;
  if (seat.kind === 'human' && seat.position === 0) return features.has('rename') ? 'rename' : null;
  if (seat.kind === 'human') return host && features.has('release_seat') ? 'release' : null;
  return host ? 'toggle' : null;
}

// During a match (feature seat_bot): the host may let a bot play for a player
// who is not connected, and give a covered seat back; a covered player may
// take their own seat back. Never a bot for the host's seat, and not back
// while a newcomer waits for the next deal (feature leave_seat).
export function standInActions(lobby, {host, ownSeat, features = new Set(), active}) {
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
export function seatChoices(seats, host = 0) {
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
export function moveAction(seat, {host, playing, features = new Set(), lobby}) {
  const own = hostSeat(lobby), partnerSeat = (own + 2) % 4;
  if (!host || playing || !features.has('seat_swap') || (seat.seat - own + 4) % 2 !== 1) return null;
  const partner = lobby?.seats?.find(item => item.seat === partnerSeat);
  if (seat.kind === 'open' && (!partner || partner.kind === 'open')) return null;
  return {seats: [seat.seat, partnerSeat], text: seat.kind === 'open' ? 'Siirrä parisi tähän' : 'Siirrä pariksi'};
}

// Seats a spectator could take (feature watch): a free seat before the match,
// or one a player left during it (the newcomer plays from the next deal).
export function takeableSeats(lobby) {
  const playing = ['playing', 'completed'].includes(lobby?.lifecycle);
  if (lobby?.lifecycle === 'completed') return [];
  return (lobby?.seats ?? []).filter(seat => playing ? seat.vacant : seat.kind === 'open').map(seat => seat.seat);
}
// A seat's name at the table: a stand-in bot says whom it plays for.
export function seatDisplayName(seat) {
  return seat?.covering ? `Botti (${seat.covering})` : seat?.display_name;
}

export class LobbyView {
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
