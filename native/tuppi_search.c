// Hidden-hand sampling for search.
//
// tc_sample_world draws the other three hands exactly uniformly from every
// assignment consistent with the observer's hard public constraints: hand
// sizes, cards already played, shown cards not yet played (known to be held by
// their shower), and voids revealed by failing to follow suit. Cards of one
// suit are exchangeable under these constraints, so the count of assignments
// factorises over suits; a DP over remaining capacities (at most 14^3 states)
// gives exact weights for the per-suit split counts.
#include <dispatch/dispatch.h>
#include <math.h>
#include <stdlib.h>
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

// Filled once: the sooli heuristics sample worlds from several threads at a
// time (search_core resolves rollouts' soolis in parallel).
static double lfact[53];
static void fill_lfact(void *unused) {
  (void)unused;
  lfact[0] = 0;
  for (int i = 1; i < 53; i++) lfact[i] = lfact[i - 1] + log((double)i);
}
static void init_lfact(void) {
  static dispatch_once_t once;
  dispatch_once_f(&once, NULL, fill_lfact);
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
  d->ruleset = o->ruleset == 2 || o->ruleset == 3 ? o->ruleset : 1;
  d->trick_size = o->trick_size == 3 ? 3 : 4;
  d->n_decisions = o->n_decisions;
  memcpy(d->decision_seat, o->decision_seat, 2);
  memcpy(d->decision_accept, o->decision_accept, 2);
  d->soolaaja = o->soolaaja;
  d->given = o->known_given;
  d->returned = o->known_returned;
  for (int i = 0; i < 4; i++) { played_by[i] = 0; void_mask[i] = 0; }
  *played_all = 0;
  const int ts = d->trick_size;
  int leader = ts == 3 ? o->declarer : o->first_leader, n = o->n_played;
  for (int t = 0; t < n; t += ts) {
    int led = o->play_card[t] / 13, best = t;
    for (int i = t; i < n && i < t + ts; i++) {
      int c = o->play_card[i], s = o->play_seat[i];
      played_by[s]++;
      *played_all |= 1ULL << c;
      if (c / 13 != led) void_mask[s] |= 1 << led;
      int higher = ts == 3 ? tc_sooli_rank(c) > tc_sooli_rank(o->play_card[best]) : c % 13 > o->play_card[best] % 13;
      if (i > t && c / 13 == led && higher) best = i;
    }
    if (t + ts <= n) {
      int w = o->play_seat[best];
      d->team_tricks[w & 1]++;
      leader = w;
    }
  }
  if (o->phase == TC_PH_SHOW) d->cur = (uint8_t)((o->dealer + 1 + o->n_shows) & 3);
  else if (o->phase == TC_PH_PLAY) {
    int pos = n & 3;
    d->cur = (uint8_t)(pos ? ((o->play_seat[n - pos] + pos) & 3) : leader);
  } else if (o->phase == TC_PH_SOOLI_OFFER) {
    d->cur = (uint8_t)((o->declarer + (o->n_decisions ? 3 : 1)) & 3);
  } else if (o->phase == TC_PH_SOOLI_GIVE) {
    d->cur = (uint8_t)o->soolaaja;
  } else if (o->phase == TC_PH_SOOLI_RETURN) {
    d->cur = (uint8_t)((o->soolaaja + 2) & 3);
  } else if (o->phase == TC_PH_SOOLI_PLAY) {
    int pos = n % 3, lead = pos ? o->play_seat[n - pos] : leader;
    d->cur = (uint8_t)(pos == 0 ? lead : pos == 1 ? ((lead + 2) & 3) : o->soolaaja);
  }
}

// Optional exponential tilt on one other seat's holding (sooli beliefs): each
// assignment is weighted by exp(-lambda * exposure) of that seat's cards
// together with `fixed` (its cards known or already played). Exposure against
// the rest of the deck is a sum over suits of max(0, rank_i - 2i) over the
// seat's ace-low ranks in increasing order, so the weighted count still
// factorises over suits and the draw stays exact.
typedef struct { int j; double lambda; u64 fixed; } Tilt;

