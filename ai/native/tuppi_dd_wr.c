// Double-dummy solver with winning-rank partitions (research, 2026-10-20).
//
// The same answers as tuppi_dd.c and tuppi_dd_full.c, for both contracts,
// using the ideas that make DDS (Haglund and Hein's bridge solver,
// Apache-2.0; only its published techniques are reused here, not its code)
// fast:
//   - null-window searches driven towards the value (MTD(f));
//   - winning ranks: every search result carries the set of cards whose ranks
//     decided a trick in the part of the tree that proved it (the winner of
//     each trick in which another card of the led suit was played, with the
//     run of the winner's own cards just below it). A position's value then
//     holds for every position with the same suit lengths in each hand and
//     the same owners of each suit's cards from the top down to its lowest
//     winning rank; lower cards matter only by their number;
//   - so the transposition table stores those partitions, keyed by the
//     leader and the 16 hand-suit lengths, and one entry answers for many
//     positions;
//   - after a card has been tried, the mover's lower cards of that suit below
//     every winning rank found so far are equivalent to it and are skipped;
//   - in RAMI, the leader's quick tricks (top cards it can cash) bound the
//     result early.
// Trick-taking mechanics are the same for both contracts, so the partitions
// hold for NOLO too (which DDS does not solve): only who wants the trick
// changes. tests/native/wr_bench.c checks the answers against tuppi_dd_full.c.
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"
#include "tuppi_parallel.h"

typedef uint64_t u64;
#define SUIT_MASK(s) (0x1FFFULL << ((s) * 13))

// A stored partition: lens (4 bits per hand-suit length), the leader and
// contract (lk), m (4 bits per suit: how many of its top remaining cards are
// fixed) and own[s] (their owners, 2 bits each from the highest). Entries
// are found by an exact hash of all of these; for each (lens, lk) a short
// list remembers the m vectors stored most recently, which a lookup tries.
typedef struct {
  u64 lens;
  uint32_t own[4];
  uint16_t m;
  uint8_t lk, depth;
  int8_t lo, hi;
  uint8_t move, used;
} Entry;
#define WAYS 4
typedef struct { Entry e[WAYS]; } Bucket;
#define MVECS 32
typedef struct { u64 lens; uint8_t lk, n, next, used; uint16_t m[MVECS]; } MList;

static int table_bits = 20;
static __thread Bucket *table_tls = NULL;
static __thread MList *mlist_tls = NULL;
static __thread u64 nodes_tls;

typedef struct { Bucket *tt; MList *ml; int nolo; } Ctx;
// lens (the hand-suit lengths) and own (owners() of each suit) are kept up
// to date as cards are played.
typedef struct { u64 h[4], lens; uint32_t own[4]; int leader, n, card[4]; } Pos;

static inline int rank_of(int c) { return c % 13; }
static inline int suit_of(int c) { return c / 13; }
static inline u64 mix(u64 x) { x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL; x ^= x >> 33; return x; }

static inline u64 live_of(const Pos *p) { return p->h[0] | p->h[1] | p->h[2] | p->h[3]; }

static inline Bucket *bucket_of(const Ctx *x, u64 key, uint8_t lk, uint16_t m, const uint32_t own[4]) {
  const u64 h = mix(key ^ ((u64)lk << 56) ^ mix(((u64)m << 32) ^ own[0] ^ ((u64)own[1] << 26)) ^ mix(own[2] ^ ((u64)own[3] << 26) ^ 0x51ED));
  return &x->tt[h & ((1ULL << table_bits) - 1)];
}
static inline MList *mlist_of(const Ctx *x, u64 key, uint8_t lk) {
  return &x->ml[mix(key ^ ((u64)lk << 56) ^ 0x9E3779B97F4A7C15ULL) & ((1ULL << (table_bits - 2)) - 1)];
}
static inline void mask_owners(const uint32_t own[4], uint16_t m, uint32_t out[4]) {
  for (int s = 0; s < 4; s++) out[s] = own[s] & ((1u << (2 * ((m >> (4 * s)) & 15))) - 1);
}

static u64 lens_key(const Pos *p) {
  u64 k = 0;
  for (int h = 0; h < 4; h++)
    for (int s = 0; s < 4; s++) k |= (u64)__builtin_popcountll(p->h[h] & SUIT_MASK(s)) << (4 * (4 * h + s));
  return k;
}

