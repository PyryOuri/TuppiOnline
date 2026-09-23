// Observation-only sooli heuristics (project_target_v2).
//
// Used as the rollout policy for sooli decisions inside search, and as the
// sooli behaviour of baseline players. Everything here reads a TcObs only.
//
//  - Offer: decline unless every suit held has a low card (at most one suit,
//    a singleton that can be given away, may not); otherwise a small Monte
//    Carlo: in `OFFER_WORLDS` worlds drawn from the observation, exchange with
//    these heuristics and solve the play with perfect information; accept if
//    the soolaaja survives in at least half of them.
//  - Give: the card whose removal leaves the least exposed hand.
//  - Return: the lowest card, preferring other suits than the received card's
//    and suits the partner is short in (where the soolaaja is likely long).
//  - Play: the soolaaja ducks as high as it can and discards to reduce
//    exposure; RAMI players lead their lowest cards where the soolaaja may
//    still follow, follow under the leader's card and discard high.
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;
#define SM 0x1FFFULL
#define FULL_DECK ((1ULL << 52) - 1)
#define OFFER_WORLDS 8

int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out);

static inline u64 to_low(u64 h) {
  u64 out = 0;
  for (int s = 0; s < 4; s++) {
    u64 m = (h >> (13 * s)) & SM;
    out |= (((m & 0xFFFULL) << 1) | (m >> 12)) << (13 * s);
  }
  return out;
}
static inline int low_of(int c) { int s = c / 13, r = c % 13; return s * 13 + (r == 12 ? 0 : r + 1); }
static inline int high_of(int p) { int s = p / 13, r = p % 13; return s * 13 + (r == 0 ? 12 : r - 1); }

// Exposure of a soolaaja hand (low layout): in each suit, with own cards
// m_1 < ... < m_k, the sum over i of how many other live cards lie below m_i
// beyond the i - 1 rounds already survived.
static int exposure(u64 mine, u64 others) {
  int d = 0;
  for (int s = 0; s < 4; s++) {
    u64 M = (mine >> (13 * s)) & SM, O = (others >> (13 * s)) & SM;
    int i = 0;
    while (M) {
      int c = __builtin_ctzll(M);
      M &= M - 1;
      int below = __builtin_popcountll(O & ((1ULL << c) - 1));
      if (below > i) d += below - i;
      i++;
    }
  }
  return d;
}

static u64 played_mask(const TcObs *o) {
  u64 m = 0;
  for (int i = 0; i < o->n_played; i++) m |= 1ULL << o->play_card[i];
  return m;
}

// The card (ace-high index) of `hand` whose removal minimises exposure; ties
// go to the higher card.
static int least_exposed_without(u64 hand, u64 others_high) {
  u64 mine = to_low(hand), others = to_low(others_high);
  int best = -1, best_d = 1 << 30, best_r = -1;
  for (u64 m = hand; m; m &= m - 1) {
    int c = __builtin_ctzll(m), p = low_of(c);
    int d = exposure(mine & ~(1ULL << p), others);
    if (d < best_d || (d == best_d && p % 13 > best_r)) { best = c; best_d = d; best_r = p % 13; }
  }
  return best;
}

static int give_card(const TcObs *o) {
  u64 others = FULL_DECK & ~o->hand & ~played_mask(o);
  return least_exposed_without(o->hand, others);
}

static int return_card(const TcObs *o) {
  int g = o->known_given, best = -1;
  long best_key = 1L << 40;
  for (u64 m = o->hand; m; m &= m - 1) {
    int c = __builtin_ctzll(m);
    if (c == g) continue;
    int p = low_of(c), suit = c / 13;
    int held = __builtin_popcountll(o->hand & (SM << (13 * suit)));
    long key = (long)(p % 13) * 1000 + (g >= 0 && suit == g / 13 ? 100 : 0) + held;
    if (key < best_key) { best_key = key; best = c; }
  }
  return best;
}

static int play_card(const TcObs *o) {
  const int me = o->seat, S = o->soolaaja;
  int n = o->n_played, pos = n % 3;
  u64 hand = o->hand, played = played_mask(o);
  if (me == S) {
    int start = n - pos, led = o->play_card[start] / 13, hi = -1;
    for (int i = start; i < n; i++)
      if (o->play_card[i] / 13 == led && low_of(o->play_card[i]) > hi) hi = low_of(o->play_card[i]);
    u64 follow = to_low(hand) & (SM << (13 * led));
    if (follow) {
      u64 safe = follow & ((1ULL << hi) - 1);
      u64 pick = safe ? safe : follow;
      return high_of(63 - __builtin_clzll(pick));
    }
    return least_exposed_without(hand, FULL_DECK & ~hand & ~played);
  }
  // RAMI players. Voids the soolaaja has shown in sooli play:
  int s_void = 0;
  for (int t = 0; t + 3 <= n; t += 3) {
    int led = o->play_card[t] / 13;
    for (int i = t; i < t + 3; i++)
      if (o->play_seat[i] == S && o->play_card[i] / 13 != led) s_void |= 1 << led;
  }
  if (pos == 1 && n % 3 == 1) {
    int a = o->play_card[n - 1], led = a / 13;
    u64 follow = to_low(hand) & (SM << (13 * led));
    if (follow) {
      u64 under = follow & ((1ULL << low_of(a)) - 1);
      if (under) return high_of(63 - __builtin_clzll(under));  // keep the lowest for later leads
      return high_of(__builtin_ctzll(follow));
    }
    return high_of(63 - __builtin_clzll(to_low(hand)));  // discard the highest
  }
  // Leader: the card with the fewest unseen cards below it in a suit the
  // soolaaja may still hold; then suits with more unseen cards; then lowest.
  u64 unseen = to_low(FULL_DECK & ~hand & ~played);
  int best = -1;
  long best_key = 1L << 40;
  for (u64 m = to_low(hand); m; m &= m - 1) {
    int p = __builtin_ctzll(m), suit = p / 13;
    u64 us = unseen & (SM << (13 * suit));
    int below = __builtin_popcountll(us & ((1ULL << p) - 1));
    long key = (long)((s_void >> suit & 1) || !us) * 100000 + below * 1000 + (13 - __builtin_popcountll(us)) * 20 + p % 13;
    if (key < best_key) { best_key = key; best = p; }
  }
  return high_of(best);
}