// Log weight of splitting a suit's m free cards x / y / z among the others.
static inline double split_term(const Tilt *t, const double *logA, int m, int x, int y, int z) {
  if (!t) return lfact[m] - lfact[x] - lfact[y] - lfact[z];
  int n[3] = {x, y, z}, k = n[t->j], p = n[(t->j + 1) % 3];
  return logA[k] + lfact[m - k] - lfact[p] - lfact[m - k - p];
}

static int suit_exposure_low(unsigned low13) {
  int d = 0, i = 0;
  while (low13) {
    int r = __builtin_ctz(low13);
    low13 &= low13 - 1;
    if (r > 2 * i) d += r - 2 * i;
    i++;
  }
  return d;
}
static inline unsigned suit_low(u64 hand, int v) {
  unsigned m = (unsigned)((hand >> (13 * v)) & 0x1FFFULL);
  return ((m & 0xFFFu) << 1) | (m >> 12);
}
// Tilt weight of giving the seat the subset `sub` (bit i = i-th free card of
// the suit, ascending) of the suit's free cards.
static double tilt_weight(const Tilt *t, int v, const int *cards, int nc, unsigned sub) {
  u64 h = t->fixed;
  for (int i = 0; i < nc; i++) if (sub >> i & 1u) h |= 1ULL << cards[i];
  return exp(-t->lambda * suit_exposure_low(suit_low(h, v)));
}

// The counting tables of count_or_draw depend only on the free cards, the
// three others' voids and the tilt, not on the capacities or the rng, and one
// search draws hundreds of worlds from the same observation. They are kept in
// a small per-thread cache; a hit returns exactly the tables a rebuild would
// compute, so every draw is unchanged.
typedef struct {
  int valid, others[3], voids[3], tilted, tj;
  double lambda;
  u64 free_cards, fixed;
  int size[4], remaining_after[5];
  double logA[4][14];
  double W[5][14][14];
} DpTables;
#define DP_CACHE 8
static __thread DpTables *dp_cache = NULL;
static __thread int dp_next = 0;

static const DpTables *dp_tables(const int others[3], u64 free_cards, const int void_mask[4], const Tilt *tilt) {
  if (!dp_cache) dp_cache = calloc(DP_CACHE, sizeof(DpTables));
  int voids[3];
  for (int j = 0; j < 3; j++) voids[j] = void_mask[others[j]] & 15;
  for (int i = 0; i < DP_CACHE; i++) {
    const DpTables *t = &dp_cache[i];
    if (t->valid && t->free_cards == free_cards && t->tilted == (tilt != NULL) && !memcmp(t->others, others, sizeof t->others) &&
        !memcmp(t->voids, voids, sizeof voids) &&
        (!tilt || (t->tj == tilt->j && t->lambda == tilt->lambda && t->fixed == tilt->fixed)))
      return t;
  }
  DpTables *T = &dp_cache[dp_next];
  dp_next = (dp_next + 1) % DP_CACHE;
  T->valid = 1;
  memcpy(T->others, others, sizeof T->others);
  memcpy(T->voids, voids, sizeof voids);
  T->free_cards = free_cards;
  T->tilted = tilt != NULL;
  T->tj = tilt ? tilt->j : 0;
  T->lambda = tilt ? tilt->lambda : 0.0;
  T->fixed = tilt ? tilt->fixed : 0;
  int *size = T->size;
  for (int v = 0; v < 4; v++) size[v] = __builtin_popcountll(free_cards & SUIT_MASK(v));
  // logA[v][k]: log of the tilt-weighted number of k-subsets of suit v's free
  // cards for the tilted seat (log C(m, k) without a tilt).
  double (*logA)[14] = T->logA;
  int suit_cards[4][13];
  for (int v = 0; v < 4; v++) {
    int nc = 0;
    for (u64 fm = free_cards & SUIT_MASK(v); fm; fm &= fm - 1) suit_cards[v][nc++] = __builtin_ctzll(fm);
    if (!tilt) continue;
    double A[14] = {0};
    for (unsigned sub = 0; sub < (1u << nc); sub++) A[__builtin_popcount(sub)] += tilt_weight(tilt, v, suit_cards[v], nc, sub);
    for (int k = 0; k <= nc; k++) logA[v][k] = log(A[k]);
  }

  // W[v][a][b] = log number of ways to place suits v..3 given remaining
  // capacities a, b for the first two others (the third is implied).
  double (*W)[14][14] = T->W;
  int *remaining_after = T->remaining_after;
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
            double t = split_term(tilt, logA[v], m, x, y, z) + rest;
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
  return T;
}

