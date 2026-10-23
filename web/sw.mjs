const RELEASE = "b056a7daed495bef188b74bdcdcb20ba61efeb7e175c6ca9f1d90fd167fd38f4";
const FILES = [{"path": "index.html", "sha256": "31be59ad2ecca75d3f058d10013120bddcebc44067848337f775c89303dfb3a2", "bytes": 27457, "shared": false, "source_path": "offline-shell.31be59ad2ecca75d.txt"}, {"path": "app.mjs", "sha256": "6784a195c019138cebc20c821e36c8179abde8196de12eab30d860072767d243", "bytes": 106996, "shared": false}, {"path": "styles.css", "sha256": "b96c2ef05282cff461f77f7f5722f66520ba5dd94a7941b9ac4727877d1a7577", "bytes": 40146, "shared": false}, {"path": "table.mjs", "sha256": "a3afdf849408b0be05bc175533a02f0f3d526396c6a5fe7ad791a81353ffc75a", "bytes": 4278, "shared": false}, {"path": "runtime.mjs", "sha256": "2d0656f138f23f72fa306f855afb5b0e8de2610fc5313d6e64d2e246528c7748", "bytes": 12708, "shared": false}, {"path": "session.mjs", "sha256": "4facc26395dfbe55dcb75a941c14bc31433a128103a5750ca6e3bafcbe6fa57d", "bytes": 12056, "shared": false}, {"path": "worker.mjs", "sha256": "d82eff23f89acfe8b1d96171fe19d175a96c6f75d5f596947ad826629d1ad375", "bytes": 9215, "shared": false}, {"path": "storage.mjs", "sha256": "298c8bc44d0c61a980196ee8df8e2bc63fcc1171c0f2f5f30e3e481bc3ccae85", "bytes": 4525, "shared": false}, {"path": "offline.mjs", "sha256": "f407a453c9024f4464b2f7803b4907ce55d0f7831574e21f65e2b518269b91ab", "bytes": 6555, "shared": false}, {"path": "network.mjs", "sha256": "248d704af88e989e8224b09864f7ebfe4090953feaaf89d0253f3f4e2b2ba8d1", "bytes": 40756, "shared": false}, {"path": "hand.mjs", "sha256": "bafaf9ec4582e7d786f3b011e5efc3fec276295180eefe7f4c6d046aed18b8e3", "bytes": 2718, "shared": false}, {"path": "presentation.mjs", "sha256": "3cd77dd727191d0352febdc77480c337da0e7e783513524007dc78b274a8d990", "bytes": 6800, "shared": false}, {"path": "capabilities.mjs", "sha256": "e19671e943b5bbb1e8bc299e746b9654ddd8c3bf6202809a59a677b5e72b26c0", "bytes": 118, "shared": false}, {"path": "lobby.mjs", "sha256": "d252aa0e8e9c3b312d5fee78b1cdc04a3126d13fd79f1ce59dfa1b539356601e", "bytes": 9785, "shared": false}, {"path": "preferences.mjs", "sha256": "3c6e248307bb7e81be44e29df62447fd3642d3048d4cdd8c2ac485323076f2c2", "bytes": 1456, "shared": false}, {"path": "manifest.webmanifest", "sha256": "e19b09834a05463e6dbadac914c34fb7e27139789bbd1b2e1571f93d37f705a3", "bytes": 415, "shared": false}, {"path": "icon.svg", "sha256": "5ddfb27fe2fc146ba4a3fa984f3fd94158089a524c2095e445e258a658b6480c", "bytes": 346, "shared": false}, {"path": "icon-180.png", "sha256": "f12122f5933634846592afaa7b6ed8e89cfbebde39526910ab63844312e5e9a9", "bytes": 4495, "shared": false}, {"path": "icon-192.png", "sha256": "3ba0356df63c9d51b30ef4ed32d6878bb4f7233da7356094ab31a21016108dfb", "bytes": 4684, "shared": false}, {"path": "icon-512.png", "sha256": "cdb05c6e2745c938ab8a84ad0bacd3bd33488c017d0889f9466bcace453e807f", "bytes": 17323, "shared": false}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/tuppi.mjs", "sha256": "0da5645c9ad1a88ab0fe036785013ef851839e71cb0e3c709b0d3834fce2de78", "bytes": 9438, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/tuppi.wasm", "sha256": "1b51c92de5e9b7b6e3a24c1bdb51c62e290c2e2f5548e1d92d8be1acf0be6517", "bytes": 113078, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/models.json", "sha256": "8cb282aa3be3c4ebc0c4bcfcaaeceda93a9c225e3e51488148df181771ae2124", "bytes": 1673, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/build.json", "sha256": "7061aa10aad198a4f79452268afa4e83964c6e5db89628d102c98b0090724203", "bytes": 12528, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/vrpo1_actor_0504.f32", "sha256": "beb1f890947748a3df254dc200b9433547babc9fe40388fe76ba82e0f01abbda", "bytes": 3218032, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/vrpo3_final.f32", "sha256": "0e4bba619908ad3fa92a75fb118470b436ffa571caaca5e8f6aab497be633b47", "bytes": 12743280, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/equity.f64", "sha256": "8e01246f723210a8e0364a63748de460b94b6e5a513e8e747dc91744f1bc3f0b", "bytes": 400, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/tuppi-thread.mjs", "sha256": "79d7546158f4aa79b921a0dadd656078230f69ab23f0a7d65ac3333d01b1ffa8", "bytes": 23783, "shared": true}, {"path": "runtime/31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413/tuppi-thread.wasm", "sha256": "132067b70b95f5a455e02d668988728d02747747be2760fc3f762c3a0dfbaeff", "bytes": 126902, "shared": true}, {"path": "bootstrap.mjs", "sha256": "0dca44985ea97c0db137281c1f767bf69f752281dc5dd7b23ec07a33a9ba4566", "bytes": 3197, "shared": false}, {"path": "recover.html", "sha256": "d96df6aab96a15621dbf5f21962b9d2159e43481e22f0c44c58f89dc4dec53f0", "bytes": 682, "shared": false, "source_path": "offline-shell.d96df6aab96a1562.txt"}, {"path": "recover.mjs", "sha256": "44a9ea47ff5424120abc840da93d224e7e2bc0efbda234e4480cd45f9dca33b4", "bytes": 1706, "shared": false}, {"path": "recover.css", "sha256": "61151cef850846caa9373061b911d0b4ce74d29dac4929a2b9e89d8d35bd959f", "bytes": 403, "shared": false}, {"path": "frontend.json", "sha256": "3c728bfdbffca29b730a9da3aab7a2c6e4ec0bc4fe9e5310cc74c1d8c3d1dff4", "bytes": 690, "shared": false}, {"path": "client.8b7d5f92a3e6d15b.mjs", "sha256": "8b7d5f92a3e6d15b4aea037546f3bdf734a71b0cfc4d5c2f44459311835cd37a", "bytes": 212739, "shared": false}, {"path": "engine.cc87cf7f8af415a5.mjs", "sha256": "cc87cf7f8af415a588cd9d86ad9849d68c9aed3491fff0c71153dd08c992925f", "bytes": 39493, "shared": false}, {"path": "launch.b78890772ac337b1.html", "sha256": "0f95d8770ed1526181de6bdeeafc9696b12657034f6216955823ccafaf917aa0", "bytes": 27491, "shared": false, "source_path": "offline-shell.0f95d8770ed15261.txt"}, {"path": "styles.b96c2ef05282cff4.css", "sha256": "b96c2ef05282cff461f77f7f5722f66520ba5dd94a7941b9ac4727877d1a7577", "bytes": 40146, "shared": false}, {"path": "bootstrap.6428ca88a057b2ce.mjs", "sha256": "6428ca88a057b2ce060db6d6493c144a32d5562b5fadfc6580613b321788ab51", "bytes": 3214, "shared": false}, {"path": "frontend.b78890772ac337b1.json", "sha256": "3c728bfdbffca29b730a9da3aab7a2c6e4ec0bc4fe9e5310cc74c1d8c3d1dff4", "bytes": 690, "shared": false}, {"path": "./", "sha256": "31be59ad2ecca75d3f058d10013120bddcebc44067848337f775c89303dfb3a2", "bytes": 27457, "shared": false, "source_path": "offline-shell.31be59ad2ecca75d.txt"}];
const FRONTEND = {"schema": "tuppi.browser.frontend.v1", "client": "client.8b7d5f92a3e6d15b.mjs", "client_sha256": "8b7d5f92a3e6d15b4aea037546f3bdf734a71b0cfc4d5c2f44459311835cd37a", "engine": "engine.cc87cf7f8af415a5.mjs", "engine_sha256": "cc87cf7f8af415a588cd9d86ad9849d68c9aed3491fff0c71153dd08c992925f", "runtime_identity": "31426bbf97821e2c275339a66147d8cdfe7ffcbbc6b089b3b9bbc41881415413", "worker_protocol": "tuppi.local.worker.v1", "capabilities": {"offline": true, "network": true}, "launch": "launch.b78890772ac337b1.html", "styles": "styles.b96c2ef05282cff4.css", "bootstrap": "bootstrap.6428ca88a057b2ce.mjs", "manifest": "frontend.b78890772ac337b1.json"};
const CACHE = `tuppi-${RELEASE}`;
const CONTENT = `tuppi-assets-v1:${self.registration.scope}`;
const at = path => new URL(path, self.registration.scope);
const readyURL = at('./offline-ready'), metadataURL = at('./offline-release.json');
const contentURL = file => at(`./__tuppi-assets/${file.sha256}`);
const preparing = new Map();
function isolatedResponse(response) {
  // Previously installed files can have the same bytes and older headers.
  // Apply current delivery policy to both new and retained immutable engines.
  const headers = new Headers(response.headers);
  headers.set('Cross-Origin-Opener-Policy', 'same-origin');
  headers.set('Cross-Origin-Embedder-Policy', 'require-corp');
  headers.set('Cross-Origin-Resource-Policy', 'same-origin');
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
}
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
      if (response) return isolatedResponse(response);
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
