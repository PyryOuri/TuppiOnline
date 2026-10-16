// Keep the entry point independent of the game module graph so failed imports
// produce a visible recovery action instead of a permanent loading screen.
const element = id => document.getElementById(id);
let ready = false, watchdog;

function entryMessage(message, failed = false) {
  const home = element('home');
  if (!home || home.hidden) return;
  element('home-status').textContent = message;
  if (failed) {
    element('home-status').classList.add('error');
    element('home-recovery').hidden = false;
    element('home-retry').onclick = () => location.reload();
  }
}

export function startupFailure(error) {
  clearTimeout(watchdog);
  const message = error?.message || String(error);
  element('prompt').textContent = 'Pelin käynnistys epäonnistui.';
  element('table-status').textContent = 'Pelin käynnistys epäonnistui.';
  element('status').textContent = `Yritä uudelleen tai päivitä pelitiedostot. ${message}`;
  element('status').classList.add('error');
  element('retry').hidden = false;
  element('retry').onclick = () => location.reload();
  element('startup-recovery').hidden = false;
  entryMessage(`Peliä ei voitu avata. Yritä uudelleen tai päivitä pelitiedostot. ${message}`, true);
}

function progress(message) {
  clearTimeout(watchdog);
  if (message) element('status').textContent = message;
  if (!ready && message) entryMessage(message);
  if (!ready) watchdog = setTimeout(() => {
    element('prompt').textContent = 'Käynnistys kestää tavallista pidempään.';
    element('status').textContent = 'Voit yrittää uudelleen tai päivittää pelitiedostot. Tallennettua peliä ei poisteta.';
    element('retry').hidden = false; element('retry').onclick = () => location.reload();
    element('startup-recovery').hidden = false;
    entryMessage('Avaaminen kestää tavallista pidempään. Voit yrittää uudelleen; tallennettu peli säilyy.', true);
  }, 30000);
}
addEventListener('tuppi-startup', ({detail}) => {
  if (detail?.begin) ready = false;
  if (detail?.ready) {
    ready = true; clearTimeout(watchdog); element('startup-recovery').hidden = true;
    if (element('home-recovery')) element('home-recovery').hidden = true;
  } else if (detail?.error) startupFailure(new Error(detail.error));
  else progress(detail?.message);
});
addEventListener('error', event => { if (!ready) startupFailure(event.error ?? new Error(event.message)); });
addEventListener('unhandledrejection', event => { if (!ready) startupFailure(event.reason); });

export async function startClient({fetchManifest = () => fetch('./frontend.json', {cache: 'no-store'}),
  importClient = url => import(url), base = import.meta.url} = {}) {
  progress('Ladataan pelin käyttöliittymä…');
  try {
    const response = await fetchManifest();
    if (!response.ok) throw new Error('Pelitiedostoja ei voitu ladata.');
    const manifest = await response.json();
    if (manifest.schema !== 'tuppi.browser.frontend.v1' || !/^client\.[a-f0-9]{16}\.mjs$/.test(manifest.client))
      throw new Error('Pelitiedostojen versio on virheellinen.');
    await importClient(new URL(manifest.client, base).href);
  } catch (error) { startupFailure(error); }
}
await startClient();