// Log number of assignments of `free_cards` to the three `others` with exact
// capacities and no card of a void suit, and, if `hands` is given, an exact
// uniform draw of one such assignment (added to hands). -INFINITY if none.
static double count_or_draw(const int others[3], const int cap[3], u64 free_cards, const int void_mask[4],
                            u64 *rng, u64 hands[4], const Tilt *tilt) {
  const DpTables *T = dp_tables(others, free_cards, void_mask, tilt);
  const int *size = T->size, *remaining_after = T->remaining_after;
  const double (*logA)[14] = T->logA;
  const double (*W)[14][14] = T->W;
  if (size[0] + size[1] + size[2] + size[3] != cap[0] + cap[1] + cap[2]) return -INFINITY;
  if (cap[0] > 13 || cap[1] > 13 || W[0][cap[0]][cap[1]] == -INFINITY) return -INFINITY;
  if (!hands) return W[0][cap[0]][cap[1]];

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
        lw[ns] = split_term(tilt, logA[v], m, x, y, z) + rest - W[v][a][b];
        sx[ns] = x; sy[ns] = y; ns++;
      }
    }
    if (!ns) return -INFINITY;
    double r = unit(rng), acc = 0.0;
    int pick = ns - 1;
    for (int i = 0; i < ns; i++) { acc += exp(lw[i]); if (r < acc) { pick = i; break; } }
    int cx = sx[pick], cy = sy[pick];
    int cards[13], nc = 0;
    u64 fm = free_cards & SUIT_MASK(v);
    while (fm) { cards[nc++] = __builtin_ctzll(fm); fm &= fm - 1; }
    if (tilt) {
      // The tilted seat's subset by weight, then the rest uniformly.
      int n3[3] = {cx, cy, m - cx - cy}, k = n3[tilt->j];
      double r2 = unit(rng) * exp(logA[v][k]), acc2 = 0.0;
      unsigned chosen = 0, last = 0;
      for (unsigned sub = 0; sub < (1u << nc); sub++) {
        if (__builtin_popcount(sub) != k) continue;
        last = sub;
        acc2 += tilt_weight(tilt, v, cards, nc, sub);
        if (r2 < acc2) { chosen = sub; break; }
        chosen = last;
      }
      int rest[13], nr = 0;
      for (int i = 0; i < nc; i++) {
        if (chosen >> i & 1u) hands[others[tilt->j]] |= 1ULL << cards[i];
        else rest[nr++] = cards[i];
      }
      for (int i = nr - 1; i > 0; i--) { int j = (int)(splitmix(rng) % (u64)(i + 1)); int t = rest[i]; rest[i] = rest[j]; rest[j] = t; }
      int j1 = (tilt->j + 1) % 3, j2 = (tilt->j + 2) % 3, n1 = n3[j1];
      for (int i = 0; i < nr; i++) hands[others[i < n1 ? j1 : j2]] |= 1ULL << rest[i];
    } else {
      // Deal the suit's free cards: a random permutation split x / y / z.
      for (int i = nc - 1; i > 0; i--) { int j = (int)(splitmix(rng) % (u64)(i + 1)); int t = cards[i]; cards[i] = cards[j]; cards[j] = t; }
      for (int i = 0; i < nc; i++) {
        int who = i < cx ? 0 : (i < cx + cy ? 1 : 2);
        hands[others[who]] |= 1ULL << cards[i];
      }
    }
    a -= cx;
    b -= cy;
  }
  return W[0][cap[0]][cap[1]];
}

// Capacities of the others and free cards given the known placements.
static int setup(const TcObs *o, const int others[3], const int hand_size[4], const u64 known[4], u64 played_all,
                 int cap[3], u64 *free_cards) {
  u64 known_all = known[0] | known[1] | known[2] | known[3];
  *free_cards = FULL_DECK & ~o->hand & ~played_all & ~known_all;
  for (int j = 0; j < 3; j++) {
    int s = others[j];
    cap[j] = hand_size[s] - __builtin_popcountll(known[s]);
    if (cap[j] < 0) return -1;
  }
  return 0;
}

static int sample_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, const int played_by[4], const int void_mask[4],
                        u64 played_all, const int others[3]);

