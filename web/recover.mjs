// The repair page's script, a file of its own so the page needs no inline
// script under the hosted Content-Security-Policy.
const button = document.getElementById('repair'), status = document.getElementById('status');
button.onclick = async () => {
  button.disabled = true; status.textContent = 'Päivitetään pelitiedostot…';
  try {
    if (!navigator.locks) throw new Error('Päivitä selain ja avaa korjaussivu localhost-osoitteesta.');
    await navigator.locks.request('tuppi-current-match', {mode: 'exclusive', ifAvailable: true}, async owned => {
      if (!owned) throw new Error('Peli on avoinna toisessa välilehdessä. Sulje se ja yritä uudelleen.');
      // IndexedDB and saved matches are deliberately not touched.
      const registration = await navigator.serviceWorker?.getRegistration('./');
      if (registration && new URL(registration.scope).href === new URL('./', location.href).href) await registration.unregister();
      const response = await fetch('./current-release.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('Pidä paikallinen palvelin käynnissä ja yritä uudelleen.');
      const manifest = await response.json();
      if (manifest.schema !== 'tuppi.browser.frontend.v1' || !/^launch\.[a-f0-9]{16}\.html$/.test(manifest.launch)) throw new Error('Pelitiedostojen versio on virheellinen.');
      status.textContent = 'Pelitiedostot ovat valmiit. Sulje tämä korjaussivu ja avaa Tuppi uudelleen.';
      document.getElementById('open').href = new URL(manifest.launch, location.href).href;
      document.getElementById('open').hidden = false;
    });
  } catch (error) { status.textContent = error.message; button.disabled = false; }
};
