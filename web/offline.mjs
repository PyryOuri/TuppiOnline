// The packager pins this value without changing runtime/model save identity.
export const packagedRuntimeIdentity = null;

export class OfflineSetup {
  constructor({serviceWorker = navigator.serviceWorker, paths, onChange = () => {}} = {}) {
    this.serviceWorker = serviceWorker; this.paths = paths; this.onChange = onChange;
    this.registration = null; this.state = {state: 'idle', ready: false}; this.queryToken = 0;
  }
  request(worker, data, timeout = 5000) {
    if (!worker) return Promise.resolve(null);
    return new Promise(resolve => {
      const channel = new MessageChannel(), timer = setTimeout(() => { channel.port1.close(); resolve(null); }, timeout);
      channel.port1.onmessage = ({data}) => { clearTimeout(timer); channel.port1.close(); resolve(data); };
      try { worker.postMessage(data, [channel.port2]); }
      catch { clearTimeout(timer); channel.port1.close(); resolve(null); }
    });
  }
  async refresh() {
    if (!this.registration) return;
    const token = ++this.queryToken, registration = this.registration;
    const active = registration.active, newest = registration.installing ?? registration.waiting ?? active;
    const [current, update] = await Promise.all([this.request(active, {type: 'offline-status', paths: this.paths}),
      newest !== active ? this.request(newest, {type: 'offline-status', paths: this.paths}) : Promise.resolve(null)]);
    if (token !== this.queryToken) return;
    this.activeStatus = current;
    const data = update ?? current ?? {state: 'idle'};
    const ready = Boolean(current?.ready && current.clientReady);
    const error = data.error ?? (!ready && !['downloading', 'ready'].includes(data.state) ? this.state.error : null);
    this.state = {...data, state: error ? 'error' : data.state ?? (ready ? 'ready' : 'idle'), ready,
      updateReady: Boolean(update?.ready), error};
    this.onChange(this.state);
  }
  watch(worker) {
    if (!worker) return;
    worker.addEventListener('statechange', () => {
      if (worker.state === 'redundant' && !this.state.ready) {
        this.state = {...this.state, state: 'error', error: this.state.error ?? 'Offline-lataus jäi kesken. Yritä uudelleen.'};
        this.onChange(this.state);
      } else this.refresh();
    });
  }
  async start() {
    if (this.started) return this.started;
    this.started = this.begin();
    return this.started;
  }
  async begin() {
    if (!this.serviceWorker) {
      this.state = {state: 'unavailable', ready: false, error: 'Tämä selain ei tue offline-käynnistystä.'};
      this.onChange(this.state); return;
    }
    this.serviceWorker.addEventListener('message', ({data}) => {
      if (data?.type !== 'offline-progress') return;
      this.state = {...this.state, ...data}; this.onChange(this.state);
      if (['ready', 'error'].includes(data.state)) this.refresh();
    });
    this.serviceWorker.addEventListener('controllerchange', () => this.refresh());
    await this.retry();
  }
  async retry() {
    try {
      this.registration = await this.serviceWorker.register('./sw.mjs', {type: 'module'});
      this.registration.addEventListener('updatefound', () => this.watch(this.registration.installing));
      this.watch(this.registration.installing);
      await this.refresh();
      if (!this.registration.installing && !this.registration.waiting && !this.state.ready) {
        // An unchanged worker script is not reinstalled after cache eviction.
        // Rehydrate its verified release explicitly before checking for updates.
        if (this.registration.active && this.activeStatus?.recovery === 1) await this.repair(packagedRuntimeIdentity);
        await this.registration.update();
      }
    } catch (error) {
      this.registration ??= await this.serviceWorker.getRegistration().catch(() => null);
      if (this.registration?.active) await this.refresh();
      if (!this.state.ready) { this.state = {...this.state, state: 'error', error: error.message}; this.onChange(this.state); }
    }
  }
  // After the game server returns from a restart (perhaps a new release),
  // look for a newer browser release, at most every ten minutes. It installs
  // in the background and never activates beneath an open Tuppi.
  async checkForUpdate(now = Date.now()) {
    if (!this.registration || now - (this.lastUpdateCheck ?? -Infinity) < 600000) return false;
    this.lastUpdateCheck = now;
    try { await this.registration.update(); } catch { return false; }
    await this.refresh(); return true;
  }
  async compatible(identity) {
    return (await this.release(identity))?.launch ?? null;
  }
  async latestInstalled() {
    this.registration ??= await this.serviceWorker?.getRegistration();
    const data = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths});
    if (!/^[a-f0-9]{64}$/.test(data?.identity ?? '')) return null;
    this.activeStatus = data;
    return {identity: data.identity,
      engine: /^engine\.[a-f0-9]{16}\.mjs$/.test(data.currentEngine ?? '') ? data.currentEngine : null};
  }
  async release(identity) {
    if (!/^[a-f0-9]{64}$/.test(identity ?? '')) return null;
    this.registration ??= await this.serviceWorker?.getRegistration();
    const data = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths, identity});
    const launch = /^launch\.[a-f0-9]{16}\.html$/.test(data?.compatibleLaunch ?? '') ? data.compatibleLaunch : null;
    const engine = /^engine\.[a-f0-9]{16}\.mjs$/.test(data?.compatibleEngine ?? '') ? data.compatibleEngine : null;
    return launch || engine ? {identity, launch, engine} : null;
  }
  async repair(identity = packagedRuntimeIdentity) {
    this.registration ??= await this.serviceWorker?.getRegistration();
    const status = await this.request(this.registration?.active, {type: 'offline-status', paths: this.paths});
    if (status?.recovery !== 1) throw new Error('Sulje kaikki Tuppi-ikkunat ja avaa peli uudelleen päivityksen valmistuttua. Tallennukset säilyvät.');
    const data = await this.request(this.registration?.active, {type: 'offline-repair', identity}, 120000);
    await this.refresh();
    if (!data?.repaired) throw new Error(data?.error ?? 'Pelitiedostoja ei voitu palauttaa. Tarkista verkkoyhteys ja yritä uudelleen.');
    return data;
  }
  async retain(identities) {
    if (this.registration?.installing || this.registration?.waiting || !this.state.ready) return;
    return this.request(this.registration.active, {type: 'offline-retain', paths: this.paths, identities});
  }
}