#include "showing_constraints.h"

// B0-S1 fix: honour the showing-fallback restrictions when drawing worlds.
// Off by default until its strength screen (live search unchanged); the
// self-play labellers turn it on.
static int showing_fix = 0;
void tc_set_showing_fix(int on) { showing_fix = on; }

// Returns 0 on success, -1 if the constraints admit no world.
int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out) {
  init_lfact();
  int played_by[4], void_mask[4];
  u64 played_all;
  public_state(o, out, played_by, void_mask, &played_all);
  const int me = o->seat;
  int others[3], k = 0;
  for (int s = 0; s < 4; s++) if (s != me) others[k++] = s;
  if (o->soolaaja >= 0 && (o->phase == TC_PH_SOOLI_RETURN || o->trick_size == 3))
    return sample_sooli(o, rng, out, played_by, void_mask, played_all, others);
  u64 known[4] = {0, 0, 0, 0};
  for (int i = 0; i < (TC_LOCKED(o) ? 0 : o->n_shows); i++) {
    int c = o->show_card[i], s = o->show_seat[i];
    if (s != me && !(played_all >> c & 1ULL)) known[s] |= 1ULL << c;
  }
  int hand_size[4], cap[3];
  for (int s = 0; s < 4; s++) hand_size[s] = 13 - played_by[s];
  u64 free_cards;
  if (setup(o, others, hand_size, known, played_all, cap, &free_cards) != 0) return -1;
  u64 hands[4] = {0, 0, 0, 0};
  hands[me] = o->hand;
  for (int s = 0; s < 4; s++) hands[s] |= known[s];
  u64 forbidden[4] = {0, 0, 0, 0};
  if (showing_fix && showing_forbidden(o, forbidden)) {  // fallback shows restrict the original hands (B0-S1)
    u64 original[4];
    for (int s = 0; s < 4; s++) original[s] = hands[s];
    for (int i = 0; i < o->n_played; i++) original[o->play_seat[i]] |= 1ULL << o->play_card[i];
    for (int s = 0; s < 4; s++) {
      if (original[s] & forbidden[s]) return -1;
      for (int suit = 0; suit < 4; suit++) if (void_mask[s] >> suit & 1) forbidden[s] |= SUIT_MASK(suit);
    }
    if (tc_research_draw_constrained(others, cap, free_cards, forbidden, rng, hands) == 0) return -1;
  } else if (count_or_draw(others, cap, free_cards, void_mask, rng, hands, NULL) == -INFINITY) return -1;
  for (int s = 0; s < 4; s++) out->hand[s] = hands[s];
  if (TC_LOCKED(o)) {
    // Locked bids: the earlier bids are unseen, and all were NOLO (a RAMI
    // would have ended showing). Each earlier seat bids a random legal NOLO
    // card of its sampled hand, as players pick bid cards (owner: "roughly
    // at random"). Only hands matter for the rest of the deal.
    for (int i = 0; i < o->n_shows; i++) {
      int s = (o->dealer + 1 + i) & 3;
      u64 valid = tc_valid_show_cards(hands[s], TC_NOLO);
      int n = __builtin_popcountll(valid), pick = (int)(splitmix(rng) % (u64)(n ? n : 1));
      int c = -1;
      for (u64 m = valid; m; m &= m - 1) { if (pick-- == 0) { c = __builtin_ctzll(m); break; } }
      if (c < 0) return -1;
      out->show_seat[i] = (uint8_t)s;
      out->show_card[i] = (uint8_t)c;
      out->show_contract[i] = TC_NOLO;
      out->show_verbal[i] = (uint8_t)tc_verbal_required(c, TC_NOLO);
    }
  }
  return 0;
}

// Exposure tilt for sooli worlds (tc_sample_world_tilted); 0 = none.
static __thread double sooli_tilt = 0.0;

int tc_sample_world_tilted(const TcObs *o, uint64_t *rng, TcDeal *out, double lambda) {
  sooli_tilt = lambda;
  int r = tc_sample_world(o, rng, out);
  sooli_tilt = 0.0;
  return r;
}