// Owners of suit s's remaining cards from the highest, 2 bits each.
static uint32_t owners(const Pos *p, int s, u64 live) {
  uint32_t code = 0; int i = 0;
  for (u64 m = live & SUIT_MASK(s); m; i++) {
    const int c = 63 - __builtin_clzll(m);
    m &= ~(1ULL << c);
    const uint32_t q = (p->h[0] >> c & 1) ? 0 : (p->h[1] >> c & 1) ? 1 : (p->h[2] >> c & 1) ? 2 : 3;
    code |= q << (2 * i);
  }
  return code;
}

// The top `m` remaining cards of suit s.
static u64 top_cards(u64 live, int s, int m) {
  u64 out = 0, l = live & SUIT_MASK(s);
  for (int i = 0; i < m && l; i++) { const int c = 63 - __builtin_clzll(l); out |= 1ULL << c; l &= ~(1ULL << c); }
  return out;
}

// For each suit, how many remaining cards lie at or above its lowest winning rank.
static uint16_t partition_of(u64 live, u64 wr) {
  uint16_t m = 0;
  for (int s = 0; s < 4; s++) {
    const u64 w = wr & SUIT_MASK(s);
    if (!w) continue;
    const int low = __builtin_ctzll(w);
    m |= (uint16_t)(__builtin_popcountll(live & SUIT_MASK(s) & ~((1ULL << low) - 1)) << (4 * s));
  }
  return m;
}

