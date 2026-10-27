const preferenceKey = 'tuppi.ui.preferences.v1';
const defaults = {nickname: 'Pelaaja', expandedHand: false, turnSound: false, shareResults: true, suitOrder: [0, 1, 2, 3]};
// The suits in the hand from left to right (0 ♥, 1 ♦, 2 ♣, 3 ♠), as in the Mac app.
export function validSuitOrder(order) {
  return Array.isArray(order) && order.length === 4 && [0, 1, 2, 3].every(suit => order.includes(suit));
}
function cleanPreferences(value) {
  return {nickname: typeof value?.nickname === 'string' && value.nickname.trim() ? value.nickname.trim().slice(0, 40) : defaults.nickname,
    expandedHand: value?.expandedHand === true, turnSound: value?.turnSound === true,
    // Offline development records exclude names; sharing is on unless disabled.
    shareResults: value?.shareResults !== false,
    suitOrder: validSuitOrder(value?.suitOrder) ? [...value.suitOrder] : [...defaults.suitOrder]};
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