// Worlds once a sooli exchange has begun (project_target_v2). Hand sizes follow
// the exchange (during the return the soolaaja holds 12 cards and the partner
// 14). The soolaaja and the partner know both exchanged cards, so every shown
// card's holder is known to them. The RAMI pair does not: a card shown by the
// soolaaja or the partner and not yet played is with one of the two, and the
// cases are weighted by their numbers of worlds times the number of exchanges
// (given card, returned card) that lead to them, i.e. a uniform prior over the
// exchange. A RAMI player is never asked during the return, so that case is
// unsupported (-1).
static int sample_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, const int played_by[4], const int void_mask[4],
                        u64 played_all, const int others[3]) {
  const int me = o->seat, S = o->soolaaja, P = (S + 2) & 3;
  const int returning = o->phase == TC_PH_SOOLI_RETURN;
  const int knows = me == S || me == P;
  if (!knows && returning) return -1;
  int hand_size[4];
  for (int s = 0; s < 4; s++) hand_size[s] = 13 - played_by[s];
  if (returning) { hand_size[S]--; hand_size[P]++; }
  const int g = o->known_given, r = o->known_returned;
  u64 known[4] = {0, 0, 0, 0};
  int unsure[2], n_unsure = 0, x_card = -1, y_card = -1;
  for (int i = 0; i < o->n_shows; i++) {
    int c = o->show_card[i], s = o->show_seat[i];
    if (s == S) x_card = c;
    if (s == P) y_card = c;
    if (played_all >> c & 1ULL) continue;
    int loc = s;
    if (knows) loc = c == g ? P : (c == r ? S : s);
    else if (s == S || s == P) { unsure[n_unsure++] = c; continue; }
    if (loc != me) known[loc] |= 1ULL << c;
  }
  if (knows) {
    if (g >= 0 && P != me && !(played_all >> g & 1ULL)) known[P] |= 1ULL << g;
    if (r >= 0 && S != me && !(played_all >> r & 1ULL)) known[S] |= 1ULL << r;
  }
  for (int s = 0; s < 4; s++) known[s] &= ~o->hand;
  u64 base[4] = {0, 0, 0, 0};
  base[me] = o->hand;
  for (int s = 0; s < 4; s++) base[s] |= known[s];
  // The tilted seat is the soolaaja; its fixed cards are those it is known to
  // hold, those it has played and, during the return, the card it gave.
  u64 s_played = 0;
  for (int i = 0; i < o->n_played; i++) if (o->play_seat[i] == S) s_played |= 1ULL << o->play_card[i];
  Tilt tilt = {0, sooli_tilt, 0};
  int tilted = sooli_tilt > 0.0 && me != S;
  for (int j = 0; j < 3; j++) if (others[j] == S) tilt.j = j;
  if (returning && g >= 0) s_played |= 1ULL << g;
  if (knows || n_unsure == 0) {
    int cap[3];
    u64 free_cards;
    if (setup(o, others, hand_size, known, played_all, cap, &free_cards) != 0) return -1;
    tilt.fixed = known[S] | s_played;
    if (count_or_draw(others, cap, free_cards, void_mask, rng, base, tilted ? &tilt : NULL) == -INFINITY) return -1;
    for (int s = 0; s < 4; s++) out->hand[s] = base[s];
    return 0;
  }
  // RAMI observer: every placement of the unsure cards with S or P.
  double lw[4];
  u64 case_known[4][4];
  int n_cases = 1 << n_unsure;
  double best = -INFINITY;
  for (int m = 0; m < n_cases; m++) {
    u64 *kk = case_known[m];
    for (int s = 0; s < 4; s++) kk[s] = known[s];
    int ok = 1;
    for (int j = 0; j < n_unsure; j++) {
      int c = unsure[j], loc = (m >> j & 1) ? P : S;
      if (loc == S && (void_mask[S] >> (c / 13) & 1)) ok = 0;
      kk[loc] |= 1ULL << c;
    }
    int cap[3];
    u64 free_cards;
    lw[m] = -INFINITY;
    if (!ok || setup(o, others, hand_size, kk, played_all, cap, &free_cards) != 0) continue;
    tilt.fixed = kk[S] | s_played;
    double w = count_or_draw(others, cap, free_cards, void_mask, NULL, NULL, tilted ? &tilt : NULL);
    if (w == -INFINITY) continue;
    // Exchanges (given, returned) leading to this placement: the soolaaja's
    // post-exchange cards S' and the partner's P'.
    int x_in_s = 0, y_in_s = 0;
    if (x_card >= 0) x_in_s = (kk[S] >> x_card & 1ULL) || (played_all >> x_card & 1ULL);
    if (y_card >= 0) y_in_s = (kk[S] >> y_card & 1ULL) || (played_all >> y_card & 1ULL);
    int n_r = y_in_s ? 1 : 13 - (x_card >= 0 && x_in_s);
    int n_g = (x_card >= 0 && !x_in_s) ? 1 : 13 - (y_card >= 0 && !y_in_s);
    lw[m] = w + log((double)n_r * n_g);
    if (lw[m] > best) best = lw[m];
  }
  if (best == -INFINITY) return -1;
  double total = 0.0;
  for (int m = 0; m < n_cases; m++) total += lw[m] == -INFINITY ? 0.0 : exp(lw[m] - best);
  double u = unit(rng) * total, acc = 0.0;
  int pick = -1;
  for (int m = 0; m < n_cases; m++) {
    if (lw[m] == -INFINITY) continue;
    pick = m;
    acc += exp(lw[m] - best);
    if (u < acc) break;
  }
  u64 hands[4] = {0, 0, 0, 0};
  hands[me] = o->hand;
  for (int s = 0; s < 4; s++) hands[s] |= case_known[pick][s];
  int cap[3];
  u64 free_cards;
  setup(o, others, hand_size, case_known[pick], played_all, cap, &free_cards);
  tilt.fixed = case_known[pick][S] | s_played;
  if (count_or_draw(others, cap, free_cards, void_mask, rng, hands, tilted ? &tilt : NULL) == -INFINITY) return -1;
  for (int s = 0; s < 4; s++) out->hand[s] = hands[s];
  return 0;
}

