// Perfect-information (double-dummy) solver for the rest of a deal.
//
// Both contracts are zero-sum in the trick split and every utility (deal
// points, match equity) is monotone in it, so one minimax on team-0 tricks
// with the contract's polarity is exact for any of them: RAMI, both teams take
// tricks; NOLO, both avoid them. Alpha-beta over trick boundaries with a
// transposition table keyed on rank-canonical hands (only the relative order
// of remaining cards matters), plus rank-equivalence move pruning.
//
// Practical for the last ~7 tricks; full 13-trick deals need more (see
// docs/STATUS.md). Used by search as an exact evaluator of late positions.
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;
#define SUIT_MASK(s) (0x1FFFULL << ((s) * 13))

typedef struct { u64 h[4]; uint32_t gen; uint8_t leader; int8_t lo, hi; } TTE;
#define TTBITS 18
// Per-thread state, so solves can run in parallel (tc_env_dd_finish). Entries
// hold exact bounds on a pure function of (canonical position, leader,
// polarity), so they stay valid across solves and are never cleared; the
// polarity is part of the key (the high bit of `leader`).
static __thread TTE *tt_tls = NULL;
// One solve's state, read through a pointer: thread-local variables in a
// dylib cost a function call per access (_tlv_get_addr), in every node.
typedef struct { TTE *tt; uint32_t gen; int nolo; } Ctx;

typedef struct { u64 h[4]; int leader, n, card[4]; } Pos;

static inline int rank_of(int c) { return c % 13; }
static inline int suit_of(int c) { return c / 13; }
static inline int is_max(const Ctx *x, int seat) { return ((seat & 1) == 0) ^ x->nolo; }
static inline u64 mix(u64 x) { x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL; x ^= x >> 33; return x; }

// Each remaining card moved down to its rank among the suit's remaining cards
// (walks the live cards only; the same result as probing all 13 x 4 bits).
static void canon(const Pos *p, u64 *c) {
  c[0] = c[1] = c[2] = c[3] = 0;
  const u64 live = p->h[0] | p->h[1] | p->h[2] | p->h[3];
  for (int s = 0; s < 4; s++) {
    int j = s * 13;
    for (u64 m = live & SUIT_MASK(s); m; m &= m - 1, j++) {
      const u64 b = m & -m;
      const int q = (p->h[0] & b) ? 0 : (p->h[1] & b) ? 1 : (p->h[2] & b) ? 2 : 3;
      c[q] |= 1ULL << j;
    }
  }
}

static int gen_moves(const Pos *p, int seat, int *mv) {
  u64 hand = p->h[seat], legal = hand;
  if (p->n > 0) { u64 f = hand & SUIT_MASK(suit_of(p->card[0])); if (f) legal = f; }
  u64 live = p->h[0] | p->h[1] | p->h[2] | p->h[3];
  for (int i = 0; i < p->n; i++) live |= 1ULL << p->card[i];
  // The highest card of each run of own cards adjacent among live cards: a
  // card whose next higher live card of its suit is not the mover's. Suits in
  // increasing order, cards in decreasing order (the order order_moves' stable
  // sort starts from).
  int k = 0;
  for (int s = 0; s < 4; s++) {
    const u64 sm = SUIT_MASK(s);
    for (u64 own = legal & sm; own; ) {
      const int c = 63 - __builtin_clzll(own);
      own &= ~(1ULL << c);
      const u64 above = live & sm & ~((1ULL << c) - 1) & ~(1ULL << c);
      if (!above || !(hand >> __builtin_ctzll(above) & 1ULL)) mv[k++] = c;
    }
  }
  return k;
}

static void order_moves(const Ctx *x, const Pos *p, int seat, int *mv, int k) {
  const int nolo = x->nolo;
  int sc[13], want = !nolo, cur_best = -1, cur_seat = -1, ls = -1;
  if (p->n) {
    ls = suit_of(p->card[0]); int b = 0;
    for (int i = 1; i < p->n; i++) if (suit_of(p->card[i]) == ls && rank_of(p->card[i]) > rank_of(p->card[b])) b = i;
    cur_best = rank_of(p->card[b]); cur_seat = (p->leader + b) & 3;
  }
  for (int i = 0; i < k; i++) {
    int c = mv[i], r = rank_of(c), s = suit_of(c), v;
    if (!p->n) v = want ? r : -r;
    else if (s != ls) v = nolo ? 20 + r : 20 - r;
    else {
      int beats = r > cur_best, partner_winning = ((cur_seat ^ seat) & 1) == 0;
      if (want) v = (beats && !partner_winning) ? 40 - r : -r;
      else v = beats ? -r : 40 + r;
    }
    sc[i] = v;
  }
  for (int i = 1; i < k; i++) { int c = mv[i], v = sc[i], j = i - 1; while (j >= 0 && sc[j] < v) { mv[j + 1] = mv[j]; sc[j + 1] = sc[j]; j--; } mv[j + 1] = c; sc[j + 1] = v; }
}

static int trick_winner(const Pos *p) {
  int ls = suit_of(p->card[0]), best = 0;
  for (int i = 1; i < 4; i++) if (suit_of(p->card[i]) == ls && rank_of(p->card[i]) > rank_of(p->card[best])) best = i;
  return (p->leader + best) & 3;
}

