const RELEASE = "eddc24b82bb34506d9bcaf5631c9517d089a462651e8cec407cf26ad17eb3966";
const FILES = [{"path": "index.html", "sha256": "3cf713489c37afb75029536153e73e34e057f7e661a5455f073fbde46856d08e", "bytes": 15683, "shared": false, "source_path": "offline-shell.3cf713489c37afb7.txt"}, {"path": "app.mjs", "sha256": "858f04a7dcb0c42db92b8749bd435055e787a5bdf8d1857cf188ccf61ca7467e", "bytes": 55388, "shared": false}, {"path": "styles.css", "sha256": "22fd6f6d9bf5063e313a2139898689e261685c2f99e4bfda3dd5c2448b038a9b", "bytes": 27381, "shared": false}, {"path": "table.mjs", "sha256": "79e583d7a659ff002f0125680583c538a1ab5def8ed9a9836d28171b4912ee44", "bytes": 4059, "shared": false}, {"path": "runtime.mjs", "sha256": "4dc23e1c27228258c5884ab18afc41523d3d5f2ed3e395e4050d903f3b351ccc", "bytes": 8316, "shared": false}, {"path": "session.mjs", "sha256": "e28510af4b0916aa70b2ea6fd1ad6d4b61ef13a52b038c0764dd379eaa73635f", "bytes": 6948, "shared": false}, {"path": "worker.mjs", "sha256": "95f78f20a7859ea3f59954975468bd910798fe11d178b963c857d7b28c5a370e", "bytes": 2646, "shared": false}, {"path": "storage.mjs", "sha256": "298c8bc44d0c61a980196ee8df8e2bc63fcc1171c0f2f5f30e3e481bc3ccae85", "bytes": 4525, "shared": false}, {"path": "offline.mjs", "sha256": "c58d43dc43ad22089cae7018d03f4e15fc643173120e62c3a570ede46d6fe53f", "bytes": 6052, "shared": false}, {"path": "network.mjs", "sha256": "0c05309fa0bbbd3598c9326ca8bd09461d610327ad57b17996710b61a7c56f44", "bytes": 22836, "shared": false}, {"path": "hand.mjs", "sha256": "bafaf9ec4582e7d786f3b011e5efc3fec276295180eefe7f4c6d046aed18b8e3", "bytes": 2718, "shared": false}, {"path": "presentation.mjs", "sha256": "ec17a57781c7c2f3c62a4cf780be039759b4544edc6fdd6cc05ed9dd9eaa13b0", "bytes": 1918, "shared": false}, {"path": "capabilities.mjs", "sha256": "e19671e943b5bbb1e8bc299e746b9654ddd8c3bf6202809a59a677b5e72b26c0", "bytes": 118, "shared": false}, {"path": "lobby.mjs", "sha256": "ecaa5462de862ec99c2ddd6e51f31ca3cc94382917410d602b652e7b3cd650b3", "bytes": 3595, "shared": false}, {"path": "preferences.mjs", "sha256": "b6ea1a34e984ca958d792fd88110af81f19ad73d845a47485232f5286cc95b31", "bytes": 961, "shared": false}, {"path": "manifest.webmanifest", "sha256": "e19b09834a05463e6dbadac914c34fb7e27139789bbd1b2e1571f93d37f705a3", "bytes": 415, "shared": false}, {"path": "icon.svg", "sha256": "5ddfb27fe2fc146ba4a3fa984f3fd94158089a524c2095e445e258a658b6480c", "bytes": 346, "shared": false}, {"path": "icon-180.png", "sha256": "f12122f5933634846592afaa7b6ed8e89cfbebde39526910ab63844312e5e9a9", "bytes": 4495, "shared": false}, {"path": "icon-192.png", "sha256": "3ba0356df63c9d51b30ef4ed32d6878bb4f7233da7356094ab31a21016108dfb", "bytes": 4684, "shared": false}, {"path": "icon-512.png", "sha256": "cdb05c6e2745c938ab8a84ad0bacd3bd33488c017d0889f9466bcace453e807f", "bytes": 17323, "shared": false}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/tuppi.mjs", "sha256": "1fdc0bb286a965c9b4daf8d54f80b1100b95db549affa52be96289eb170471c9", "bytes": 8153, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/tuppi.wasm", "sha256": "9d04dfd0e27a6af20b17594d1669422d4f5393515cf6e04c14e0c39389ced616", "bytes": 87227, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/models.json", "sha256": "8cb282aa3be3c4ebc0c4bcfcaaeceda93a9c225e3e51488148df181771ae2124", "bytes": 1673, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/build.json", "sha256": "c31f8c1e857f438b5f95e0b984ca9ed07ff42043016703a12bbe8b5810ffe854", "bytes": 4140, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/vrpo1_actor_0504.f32", "sha256": "beb1f890947748a3df254dc200b9433547babc9fe40388fe76ba82e0f01abbda", "bytes": 3218032, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/vrpo3_final.f32", "sha256": "0e4bba619908ad3fa92a75fb118470b436ffa571caaca5e8f6aab497be633b47", "bytes": 12743280, "shared": true}, {"path": "runtime/95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d/equity.f64", "sha256": "8e01246f723210a8e0364a63748de460b94b6e5a513e8e747dc91744f1bc3f0b", "bytes": 400, "shared": true}, {"path": "bootstrap.mjs", "sha256": "84af2e289162bc0aa22a4807161be5241c2324880d4121e2ed74d95377762564", "bytes": 2503, "shared": false}, {"path": "recover.html", "sha256": "482b90f06d06e4acf23c4475ee2ae46c55ac7b0646959680afa85e899d15617c", "bytes": 2610, "shared": false, "source_path": "offline-shell.482b90f06d06e4ac.txt"}, {"path": "frontend.json", "sha256": "1e8de36ae2720f4da8d093c2b0eadc14f53187558e5ae89edb6eb71ae37fca1e", "bytes": 690, "shared": false}, {"path": "client.a73b6aaa5183d525.mjs", "sha256": "a73b6aaa5183d5256d70b81375d138770820423149145284d9cddaa8f3ba1c0f", "bytes": 101340, "shared": false}, {"path": "engine.ba679a5bb2e66563.mjs", "sha256": "ba679a5bb2e66563e9be5e290e891df55fa2e4e321281da7cafc44cfbc0e7c56", "bytes": 17979, "shared": false}, {"path": "launch.be0da04422e74637.html", "sha256": "a0edf28ca0b0607aeee871e32dc853a0d36b2a7332fffdcd04cd224997a0b18e", "bytes": 15717, "shared": false, "source_path": "offline-shell.a0edf28ca0b0607a.txt"}, {"path": "styles.22fd6f6d9bf5063e.css", "sha256": "22fd6f6d9bf5063e313a2139898689e261685c2f99e4bfda3dd5c2448b038a9b", "bytes": 27381, "shared": false}, {"path": "bootstrap.e676380057cbc482.mjs", "sha256": "e676380057cbc482218935b1fef72a98101292035f2ce5a801eddaad0d5fa8f0", "bytes": 2520, "shared": false}, {"path": "frontend.be0da04422e74637.json", "sha256": "1e8de36ae2720f4da8d093c2b0eadc14f53187558e5ae89edb6eb71ae37fca1e", "bytes": 690, "shared": false}, {"path": "./", "sha256": "3cf713489c37afb75029536153e73e34e057f7e661a5455f073fbde46856d08e", "bytes": 15683, "shared": false, "source_path": "offline-shell.3cf713489c37afb7.txt"}];
const FRONTEND = {"schema": "tuppi.browser.frontend.v1", "client": "client.a73b6aaa5183d525.mjs", "client_sha256": "a73b6aaa5183d5256d70b81375d138770820423149145284d9cddaa8f3ba1c0f", "engine": "engine.ba679a5bb2e66563.mjs", "engine_sha256": "ba679a5bb2e66563e9be5e290e891df55fa2e4e321281da7cafc44cfbc0e7c56", "runtime_identity": "95497f1ebdf0979b8463f3822cf3db85ad8495ed85ae1fe3e5b3b09962871b5d", "worker_protocol": "tuppi.local.worker.v1", "capabilities": {"offline": true, "network": true}, "launch": "launch.be0da04422e74637.html", "styles": "styles.22fd6f6d9bf5063e.css", "bootstrap": "bootstrap.e676380057cbc482.mjs", "manifest": "frontend.be0da04422e74637.json"};
const CACHE = `tuppi-${RELEASE}`;
const CONTENT = `tuppi-assets-v1:${self.registration.scope}`;
const at = path => new URL(path, self.registration.scope);
const readyURL = at('./offline-ready'), metadataURL = at('./offline-release.json');
const contentURL = file => at(`./__tuppi-assets/${file.sha256}`);
const preparing = new Map();
const cacheTask = callback => globalThis.navigator?.locks ? navigator.locks.request(`tuppi-offline-cache:${self.registration.scope}`, callback) : callback();
let progress = {type: 'offline-progress', release: RELEASE, state: 'idle', completedBytes: 0,
  totalBytes: FILES.reduce((sum, file) => sum + file.bytes, 0), completedFiles: 0, totalFiles: FILES.length};
