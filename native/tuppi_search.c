// Hidden-hand sampling for search.
//
// tc_sample_world draws the other three hands exactly uniformly from every
// assignment consistent with the observer's hard public constraints: hand
// sizes, cards already played, shown cards not yet played (known to be held by
// their shower), and voids revealed by failing to follow suit. Cards of one
// suit are exchangeable under these constraints, so the count of assignments
// factorises over suits; a DP over remaining capacities (at most 14^3 states)
// gives exact weights for the per-suit split counts.
#include <math.h>
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;
#define SUIT_MASK(s) (0x1FFFULL << ((s) * 13))
#define FULL_DECK ((1ULL << 52) - 1)

static inline u64 splitmix(u64 *x) {
  u64 z = (*x += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}
static inline double unit(u64 *x) { return (splitmix(x) >> 11) * (1.0 / 9007199254740992.0); }

static double lfact[53];
static int lfact_ready = 0;
static void init_lfact(void) {
  if (lfact_ready) return;
  lfact[0] = 0;
  for (int i = 1; i < 53; i++) lfact[i] = lfact[i - 1] + log((double)i);
  lfact_ready = 1;
}

// Rebuilds the full public trick state from an observation's history and fills
// everything in a TcDeal except the hidden hands.
static void public_state(const TcObs *o, TcDeal *d, int played_by[4], int void_mask[4], u64 *played_all) {
  memset(d, 0, sizeof *d);
  d->dealer = o->dealer;
  d->phase = o->phase;
  d->n_shows = o->n_shows;
  memcpy(d->show_seat, o->show_seat, 4);
  memcpy(d->show_card, o->show_card, 4);
  memcpy(d->show_contract, o->show_contract, 4);
  memcpy(d->show_verbal, o->show_verbal, 4);
  d->contract = o->contract;
  d->declarer = o->declarer;
  d->first_leader = o->first_leader;
  d->n_played = o->n_played;
  memcpy(d->play_card, o->play_card, o->n_played);
  memcpy(d->play_seat, o->play_seat, o->n_played);
  d->score[0] = o->score[0];
  d->score[1] = o->score[1];
  d->winner_team = -1;
  for (int i = 0; i < 4; i++) { played_by[i] = 0; void_mask[i] = 0; }
  *played_all = 0;
  int leader = o->first_leader, n = o->n_played;
  for (int t = 0; t < n; t += 4) {
    int led = o->play_card[t] / 13, best = t;
    for (int i = t; i < n && i < t + 4; i++) {
      int c = o->play_card[i], s = o->play_seat[i];
      played_by[s]++;
      *played_all |= 1ULL << c;
      if (c / 13 != led) void_mask[s] |= 1 << led;
      if (i > t && c / 13 == led && c % 13 > o->play_card[best] % 13) best = i;
    }
    if (t + 4 <= n) {
      int w = o->play_seat[best];
      d->team_tricks[w & 1]++;
      leader = w;
    }
  }
  if (o->phase == TC_PH_SHOW) d->cur = (uint8_t)((o->dealer + 1 + o->n_shows) & 3);
  else if (o->phase == TC_PH_PLAY) {
    int pos = n & 3;
    d->cur = (uint8_t)(pos ? ((o->play_seat[n - pos] + pos) & 3) : leader);
  }
}

// Returns 0 on success, -1 if the constraints admit no world.
int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out) {
  init_lfact();
  int played_by[4], void_mask[4];
  u64 played_all;
  public_state(o, out, played_by, void_mask, &played_all);
  const int me = o->seat;
  int others[3], k = 0;
  for (int s = 0; s < 4; s++) if (s != me) others[k++] = s;
  u64 known[4] = {0, 0, 0, 0};
  for (int i = 0; i < o->n_shows; i++) {
    int c = o->show_card[i], s = o->show_seat[i];
    if (s != me && !(played_all >> c & 1ULL)) known[s] |= 1ULL << c;
  }
  u64 known_all = known[0] | known[1] | known[2] | known[3];
  u64 free_cards = FULL_DECK & ~o->hand & ~played_all & ~known_all;
  int cap[3];
  for (int j = 0; j < 3; j++) {
    int s = others[j];
    cap[j] = 13 - played_by[s] - __builtin_popcountll(known[s]);
    if (cap[j] < 0) return -1;
  }
  int size[4];
  for (int v = 0; v < 4; v++) size[v] = __builtin_popcountll(free_cards & SUIT_MASK(v));
  if (size[0] + size[1] + size[2] + size[3] != cap[0] + cap[1] + cap[2]) return -1;

  // W[v][a][b] = log number of ways to place suits v..3 given remaining
  // capacities a, b for the first two others (the third is implied).
  double W[5][14][14];
  int remaining_after[5];
  remaining_after[4] = 0;
  for (int v = 3; v >= 0; v--) remaining_after[v] = remaining_after[v + 1] + size[v];
  for (int a = 0; a < 14; a++) for (int b = 0; b < 14; b++) W[4][a][b] = (a == 0 && b == 0) ? 0.0 : -INFINITY;
  for (int v = 3; v >= 0; v--) {
    int m = size[v];
    for (int a = 0; a < 14; a++) {
      for (int b = 0; b < 14; b++) {
        int c = remaining_after[v] - a - b;
        double best = -INFINITY, acc = 0.0;
        double terms[196]; int nt = 0;
        if (c < 0 || c > 13) { W[v][a][b] = -INFINITY; continue; }
        for (int x = 0; x <= m && x <= a; x++) {
          if (x && (void_mask[others[0]] >> v & 1)) break;
          for (int y = 0; x + y <= m && y <= b; y++) {
            if (y && (void_mask[others[1]] >> v & 1)) break;
            int z = m - x - y;
            if (z > c) continue;
            if (z && (void_mask[others[2]] >> v & 1)) continue;
            double rest = W[v + 1][a - x][b - y];
            if (rest == -INFINITY) continue;
            double t = lfact[m] - lfact[x] - lfact[y] - lfact[z] + rest;
            terms[nt++] = t;
            if (t > best) best = t;
          }
        }
        if (!nt) { W[v][a][b] = -INFINITY; continue; }
        for (int i = 0; i < nt; i++) acc += exp(terms[i] - best);
        W[v][a][b] = best + log(acc);
      }
    }
  }
  if (W[0][cap[0]][cap[1]] == -INFINITY) return -1;

  u64 hands[4] = {0, 0, 0, 0};
  hands[me] = o->hand;
  for (int s = 0; s < 4; s++) hands[s] |= known[s];
  int a = cap[0], b = cap[1];
  for (int v = 0; v < 4; v++) {
    int m = size[v], c = remaining_after[v] - a - b;
    double lw[196]; int sx[196], sy[196], ns = 0;
    for (int x = 0; x <= m && x <= a; x++) {
      if (x && (void_mask[others[0]] >> v & 1)) break;
      for (int y = 0; x + y <= m && y <= b; y++) {
        if (y && (void_mask[others[1]] >> v & 1)) break;
        int z = m - x - y;
        if (z > c || (z && (void_mask[others[2]] >> v & 1))) continue;
        double rest = W[v + 1][a - x][b - y];
        if (rest == -INFINITY) continue;
        lw[ns] = lfact[m] - lfact[x] - lfact[y] - lfact[z] + rest - W[v][a][b];
        sx[ns] = x; sy[ns] = y; ns++;
      }
    }
    if (!ns) return -1;
    double r = unit(rng), acc = 0.0;
    int pick = ns - 1;
    for (int i = 0; i < ns; i++) { acc += exp(lw[i]); if (r < acc) { pick = i; break; } }
    int cx = sx[pick], cy = sy[pick];
    // Deal the suit's free cards: a random permutation split x / y / z.
    int cards[13], nc = 0;
    u64 fm = free_cards & SUIT_MASK(v);
    while (fm) { cards[nc++] = __builtin_ctzll(fm); fm &= fm - 1; }
    for (int i = nc - 1; i > 0; i--) { int j = (int)(splitmix(rng) % (u64)(i + 1)); int t = cards[i]; cards[i] = cards[j]; cards[j] = t; }
    for (int i = 0; i < nc; i++) {
      int who = i < cx ? 0 : (i < cx + cy ? 1 : 2);
      hands[others[who]] |= 1ULL << cards[i];
    }
    a -= cx;
    b -= cy;
  }
  for (int s = 0; s < 4; s++) out->hand[s] = hands[s];
  return 0;
}
