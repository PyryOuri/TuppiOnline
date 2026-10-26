"""Small same-origin owner page. The admin key stays in the password field.

No browser bundle rebuild is needed; these assets are served by HostedBoundary.
"""

PAGE = """<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Heidin ylläpito · Tuppi</title><link rel="stylesheet" href="/v1/admin/heidi.css">
<script type="module" src="/v1/admin/heidi.mjs"></script></head>
<body><main><p><a href="/">← Tuppiin</a></p><h1>Heidin ylläpito</h1>
<p>Heidi vapautuu automaattisesti, kun pöydässä ei ole ollut pelaajien toimintaa 15 minuuttiin.
Voit myös sulkea varauksen käsin. Sulkeminen katkaisee pöydän pelaajien ja katsojien yhteydet.
Ottelun tallenne säilyy palvelimen arkistossa, mutta peliä ei voi jatkaa huonekoodilla.</p>
<form id="login"><label for="key">Ylläpitoavain</label>
<input id="key" type="password" autocomplete="off" required minlength="16" maxlength="256">
<button id="refresh" type="submit">Näytä Heidin varaus</button></form>
<p id="status" role="status" aria-live="polite"></p><section id="tables" aria-label="Heidin varaukset"></section>
</main></body></html>"""

SCRIPT = """const key = document.getElementById('key');
const status = document.getElementById('status');
const tables = document.getElementById('tables');
const refresh = document.getElementById('refresh');
let busy = false;
async function request(path, payload) {
  const response = await fetch('/v1/admin/heidi/' + path, {
    method: payload ? 'POST' : 'GET', cache: 'no-store', credentials: 'omit',
    headers: {Authorization: 'Bearer ' + key.value, ...(payload ? {'Content-Type': 'application/json'} : {})},
    ...(payload ? {body: JSON.stringify(payload)} : {}),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(response.status === 403 ? 'Ylläpitoavain ei kelpaa tai yrityksiä on liikaa.' :
    body.error === 'heidi_table_not_active' ? 'Tämä varaus ei ole enää voimassa. Päivitä tilanne.' :
    body.error === 'storage_unavailable' ? 'Tallennus ei toimi. Heidiä ei vapautettu; tarkista palvelin.' : 'Palvelupyyntö epäonnistui.');
  return body;
}
async function showTables() {
  const body = await request('status');
  tables.replaceChildren();
  status.textContent = body.tables.length ? 'Heidi on varattu.' : 'Heidi on vapaa.';
  for (const table of body.tables) {
    const section = document.createElement('article');
    const title = document.createElement('h2'); title.textContent = 'Huone ' + table.room_code;
    const detail = document.createElement('p');
    detail.textContent = `${table.connected_players} pelaajaa yhteydessä · ${Math.floor(table.idle_seconds / 60)} min ilman pelaajien toimintaa${table.paused ? ' · tauolla' : ''}`;
    const release = document.createElement('button'); release.textContent = 'Sulje pöytä ja vapauta Heidi';
    release.addEventListener('click', async () => {
      if (busy || !window.confirm(`Suljetaanko huone ${table.room_code} ja vapautetaan Heidi? Pelaajien ja katsojien yhteydet katkeavat, eikä peliä voi jatkaa huonekoodilla.`)) return;
      busy = true; release.disabled = true; refresh.disabled = true;
      status.textContent = 'Vapautetaan Heidiä. Odotetaan mahdollisen bottisiirron valmistumista…';
      try { await request('release', {room_code: table.room_code}); await showTables(); }
      catch (error) { status.textContent = error.message; }
      finally { busy = false; release.disabled = false; refresh.disabled = false; }
    });
    section.append(title, detail, release); tables.append(section);
  }
}
document.getElementById('login').addEventListener('submit', async event => {
  event.preventDefault(); if (busy) return;
  busy = true; refresh.disabled = true; tables.replaceChildren(); status.textContent = 'Haetaan varausta…';
  try { await showTables(); } catch (error) { status.textContent = error.message; }
  finally { busy = false; refresh.disabled = false; }
});
window.addEventListener('pagehide', () => { key.value = ''; tables.replaceChildren(); });
"""

STYLE = """html {color-scheme: light dark; font: 17px/1.55 system-ui, sans-serif}
body {margin: 0; padding: 1.5rem} main {max-width: 42rem; margin: auto}
form {display: grid; gap: .6rem; margin: 2rem 0} input, button {font: inherit; padding: .7rem}
button {cursor: pointer} article {border: 1px solid #888; border-radius: .5rem; padding: 1rem}
#status {min-height: 2rem} a {color: inherit}
"""

ASSETS = {
    "/v1/admin/heidi": ("text/html; charset=utf-8", PAGE),
    "/v1/admin/heidi.mjs": ("text/javascript; charset=utf-8", SCRIPT),
    "/v1/admin/heidi.css": ("text/css; charset=utf-8", STYLE),
}
