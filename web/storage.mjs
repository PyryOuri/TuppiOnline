let database;
function open() {
  if (!database) database = new Promise((resolve, reject) => {
    const request = indexedDB.open('tuppi-local', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('saves');
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => { db.close(); database = null; };
      db.onclose = () => { database = null; };
      resolve(db);
    };
    request.onerror = () => reject(request.error);
  }).catch(error => { database = null; throw error; });
  return database;
}

async function hash(save) {
  const bytes = new TextEncoder().encode(JSON.stringify(save));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function envelope(save) { return {format: 'tuppi.local.backup.v1', sha256: await hash(save), save}; }
export async function unwrap(record) {
  if (!record || record.format !== 'tuppi.local.backup.v1' || await hash(record.save) !== record.sha256)
    throw new Error('Tallennuksen tarkistus epäonnistui.');
  return record.save;
}

export async function readLocalRecord(key = 'current') {
  if (!['current', 'previous'].includes(key)) throw new Error('Tuntematon paikallinen tallennus.');
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db.transaction('saves').objectStore('saves').get(key);
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
}

export async function load() {
  const record = await readLocalRecord();
  return record ? unwrap(record) : null;
}

export async function store(save, {replace = false} = {}) {
  const record = await envelope(save), db = await open();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('saves', 'readwrite');
    const saves = transaction.objectStore('saves');
    if (replace) {
      // Copy and replacement commit together. A quota/abort failure preserves
      // both the old match and its previous recovery copy, including raw data
      // whose integrity check failed. Never touch the separate network key.
      const request = saves.get('current');
      request.onsuccess = () => {
        if (request.result && JSON.stringify(request.result) !== JSON.stringify(record)) saves.put(request.result, 'previous');
        saves.put(record, 'current');
      };
    } else saves.put(record, 'current');
    transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error('Tallennus keskeytyi.'));
  });
}

// Online credentials occupy a separate key and never enter offline backups.
export async function loadNetwork() {
  const db = await open();
  const record = await new Promise((resolve, reject) => {
    const request = db.transaction('saves').objectStore('saves').get('network');
    request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
  });
  return record ? unwrap(record) : null;
}
export async function storeNetwork(session) {
  const record = await envelope(session), db = await open();
  await new Promise((resolve, reject) => {
    const transaction = db.transaction('saves', 'readwrite');
    transaction.objectStore('saves').put(record, 'network');
    transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error('Verkkopelin tallennus keskeytyi.'));
  });
}

export async function storageHealth({requestPersistence = false, storage = navigator.storage} = {}) {
  let persistent = null, usage = null, quota = null;
  const errors = [];
  if (storage?.persisted) {
    try { persistent = await storage.persisted(); } catch (error) { errors.push(error.message); }
  }
  if (requestPersistence && persistent !== true && storage?.persist) {
    try { persistent = await storage.persist(); } catch (error) { errors.push(error.message); }
  }
  if (storage?.estimate) {
    try {
      const estimate = await storage.estimate();
      if (Number.isFinite(estimate.usage)) usage = estimate.usage;
      if (Number.isFinite(estimate.quota)) quota = estimate.quota;
    } catch (error) { errors.push(error.message); }
  }
  return {persistent, usage, quota, available: usage !== null && quota !== null ? Math.max(0, quota - usage) : null,
    canRequest: Boolean(storage?.persist), errors};
}