async function sha256(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function announce(extra) {
  progress = {...progress, ...extra};
  for (const client of await self.clients.matchAll({includeUncontrolled: true, type: 'window'}))
    if (client.url.startsWith(self.registration.scope)) client.postMessage(progress);
}
async function verified(response, file) {
  if (!response?.ok) return false;
  const bytes = await response.clone().arrayBuffer();
  return bytes.byteLength === file.bytes && await sha256(bytes) === file.sha256;
}
async function readRelease(name, incomplete = false) {
  if (!/^tuppi-[a-f0-9]{64}$/.test(name)) return null;
  const cache = await caches.open(name);
  const markedReady = Boolean(await cache.match(readyURL));
  if (!markedReady && !incomplete) return null;
  const stored = await cache.match(metadataURL);
  if (stored) {
    const metadata = await stored.json();
    if (metadata.scope !== self.registration.scope || metadata.release !== name.slice(6)) return null;
    return {name, cache, metadata, markedReady};
  }
  // Infer old complete releases before retention; unknown caches are preserved.
  const models = await cache.match(at('./assets/models.json')), build = await cache.match(at('./assets/build.json'));
  if (!models || !build) return null;
  const a = new Uint8Array(await models.arrayBuffer()), b = new Uint8Array(await build.arrayBuffer());
  const joined = new Uint8Array(a.length + b.length); joined.set(a); joined.set(b, a.length);
  const frontend = await cache.match(at('./frontend.json'));
  if (!markedReady) return null;
  return {name, cache, markedReady, metadata: {scope: self.registration.scope, release: name.slice(6),
    identity: await sha256(joined), installedAt: 0, frontend: frontend ? await frontend.json() : null, files: null}};
}
async function releases(incomplete = false) {
  const records = await Promise.all((await caches.keys()).map(async name => {
    try { return await readRelease(name, incomplete); } catch { return null; }
  }));
  return records.filter(Boolean).sort((a, b) => b.metadata.installedAt - a.metadata.installedAt);
}
async function fileResponse(record, file) {
  const cache = file.shared ? await caches.open(CONTENT) : record.cache;
  return cache.match(file.shared ? contentURL(file) : at(file.path));
}
async function reused(file, cache, shared, previous) {
  const own = await (file.shared ? shared : cache).match(file.shared ? contentURL(file) : at(file.path));
  if (await verified(own, file)) return own;
  for (const record of previous) {
    const old = record.metadata.files?.find(item => item.sha256 === file.sha256);
    const response = old ? await fileResponse(record, old) : file.shared ?
      await record.cache.match(at(`./assets/${file.path.split('/').at(-1)}`)) : null;
    if (await verified(response, file)) return response;
  }
  return null;
}
async function downloaded(response, file) {
  if (!response.ok) throw new Error(`Tiedostoa ei voitu ladata (${response.status}).`);
  let bytes;
  if (response.body?.getReader) {
    const reader = response.body.getReader(); bytes = new Uint8Array(file.bytes);
    let offset = 0, lastReport = 0;
    for (;;) {
      const {done, value} = await reader.read(); if (done) break;
      if (offset + value.length > bytes.length) { await reader.cancel(); throw new Error('Tiedoston koko ei täsmää.'); }
      bytes.set(value, offset); offset += value.length;
      if (Date.now() - lastReport > 150) { lastReport = Date.now(); await announce({receivedBytes: offset}); }
    }
    if (offset !== file.bytes) throw new Error('Lataus jäi kesken.');
  } else bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length !== file.bytes || await sha256(bytes) !== file.sha256) throw new Error('Tiedoston tarkistus epäonnistui.');
  const headers = new Headers(response.headers);
  for (const name of ['Content-Length', 'Content-Encoding', 'Transfer-Encoding']) headers.delete(name);
  if (file.source_path) headers.set('Content-Type', 'text/html; charset=utf-8');
  return new Response(bytes, {status: 200, headers});
}
async function installRelease(target = {name: CACHE, metadata: {release: RELEASE, frontend: FRONTEND, files: FILES}}, engineOnly = false) {
  if (preparing.has(target.name)) return preparing.get(target.name);
  const {release, frontend} = target.metadata;
  const files = engineOnly ? engineFiles(target) : target.metadata.files;
  if (!files?.length) throw new Error('Aiempaa pelimoottoria ei voida palauttaa tästä paketista.');
  const task = cacheTask(async () => {
    const cache = await caches.open(target.name), shared = await caches.open(CONTENT), previous = await releases();
    await announce({state: 'downloading', totalBytes: files.reduce((sum, file) => sum + file.bytes, 0), totalFiles: files.length,
      completedBytes: 0, completedFiles: 0, receivedBytes: 0, error: null});
    try {
      for (const file of files) {
        await announce({file: file.path.split('/').at(-1), receivedBytes: 0});
        const response = await reused(file, cache, shared, previous) ?? await downloaded(await fetch(at(file.source_path ?? file.path), {cache: 'no-store'}), file);
        await (file.shared ? shared : cache).put(file.shared ? contentURL(file) : at(file.path), response);
        await announce({completedBytes: progress.completedBytes + file.bytes, completedFiles: progress.completedFiles + 1, receivedBytes: 0});
      }
      const metadata = {schema: 'tuppi.offline.release.v1', scope: self.registration.scope, release,
        identity: frontend.runtime_identity, installedAt: target.metadata.installedAt ?? Date.now(), frontend, files: target.metadata.files};
      await cache.put(metadataURL, new Response(JSON.stringify(metadata), {headers: {'Content-Type': 'application/json'}}));
      // Repairing an old engine need not retrieve obsolete, unversioned UI
      // sources. Only a whole release may advertise offline launch readiness.
      if ((await Promise.all(metadata.files.map(async file => Boolean(await fileResponse({cache}, file))))).every(Boolean))
        await cache.put(readyURL, new Response(release));
      await announce({state: 'ready', file: null});
    } catch (error) {
      // Verified partial files remain for retry. No readiness marker is written;
      // the previous active worker and complete release remain untouched.
      await cache.delete(readyURL);
      await announce({state: 'error', error: error.name === 'QuotaExceededError' ? 'Laitteen tallennustila ei riitä. Vapauta tilaa ja yritä uudelleen.' : error.message}); throw error;
    }
  });
  preparing.set(target.name, task);
  try { await task; } finally { preparing.delete(target.name); }
}
async function contains(record, paths) {
  if (!Array.isArray(paths) || !paths.length || paths.length > 8) return false;
  return (await Promise.all(paths.map(async path => {
    if (typeof path !== 'string' || !at(path).href.startsWith(self.registration.scope)) return false;
    const file = record.metadata.files?.find(file => at(file.path).href === at(path).href);
    return Boolean(file ? await fileResponse(record, file) : await record.cache.match(at(path)));
  }))).every(Boolean);
}
async function complete(record) {
  return record.markedReady && (!record.metadata.files || (await Promise.all(record.metadata.files.map(async file => Boolean(await fileResponse(record, file))))).every(Boolean));
}
function engineFiles(record) {
  const files = record.metadata.files, engine = record.metadata.frontend?.engine;
  if (![undefined, 'tuppi.local.worker.v1'].includes(record.metadata.frontend?.worker_protocol)) return null;
  if (!/^engine\.[a-f0-9]{16}\.mjs$/.test(engine ?? '') || !files?.some(file => file.path === engine) || !files.some(file => file.shared)) return null;
  return files.filter(file => file.shared || file.path === engine);
}
async function engineReady(record) {
  const files = engineFiles(record);
  return Boolean(files && (await Promise.all(files.map(async file => Boolean(await fileResponse(record, file))))).every(Boolean));
}
async function retain(protectedIdentities, paths) {
  const all = await releases(true), current = all.find(record => record.name === CACHE);
  if (!current || !await complete(current) || !await contains(current, paths) || !Array.isArray(protectedIdentities) || protectedIdentities.length > 4 ||
      protectedIdentities.some(id => !/^[a-f0-9]{64}$/.test(id))) return {removed: 0};
  const keep = new Set([CACHE]);
  const previous = all.find(record => record.name !== CACHE); if (previous) keep.add(previous.name);
  for (const identity of protectedIdentities) {
    const compatible = all.find(record => record.metadata.identity === identity);
    if (compatible && await complete(compatible)) keep.add(compatible.name); else return {removed: 0};
  }
  const clients = await self.clients.matchAll({includeUncontrolled: true, type: 'window'});
  for (const record of all) {
    if (!await complete(record)) keep.add(record.name);
    if (clients.some(client => record.metadata.frontend?.launch && new URL(client.url).pathname === at(record.metadata.frontend.launch).pathname)) keep.add(record.name);
    if (!record.metadata.files && record.metadata.identity !== FRONTEND.runtime_identity) keep.add(record.name);
  }
  let removed = 0;
  for (const record of all) if (!keep.has(record.name)) { await caches.delete(record.name); removed++; }
  const used = new Set(all.filter(record => keep.has(record.name)).flatMap(record =>
    record.metadata.files?.filter(file => file.shared).map(file => contentURL(file).href) ?? []));
  const shared = await caches.open(CONTENT);
  for (const request of await shared.keys()) if (!used.has(request.url)) await shared.delete(request);
  return {removed};
}
self.addEventListener('install', event => event.waitUntil(installRelease()));
// Never activate a replacement while existing tabs are using the old worker.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || !event.request.url.startsWith(self.registration.scope)) return;
  event.respondWith((async () => {
    const url = new URL(event.request.url); url.search = ''; url.hash = '';
    if (url.href === at('./current-release.json').href) return fetch(event.request);
    const all = await releases(true), current = all.find(record => record.name === CACHE);
    const client = event.clientId ? await self.clients.get(event.clientId) : null;
    const selected = client && all.find(record => record.metadata.frontend?.launch && new URL(client.url).pathname === at(record.metadata.frontend.launch).pathname);
    const records = selected ? [selected, ...all.filter(record => record !== selected)] : [current, ...all.filter(record => record !== current)];
    const immutable = /\/(?:client|engine|bootstrap|styles|launch|frontend)\.[a-f0-9]{16}\./.test(url.pathname) || /\/runtime\/[a-f0-9]{64}\//.test(url.pathname);
    for (const record of records.filter(Boolean)) {
      if (record !== (selected || current) && !immutable) continue;
      const file = record.metadata.files?.find(file => at(file.path).href === url.href);
      const response = file ? await fileResponse(record, file) : await record.cache.match(url);
      if (response) return response;
    }
    return fetch(event.request);
  })());
});
self.addEventListener('message', event => {
  const reply = data => event.ports?.[0]?.postMessage(data);
  if (event.data?.type === 'offline-status') event.waitUntil((async () => {
    const all = await releases(true), current = all.find(record => record.name === CACHE);
    let compatible = null, engine = null;
    if (/^[a-f0-9]{64}$/.test(event.data.identity ?? '')) for (const record of all)
      if (record.metadata.identity === event.data.identity) {
        if (!compatible && record.metadata.frontend?.launch && await complete(record)) compatible = record;
        if (!engine && await engineReady(record)) engine = record;
      }
    reply({...progress, ready: Boolean(current && await complete(current)), clientReady: current ? await contains(current, event.data.paths) : false,
      recovery: 1, release: RELEASE, identity: FRONTEND.runtime_identity, compatibleLaunch: compatible?.metadata.frontend.launch ?? null,
      compatibleEngine: engine?.metadata.frontend.engine ?? null,
      currentEngine: current && await engineReady(current) ? FRONTEND.engine : null});
  })());
  else if (event.data?.type === 'offline-repair') event.waitUntil((async () => {
    try {
      const identity = event.data.identity ?? FRONTEND.runtime_identity;
      if (!/^[a-f0-9]{64}$/.test(identity)) throw new Error('Peliversion tunniste on virheellinen.');
      const target = identity === FRONTEND.runtime_identity ? undefined :
        (await releases(true)).find(record => record.metadata.identity === identity && record.metadata.files?.length && record.metadata.frontend);
      if (identity !== FRONTEND.runtime_identity && !target)
        throw new Error('Aiempaa pelipakettia ei löydy tältä laitteelta. Lataa tallennus varmuuskopioksi tai aloita uusi ottelu.');
      await installRelease(target, Boolean(target)); reply({repaired: true});
    } catch (error) { reply({repaired: false, error: error.message}); }
  })());
  else if (event.data?.type === 'offline-retain') event.waitUntil((async () =>
    reply(globalThis.navigator?.locks ? await cacheTask(() => retain(event.data.identities, event.data.paths)) : {removed: 0}))());
});