// Replays a full world from the start of its deal and emits, for every past
// decision made by a seat in `seat_mask` (bit s = seat s), that seat's encoded
// observation at the time, its legal-action mask and the action it took.
// `world` is a full state at the current decision (hands = current holdings);
// initial hands are recovered by adding back each seat's played cards.
// Forced decisions (one legal action) carry no information and are skipped.
// Returns the number of rows written (at most max_rows).
int tc_history_rows(const TcDeal *world, int seat_mask, int encoder, int max_rows,
                    uint8_t *feat, uint8_t *mask, int32_t *action) {
  if (world->n_decisions || world->soolaaja >= 0) return -1;  // sooli histories are not replayed here
  uint64_t init[4];
  for (int s = 0; s < 4; s++) init[s] = world->hand[s];
  for (int i = 0; i < world->n_played; i++) init[world->play_seat[i]] |= 1ULL << world->play_card[i];
  TcDeal d;
  tc_deal_init(&d, init, world->dealer, world->score[0], world->score[1]);
  int dim = tc_feature_dim_v(encoder), rows = 0, acts[TC_NUM_ACTIONS];
  int n_actions = world->n_shows + world->n_played;
  TcObs o;
  for (int t = 0; t < n_actions && rows < max_rows; t++) {
    int a = t < world->n_shows
      ? 52 + 52 * world->show_contract[t] + world->show_card[t]
      : world->play_card[t - world->n_shows];
    int seat = d.cur;
    if (seat_mask >> seat & 1) {
      int k = tc_legal(&d, acts);
      if (k > 1) {
        tc_observe(&d, seat, &o);
        tc_encode_v(&o, feat + (size_t)rows * dim, encoder);
        uint8_t *mk = mask + (size_t)rows * TC_NUM_ACTIONS;
        memset(mk, 0, TC_NUM_ACTIONS);
        for (int j = 0; j < k; j++) mk[acts[j]] = 1;
        action[rows++] = a;
      }
    }
    if (tc_apply(&d, a) != 0) return -1;  // world inconsistent with history
  }
  return rows;
}

