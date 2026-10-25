import {store, envelope, unwrap, storageHealth, readLocalRecord} from './storage.mjs';
import {loadNetwork, storeNetwork} from './storage.mjs';
import {NetworkSession, networkBase, networkSeat, networkDealForAnalysis} from './network.mjs';
import {OfflineSetup, packagedRuntimeIdentity} from './offline.mjs';
import {seatNames, suits, suitNames, suitSVG, cardRank, cardLabel, cardAction, legalCards, sortedHand,
  TableKeyboardSelection, bidRevealFrame, revealTiming} from './table.mjs';
import {HandView} from './hand.mjs';
import {seatPresentation, matchSummary, offlineResultReport, offlineMatchRecord, analysisPresentation, dealHands} from './presentation.mjs';
import {networkEnabled} from './capabilities.mjs';
import {LobbyView, lobbyPresentation, invitationURL, roomCodeFromInput, standInActions, seatDisplayName, seatChoices,
  takeableSeats, watcherSeatNames} from './lobby.mjs';
import {loadPreferences, savePreferences} from './preferences.mjs';
import {liveDealFromObservation, liveDealFromResult, liveDealSteps, liveTimeline, timelinePart} from './live.mjs';
import {ReplayViewer, viewerMatchFromRecord, viewerMatchFromSave, viewerMatchesFromText, viewerReadFile, viewerReplayFile, viewerCompass, viewerSpeeds} from './replay.mjs';

const $ = id => document.getElementById(id);
// Heidi 1.1 is Heidi 1.0's search on the faster engine; saves and replays from
// the earlier engine keep the name Heidi 1.0. Nelli 1.0 is the lite bot once
// called Heidi 0.5 (id heidi05, profile tuppi_ai_lite_c1h_v1): only the name changed.
// Heidi 1.2 and Nelli 1.1 are Heidi 1.1 and Nelli 1.0 with the new base network.
// New games offer only those two; the older ids stay selectable for their saves.
const heidiNames = {heidi05: 'Nelli 1.0', nelli11: 'Nelli 1.1', heidi10: 'Heidi 1.0', heidi11: 'Heidi 1.1', heidi12: 'Heidi 1.2'};
const onlineHeidiNames = {tuppi_ai_lite_c1h_v1: 'Nelli 1.0', tuppi_ai_lite_c1h_v2: 'Nelli 1.1',
  tuppi_ai_heidi10_pib8_v1: 'Heidi 1.1', tuppi_ai_heidi12_pib8_v1: 'Heidi 1.2'};
// A new game started from an older bot's selection plays that bot's current version.
const currentLocalBots = {heidi05: 'nelli11', heidi10: 'heidi12', heidi11: 'heidi12'};
const liteLocalBots = ['heidi05', 'nelli11'];  // W128; the Heidi search bots are W1024
// The online bots new rooms may choose, shown when the server lists them in bot_options.
const onlineBotChoices = [['network-nelli11-option', 'tuppi_ai_lite_c1h_v2'], ['network-heidi12-option', 'tuppi_ai_heidi12_pib8_v1']];
function botSelection(save = null) {
  let value = save ? (save.bot ?? String(save.worlds)) : $('worlds').value;
  if (!save) value = currentLocalBots[value] ?? value;  // a new game is always Heidi 1.2 or Nelli 1.1
  return value in heidiNames ? {bot: value, worlds: liteLocalBots.includes(value) ? 128 : 1024} :
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

function boot(save = null, {replace = false, engine = new URL('./worker.mjs', import.meta.url), identity = save?.identity ?? packagedRuntimeIdentity} = {}) {
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
    analysisWorker = new Worker(new URL('./worker.mjs', import.meta.url), {type: 'module'});
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
  new URL('./worker.mjs', import.meta.url).pathname], onChange: state => {
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
    viewerWorker = new Worker(new URL('./worker.mjs', import.meta.url), {type: 'module'});
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