// Team-0 tricks from here on, fail-hard within [alpha, beta].
static int search(const Ctx *x, Pos *p, int alpha, int beta) {
  int remaining = __builtin_popcountll(p->h[0] | p->h[1] | p->h[2] | p->h[3]) / 4 + (p->n ? 1 : 0);
  TTE *e = NULL; u64 ck[4];
  if (p->n == 0) {
    if (remaining == 0) return 0;
    if (alpha >= remaining) return remaining;
    if (beta <= 0) return 0;
    if (remaining == 1) {  // one card each: the last trick is forced
      const int L = p->leader;
      int best = __builtin_ctzll(p->h[L]), w = L;
      for (int k = 1; k < 4; k++) {
        const int s = (L + k) & 3, c = __builtin_ctzll(p->h[s]);
        if (suit_of(c) == suit_of(best) && rank_of(c) > rank_of(best)) { best = c; w = s; }
      }
      return (w & 1) == 0;
    }
    canon(p, ck);
    const uint8_t lk = (uint8_t)(p->leader | (x->nolo << 7));
    TTE *tt = x->tt;
    const uint32_t gen = x->gen;
    e = &tt[mix(ck[0] * 3 + mix(ck[1] + 7) + mix(ck[2] * 11 + 1) + (u64)lk * 0x9E3779B97F4A7C15ULL) & ((1ULL << TTBITS) - 1)];
    if (e->gen == gen && e->leader == lk && !memcmp(e->h, ck, sizeof ck)) {
      if (e->lo >= beta) return e->lo;
      if (e->hi <= alpha) return e->hi;
      if (e->lo == e->hi) return e->lo;
      if (e->lo > alpha) alpha = e->lo;
      if (e->hi < beta) beta = e->hi;
    }
  }
  int a0 = alpha, b0 = beta, seat = (p->leader + p->n) & 3, mv[13];
  int k = gen_moves(p, seat, mv);
  order_moves(x, p, seat, mv, k);
  int mx = is_max(x, seat), best = mx ? -1 : 99;
  for (int i = 0; i < k; i++) {
    Pos q = *p;
    q.h[seat] &= ~(1ULL << mv[i]);
    q.card[q.n++] = mv[i];
    int v;
    if (q.n == 4) {
      int w = trick_winner(&q), t = (w & 1) == 0;
      q.leader = w; q.n = 0;
      v = t + search(x, &q, alpha - t, beta - t);
    } else v = search(x, &q, alpha, beta);
    if (mx) { if (v > best) best = v; if (best > alpha) alpha = best; }
    else { if (v < best) best = v; if (best < beta) beta = best; }
    if (alpha >= beta) break;
  }
  if (e) {
    const uint8_t lk = (uint8_t)(p->leader | (x->nolo << 7));
    if (!(e->gen == x->gen && e->leader == lk && !memcmp(e->h, ck, sizeof ck))) {
      memcpy(e->h, ck, sizeof ck); e->leader = lk; e->gen = x->gen; e->lo = 0; e->hi = 13;
    }
    if (best <= a0) { if (best < e->hi) e->hi = (int8_t)best; }
    else if (best >= b0) { if (best > e->lo) e->lo = (int8_t)best; }
    else e->lo = e->hi = (int8_t)best;
  }
  return best;
}

static void to_pos(const TcDeal *d, Pos *p) {
  memset(p, 0, sizeof *p);
  for (int s = 0; s < 4; s++) p->h[s] = d->hand[s];
  int pos = d->n_played & 3;
  p->n = pos;
  if (pos) {
    int start = d->n_played - pos;
    p->leader = d->play_seat[start];
    for (int i = 0; i < pos; i++) p->card[i] = d->play_card[start + i];
  } else p->leader = d->cur;
}

// Final team-0 tricks for the whole deal under perfect-information optimal play
// from this trick-play position.
int tc_dd_team0_tricks(const TcDeal *d) {
  if (!tt_tls) tt_tls = calloc(1ULL << TTBITS, sizeof(TTE));
  const Ctx x = {tt_tls, 1, d->contract == TC_NOLO};
  Pos p;
  to_pos(d, &p);
  int remaining = 13 - (d->n_played >> 2);
  int lo = 0, hi = remaining;
  while (lo < hi) {  // null-window probes: binary search on the target
    int m = (lo + hi + 1) / 2;
    Pos q = p;
    if (search(&x, &q, m - 1, m) >= m) lo = m; else hi = m - 1;
  }
  return d->team_tricks[0] + lo;
}

// Evaluator-private utility query. Exact-trick callers keep the old API.
float tc_dd_reward_bucket(const TcDeal *d, const float payoff[14]) {
  int base = d->team_tricks[0], remaining = 13 - (d->n_played >> 2);
  int cuts[13], n = 0;
  for (int i = 1; i <= remaining; i++)
    if (payoff[base+i] != payoff[base+i-1]) cuts[n++] = i;
  if (!n) return payoff[base];
  if (!tt_tls) tt_tls = calloc(1ULL << TTBITS, sizeof(TTE));
  const Ctx x = {tt_tls, 1, d->contract == TC_NOLO};
  Pos p; to_pos(d, &p);
  int lo = 0, hi = n;
  while (lo < hi) {
    int mid = (lo + hi) / 2, target = cuts[mid];
    Pos q = p;
    if (search(&x, &q, target-1, target) >= target) lo = mid+1;
    else hi = mid;
  }
  return payoff[base + (lo ? cuts[lo-1] : 0)];
}