// Exact sampling from a product-form belief restricted to the hard-feasible set:
// P(world) proportional to prod over free cards c of w[c][owner_rel(c) - 1],
// where w is a 52x3 table over the observer's relative seats 1..3 (callers pass
// tempered probabilities). Voids force w = 0; shown-but-unplayed cards stay with
// their shower. A DP over the free cards with state = remaining capacities of
// the first two other seats (the third is implied) makes the draw exact.
int tc_sample_world_weighted(const TcObs *o, const float *wtab, uint64_t *rng, TcDeal *out) {
  if (o->soolaaja >= 0 && (o->phase == TC_PH_SOOLI_RETURN || o->trick_size == 3)) return -1;  // v1 beliefs only
  int played_by[4], void_mask[4];
  u64 played_all;
  public_state(o, out, played_by, void_mask, &played_all);
  const int me = o->seat;
  int others[3];
  for (int j = 0; j < 3; j++) others[j] = (me + 1 + j) & 3;
  u64 known[4] = {0, 0, 0, 0};
  if (TC_LOCKED(o)) return -1;  // v1 beliefs only
  for (int i = 0; i < o->n_shows; i++) {
    int c = o->show_card[i], s = o->show_seat[i];
    if (s != me && !(played_all >> c & 1ULL)) known[s] |= 1ULL << c;
  }
  u64 free_cards = FULL_DECK & ~o->hand & ~played_all & ~(known[0] | known[1] | known[2] | known[3]);
  int cap[3];
  for (int j = 0; j < 3; j++) {
    cap[j] = 13 - played_by[others[j]] - __builtin_popcountll(known[others[j]]);
    if (cap[j] < 0) return -1;
  }
  int cards[52], m = 0;
  u64 fm = free_cards;
  while (fm) { cards[m++] = __builtin_ctzll(fm); fm &= fm - 1; }
  if (m != cap[0] + cap[1] + cap[2]) return -1;
  double w[52][3];
  for (int i = 0; i < m; i++) {
    int c = cards[i];
    for (int j = 0; j < 3; j++) {
      double v = wtab[3 * c + j];
      w[i][j] = (void_mask[others[j]] >> (c / 13) & 1) ? 0.0 : (v > 1e-12 ? v : 1e-12);
    }
  }
  // Z[i][a][b]: weight of placing cards i..m-1 with capacities a, b and
  // (m - i - a - b) for the three others. Each layer is rescaled by its max.
  static __thread double Z[53][14][14];
  for (int a = 0; a < 14; a++) for (int b = 0; b < 14; b++) Z[m][a][b] = (a == 0 && b == 0) ? 1.0 : 0.0;
  for (int i = m - 1; i >= 0; i--) {
    int rem = m - i;
    double mx = 0.0;
    for (int a = 0; a < 14; a++) {
      for (int b = 0; b < 14; b++) {
        int c3 = rem - a - b;
        double z = 0.0;
        if (c3 >= 0 && c3 <= 13) {
          if (a > 0) z += w[i][0] * Z[i + 1][a - 1][b];
          if (b > 0) z += w[i][1] * Z[i + 1][a][b - 1];
          if (c3 > 0) z += w[i][2] * Z[i + 1][a][b];
        }
        Z[i][a][b] = z;
        if (z > mx) mx = z;
      }
    }
    if (mx <= 0.0) return -1;
    for (int a = 0; a < 14; a++) for (int b = 0; b < 14; b++) Z[i][a][b] /= mx;
  }
  if (Z[0][cap[0]][cap[1]] <= 0.0) return -1;
  u64 hands[4] = {0, 0, 0, 0};
  hands[me] = o->hand;
  for (int s = 0; s < 4; s++) hands[s] |= known[s];
  int a = cap[0], b = cap[1];
  for (int i = 0; i < m; i++) {
    int c3 = (m - i) - a - b;
    double p0 = a > 0 ? w[i][0] * Z[i + 1][a - 1][b] : 0.0;
    double p1 = b > 0 ? w[i][1] * Z[i + 1][a][b - 1] : 0.0;
    double p2 = c3 > 0 ? w[i][2] * Z[i + 1][a][b] : 0.0;
    double r = unit(rng) * (p0 + p1 + p2);
    int j = r < p0 ? 0 : (r < p0 + p1 ? 1 : 2);
    if (j == 0 && p0 == 0.0) j = p1 > 0 ? 1 : 2;
    if (j == 1 && p1 == 0.0) j = p2 > 0 ? 2 : 0;
    if (j == 2 && p2 == 0.0) j = p0 > 0 ? 0 : 1;
    hands[others[j]] |= 1ULL << cards[i];
    if (j == 0) a--; else if (j == 1) b--;
  }
  for (int s = 0; s < 4; s++) out->hand[s] = hands[s];
  return 0;
}
