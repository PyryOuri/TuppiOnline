import {networkSeat} from './network.mjs';
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

export function lobbyPresentation(lobby, ownSeat = 0) {
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

export function invitationURL(page, room) {
  if (!/^[A-Z0-9]{6}$/.test(room)) throw new Error('Virheellinen huonekoodi.');
  const link = new URL(page); link.search = ''; link.hash = '';
  link.searchParams.set('play', 'online'); link.searchParams.set('room', room);
  return link.href;
}

export class LobbyView {
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
