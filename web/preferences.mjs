const preferenceKey = 'tuppi.ui.preferences.v1';
const defaults = {nickname: 'Pelaaja', expandedHand: false, turnSound: false, shareResults: true};
function cleanPreferences(value) {
  return {nickname: typeof value?.nickname === 'string' && value.nickname.trim() ? value.nickname.trim().slice(0, 40) : defaults.nickname,
    expandedHand: value?.expandedHand === true, turnSound: value?.turnSound === true,
    // Anonymous offline match results for research (opt-out).
    shareResults: value?.shareResults !== false};
}
// Optional UI preferences cannot prevent a match from opening. They never
// contain room credentials, actions, cards or an offline save.
export function loadPreferences(storage) {
  try { return cleanPreferences(JSON.parse((storage ?? globalThis.localStorage)?.getItem(preferenceKey) ?? 'null')); }
  catch { return {...defaults}; }
}
export function savePreferences(value, storage) {
  const preferences = cleanPreferences(value);
  try { (storage ?? globalThis.localStorage)?.setItem(preferenceKey, JSON.stringify(preferences)); }
  catch {}
  return preferences;
}