static int offer_prefilter(u64 hand) {
  u64 low = to_low(hand);
  int lethal = 0, lethal_single = 1;
  for (int s = 0; s < 4; s++) {
    u64 m = (low >> (13 * s)) & SM;
    if (!m) continue;
    if (__builtin_ctzll(m) >= 4) {
      lethal++;
      if (__builtin_popcountll(m) > 1) lethal_single = 0;
    }
  }
  return lethal == 0 || (lethal == 1 && lethal_single);
}

int tc_sooli_policy(const TcObs *o, uint64_t *rng);

// Survival of the observer as soolaaja in one world at the offer, with the
// heuristic exchange and perfect-information play.
static int survives_in(TcDeal *w, uint64_t *rng) {
  if (tc_apply(w, TC_ACT_SOOLI_ACCEPT) != 0) return 0;
  TcObs ob;
  for (int step = 0; step < 2; step++) {
    tc_observe(w, w->cur, &ob);
    if (tc_apply(w, tc_sooli_policy(&ob, rng)) != 0) return 0;
  }
  return tc_sooli_solve(w) == 1;
}

static int offer(const TcObs *o, uint64_t *rng) {
  if (!offer_prefilter(o->hand)) return TC_ACT_SOOLI_DECLINE;
  int alive = 0;
  TcDeal w;
  for (int i = 0; i < OFFER_WORLDS; i++) {
    if (tc_sample_world(o, rng, &w) != 0) return TC_ACT_SOOLI_DECLINE;
    alive += survives_in(&w, rng);
  }
  return 2 * alive >= OFFER_WORLDS ? TC_ACT_SOOLI_ACCEPT : TC_ACT_SOOLI_DECLINE;
}

// Heuristic action for the observer in a sooli phase; -1 otherwise.
int tc_sooli_policy(const TcObs *o, uint64_t *rng) {
  switch (o->phase) {
    case TC_PH_SOOLI_OFFER: return offer(o, rng);
    case TC_PH_SOOLI_GIVE: return TC_ACT_EXCHANGE + give_card(o);
    case TC_PH_SOOLI_RETURN: return TC_ACT_EXCHANGE + return_card(o);
    case TC_PH_SOOLI_PLAY: return play_card(o);
    default: return -1;
  }
}

// Sooli-conditioned worlds. The uniform sampler ignores that the soolaaja
// chose to play sooli; these modes reject worlds whose soolaaja hand would
// not have been offered (up to SOOLI_TRIES draws, then the last uniform one):
//   bit 0: the soolaaja's hand passes the offer prefilter (before the
//          exchange when the observer knows it, i.e. the partner during the
//          return; the post-exchange hand, incl. cards played since, for RAMI
//          observers);
//   bit 1: the partner during the return: the heuristic give from that hand is
//          the card actually received.
// Mode 0 or any other observer or phase is tc_sample_world.
#define SOOLI_TRIES 400
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode) {
  const int S = o->soolaaja, P = (S + 2) & 3;
  int applies = mode && S >= 0 && o->seat != S &&
                ((o->phase == TC_PH_SOOLI_RETURN && o->seat == P) || (o->phase == TC_PH_SOOLI_PLAY && o->seat != P));
  if (!applies) return tc_sample_world(o, rng, out);
  u64 played = played_mask(o);
  for (int t = 0; t < SOOLI_TRIES; t++) {
    if (tc_sample_world(o, rng, out) != 0) return -1;
    u64 s_hand = out->hand[S];
    for (int i = 0; i < o->n_played; i++) if (o->play_seat[i] == S) s_hand |= 1ULL << o->play_card[i];
    if (o->phase == TC_PH_SOOLI_RETURN) s_hand |= 1ULL << o->known_given;
    if ((mode & 1) && !offer_prefilter(s_hand)) continue;
    if ((mode & 2) && o->phase == TC_PH_SOOLI_RETURN) {
      u64 others = FULL_DECK & ~s_hand & ~played;
      if (least_exposed_without(s_hand, others) != o->known_given) continue;
    }
    return 0;
  }
  return 0;  // keep the last uniform world
}

// The offer heuristic's static test alone (exposed for tests and analysis).
int tc_sooli_offer_prefilter(uint64_t hand) { return offer_prefilter(hand); }