static int gen_moves(const Pos *p, int seat, int *mv) {
  u64 hand = p->h[seat], legal = hand;
  if (p->n > 0) { u64 f = hand & SUIT_MASK(suit_of(p->card[0])); if (f) legal = f; }
  u64 live = live_of(p);
  for (int i = 0; i < p->n; i++) live |= 1ULL << p->card[i];
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

// NOLO: both sides avoid tricks. Lead a card that other hands have few
// cards below (someone else will have to win it); follow with the highest
// card that stays below the trick's winner, or, forced to win, the lowest
// card that may still be overtaken (the highest when last to play); discard
// high cards.
static int nolo_score(const Pos *p, int seat, int c, int ls, int cur_best, int cur_seat) {
  const int r = rank_of(c), s = suit_of(c);
  if (!p->n) {
    const u64 others = (live_of(p) & ~p->h[seat]) & SUIT_MASK(s);
    const u64 below = others & ((1ULL << c) - 1);
    if (!others) return -100 + r;  // nobody can follow: the leader takes it
    return -4 * __builtin_popcountll(below) - r;
  }
  if (s != ls) return 60 + r;
  if (r < cur_best) return 40 + r;
  const int partner_winning = ((cur_seat ^ seat) & 1) == 0;
  if (p->n == 3 || partner_winning) return 20 + r;  // the trick is ours anyway: shed the highest
  return 20 - r;
}

static void order_moves(const Ctx *x, const Pos *p, int seat, int *mv, int k, int first) {
  const int nolo = x->nolo;
  int sc[13], want = !nolo, cur_best = -1, cur_seat = -1, ls = -1;
  if (p->n) {
    ls = suit_of(p->card[0]); int b = 0;
    for (int i = 1; i < p->n; i++) if (suit_of(p->card[i]) == ls && rank_of(p->card[i]) > rank_of(p->card[b])) b = i;
    cur_best = rank_of(p->card[b]); cur_seat = (p->leader + b) & 3;
  }
  for (int i = 0; i < k; i++) {
    int c = mv[i], r = rank_of(c), s = suit_of(c), v;
    if (c == first) v = 1000;
    else if (nolo) v = nolo_score(p, seat, c, ls, cur_best, cur_seat);
    else if (!p->n) v = want ? r : -r;
    else if (s != ls) v = 20 - r;
    else {
      int beats = r > cur_best, partner_winning = ((cur_seat ^ seat) & 1) == 0;
      v = (beats && !partner_winning) ? 40 - r : -r;
    }
    sc[i] = v;
  }
  for (int i = 1; i < k; i++) { int c = mv[i], v = sc[i], j = i - 1; while (j >= 0 && sc[j] < v) { mv[j + 1] = mv[j]; sc[j + 1] = sc[j]; j--; } mv[j + 1] = c; sc[j + 1] = v; }
}

static uint8_t move_code(u64 live, int card) {
  const int s = suit_of(card);
  return (uint8_t)(s * 16 + __builtin_popcountll(live & SUIT_MASK(s) & ((1ULL << card) - 1)) + 1);
}
static int move_card(u64 live, uint8_t code) {
  if (!code) return -1;
  const int s = (code - 1) / 16, idx = (code - 1) % 16;
  u64 m = live & SUIT_MASK(s);
  for (int i = 0; i < idx && m; i++) m &= m - 1;
  return m ? __builtin_ctzll(m) : -1;
}

// Tricks seat `who` can cash in a row with the runs of top cards it holds.
static int top_runs(const Pos *p, int who, u64 live, u64 *cards) {
  int q = 0; u64 w = 0;
  for (int s = 0; s < 4; s++) {
    u64 m = live & SUIT_MASK(s);
    while (m) {
      const int c = 63 - __builtin_clzll(m);
      if (!(p->h[who] >> c & 1ULL)) break;
      q++; w |= 1ULL << c; m &= ~(1ULL << c);
    }
  }
  *cards = w;
  return q;
}

// RAMI: tricks the side on lead can take at once: the leader cashing its own
// top runs, or, when the leader can lead a suit whose top card its partner
// holds, the partner cashing all of its top runs. *cards receives the cards
// whose ranks the count relies on.
static int quick_tricks(const Pos *p, u64 live, u64 *cards) {
  const int L = p->leader, P = (L + 2) & 3;
  u64 wl, wp;
  const int ql = top_runs(p, L, live, &wl), qp = top_runs(p, P, live, &wp);
  if (qp > ql)
    for (int s = 0; s < 4; s++)
      if ((wp & SUIT_MASK(s)) && (p->h[L] & SUIT_MASK(s))) { *cards = wp; return qp; }
  *cards = wl;
  return ql;
}

// Team-0 tricks from here on (counting the current trick), fail-soft: a
// result <= alpha is an upper bound, >= beta a lower bound, otherwise exact.
// *wr receives the winning ranks the result relies on.
static int ab(const Ctx *x, Pos *p, int alpha, int beta, u64 *wr) {
  nodes_tls++;
  const u64 live = live_of(p);
  const int remaining = (__builtin_popcountll(live) + p->n) / 4;
  *wr = 0;
  u64 key = 0; uint8_t lk = 0; const uint32_t *own = p->own;
  int first = -1;
  if (p->n == 0) {
    if (remaining == 0) return 0;
    const int L = p->leader;
    if (remaining == 1) {
      int best = __builtin_ctzll(p->h[L]), w = L, same = 0;
      for (int k = 1; k < 4; k++) {
        const int s = (L + k) & 3, c = __builtin_ctzll(p->h[s]);
        if (suit_of(c) == suit_of(best)) { same = 1; if (rank_of(c) > rank_of(best)) { best = c; w = s; } }
      }
      if (same) *wr = 1ULL << best;
      return (w & 1) == 0;
    }
    if (!x->nolo) {
      u64 qc; const int q = quick_tricks(p, live, &qc);
      if ((L & 1) == 0) { if (q >= beta) { *wr = qc; return q; } }
      else if (remaining - q <= alpha) { *wr = qc; return remaining - q; }
    }
    key = p->lens;
    lk = (uint8_t)(L | (x->nolo << 7));
    const MList *ml = mlist_of(x, key, lk);
    if (ml->used && ml->lens == key && ml->lk == lk) {
      // Every candidate bucket is fetched first, so the memory reads overlap.
      const Bucket *cand[MVECS];
      uint32_t masked[MVECS][4];
      for (int i = 0; i < ml->n; i++) {
        mask_owners(own, ml->m[i], masked[i]);
        cand[i] = bucket_of(x, key, lk, ml->m[i], masked[i]);
        __builtin_prefetch(cand[i]);
      }
      for (int i = 0; i < ml->n; i++) {
        const uint16_t m = ml->m[i];
        const uint32_t *mo = masked[i];
        const Bucket *b = cand[i];
        for (int j = 0; j < WAYS; j++) {
          const Entry *e = &b->e[j];
          if (!e->used || e->lens != key || e->lk != lk || e->m != m || memcmp(e->own, mo, 4 * sizeof *mo)) continue;
          if (e->lo >= beta || e->hi <= alpha || e->lo == e->hi) {
            for (int t = 0; t < 4; t++) *wr |= top_cards(live, t, (m >> (4 * t)) & 15);
            return e->lo >= beta ? e->lo : e->hi <= alpha ? e->hi : e->lo;
          }
          if (first < 0) first = move_card(live, e->move);
        }
      }
    }
  }
  const int seat = (p->leader + p->n) & 3;
  const int mx = ((seat & 1) == 0) ^ x->nolo;  // this seat's side wants team 0 to take more
  const int a0 = alpha, b0 = beta;
  int mv[13], k = gen_moves(p, seat, mv);
  order_moves(x, p, seat, mv, k, first);
  u64 acc = 0; int skip_below[4] = {-1, -1, -1, -1};
  int best = mx ? -1 : 99, best_move = mv[0];
  for (int i = 0; i < k; i++) {
    const int c = mv[i], s = suit_of(c);
    if (rank_of(c) < skip_below[s]) continue;
    Pos q = *p;
    q.h[seat] &= ~(1ULL << c);
    q.lens -= 1ULL << (4 * (4 * seat + s));
    {  // drop c's 2-bit owner code: it sits below the cards of its suit above it
      const int above = __builtin_popcountll(live & SUIT_MASK(s) & ~((2ULL << c) - 1));
      const uint32_t low = q.own[s] & ((1u << (2 * above)) - 1);
      q.own[s] = low | ((q.own[s] >> (2 * above + 2)) << (2 * above));
    }
    q.card[q.n++] = c;
    u64 cw; int v;
    if (q.n == 4) {
      const int ls = suit_of(q.card[0]);
      int b = 0, same = 0;
      for (int j = 1; j < 4; j++) if (suit_of(q.card[j]) == ls) { same = 1; if (rank_of(q.card[j]) > rank_of(q.card[b])) b = j; }
      const int ws = (q.leader + b) & 3, t = (ws & 1) == 0, wc = q.card[b];
      u64 trick = 0;
      for (int j = 0; j < 4; j++) trick |= 1ULL << q.card[j];
      q.leader = ws; q.n = 0;
      v = t + ab(x, &q, alpha - t, beta - t, &cw);
      if (same) {
        // The winner, and the run of the winner's own cards just below it.
        cw |= 1ULL << wc;
        const u64 before = live_of(&q) | trick;
        for (int r = rank_of(wc) - 1; r >= 0; r--) {
          const int cc = ls * 13 + r;
          if (q.h[ws] >> cc & 1ULL) cw |= 1ULL << cc;
          else if (before >> cc & 1ULL) break;
        }
      }
    } else v = ab(x, &q, alpha, beta, &cw);
    if (mx) { if (v > best) { best = v; best_move = c; } if (best > alpha) alpha = best; }
    else { if (v < best) { best = v; best_move = c; } if (best < beta) beta = best; }
    if (alpha >= beta) { acc = cw; break; }  // proved by this card alone
    acc |= cw;
    if (skip_below[s] < 0) {
      // The mover's lower cards of this suit below every winning rank found
      // so far behave exactly like c.
      const u64 wsu = acc & SUIT_MASK(s);
      const int low = wsu ? rank_of(__builtin_ctzll(wsu)) : 13;
      skip_below[s] = rank_of(c) < low ? low : 0;
    }
  }
  *wr = acc;
  if (p->n == 0) {
    const uint16_t m = partition_of(live, acc);
    uint32_t mine[4];
    mask_owners(own, m, mine);
    Bucket *bucket = bucket_of(x, key, lk, m, mine);
    Entry *slot = NULL;
    for (int i = 0; i < WAYS && !slot; i++) {
      Entry *e = &bucket->e[i];
      if (e->used && e->lens == key && e->lk == lk && e->m == m && !memcmp(e->own, mine, sizeof mine)) slot = e;
    }
    if (!slot) {
      slot = &bucket->e[0];
      for (int i = 0; i < WAYS; i++) {
        Entry *e = &bucket->e[i];
        if (!e->used) { slot = e; break; }
        if (e->depth < slot->depth) slot = e;
      }
      slot->used = 1; slot->lens = key; slot->lk = lk; slot->m = m; slot->depth = (uint8_t)remaining;
      memcpy(slot->own, mine, sizeof mine);
      slot->lo = 0; slot->hi = (int8_t)remaining;
      MList *ml = mlist_of(x, key, lk);
      if (!ml->used || ml->lens != key || ml->lk != lk) { ml->used = 1; ml->lens = key; ml->lk = lk; ml->n = 0; ml->next = 0; }
      int known = 0;
      for (int i = 0; i < ml->n; i++) known |= ml->m[i] == m;
      if (!known) {
        if (ml->n < MVECS) ml->m[ml->n++] = m;
        else { ml->m[ml->next] = m; ml->next = (uint8_t)((ml->next + 1) % MVECS); }
      }
    }
    if (best <= a0) { if (best < slot->hi) slot->hi = (int8_t)best; }
    else if (best >= b0) { if (best > slot->lo) slot->lo = (int8_t)best; }
    else slot->lo = slot->hi = (int8_t)best;
    slot->move = move_code(live, best_move);
  }
  return best;
}

static void to_pos(const TcDeal *d, Pos *p) {
  memset(p, 0, sizeof *p);
  for (int s = 0; s < 4; s++) p->h[s] = d->hand[s];
  const int pos = d->n_played & 3;
  p->n = pos;
  if (pos) {
    const int start = d->n_played - pos;
    p->leader = d->play_seat[start];
    for (int i = 0; i < pos; i++) p->card[i] = d->play_card[start + i];
  } else p->leader = d->cur;
  p->lens = lens_key(p);
  for (int s = 0; s < 4; s++) p->own[s] = owners(p, s, live_of(p));
}

static __thread u64 last_nodes;
void tc_dd_wr_set_table_bits(int bits) { if (bits >= 12 && bits <= 24) table_bits = bits; }
uint64_t tc_dd_wr_last_nodes(void) { return last_nodes; }

// Final team-0 tricks under perfect-information optimal play from this
// trick-play position.
int tc_dd_wr_team0_tricks(const TcDeal *d) {
  if (!table_tls) {
    tc_thread_owns(table_tls = calloc(1ULL << table_bits, sizeof(Bucket)));
    tc_thread_owns(mlist_tls = calloc(1ULL << (table_bits - 2), sizeof(MList)));
  }
  const Ctx x = {table_tls, mlist_tls, d->contract == TC_NOLO};
  nodes_tls = 0;
  Pos p; to_pos(d, &p);
  const int remaining = 13 - (d->n_played >> 2);
  int lower = 0, upper = remaining, g = remaining / 2;
  while (lower < upper) {  // MTD(f): null-window probes that move towards the value
    const int beta = (g == lower) ? g + 1 : g;
    Pos q = p; u64 wr;
    const int v = ab(&x, &q, beta - 1, beta, &wr);
    if (v < beta) upper = v; else lower = v;
    g = v < lower ? lower : v > upper ? upper : v;
  }
  last_nodes = nodes_tls;
  return d->team_tricks[0] + lower;
}

// Whole deal from its first lead, with four 52-bit hands (tools/faceup.py).
int tc_dd_wr_deal(const uint64_t hands[4], int contract, int leader) {
  TcDeal d;
  memset(&d, 0, sizeof d);
  for (int s = 0; s < 4; s++) d.hand[s] = hands[s];
  d.contract = (int8_t)contract;
  d.cur = (uint8_t)leader;
  return tc_dd_wr_team0_tricks(&d);
}

// Does team 0 finish the deal with at least `final_tricks` tricks under
// perfect-information optimal play from this trick-play position? One
// null-window search, cheaper than the exact value.
int tc_dd_wr_team0_at_least(const TcDeal *d, int final_tricks) {
  const int target = final_tricks - d->team_tricks[0], remaining = 13 - (d->n_played >> 2);
  if (target <= 0) return 1;
  if (target > remaining) return 0;
  if (!table_tls) {
    tc_thread_owns(table_tls = calloc(1ULL << table_bits, sizeof(Bucket)));
    tc_thread_owns(mlist_tls = calloc(1ULL << (table_bits - 2), sizeof(MList)));
  }
  const Ctx x = {table_tls, mlist_tls, d->contract == TC_NOLO};
  Pos p; to_pos(d, &p);
  u64 wr;
  return ab(&x, &p, target - 1, target, &wr) >= target;
}
