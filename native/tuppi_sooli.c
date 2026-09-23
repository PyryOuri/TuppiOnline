// Perfect-information solver for sooli trick play (project_target_v2).
//
// Sooli is a boolean game: the soolaaja survives (takes no trick in the rest
// of the deal) or not. Three hands play: the leader and the other RAMI player
// (the RAMI pair, who want the soolaaja to win a trick) and the soolaaja, who
// always plays last. The dead hand never plays, so its cards are simply gone.
//
// Internally cards use an ace-low layout: bit suit * 13 + sooli rank
// (A = 0, 2 = 1, ..., K = 12), so "higher" is "higher bit" within a suit.
//
// Exact pruning, all at trick boundaries:
//  - immediate loss: the leader holds a card below the soolaaja's lowest in a
//    suit, and the other RAMI player is void there or also holds one;
//  - certain survival: in every suit the soolaaja's i-th lowest card is below
//    the RAMI pair's combined i-th lowest (playing the lowest card of the led
//    suit then always ducks, and discards never hurt the soolaaja);
//  - rank equivalence of cards adjacent among live cards;
//  - a transposition table keyed on the canonical per-suit owner sequence,
//    which describes the subgame completely, so entries stay valid across
//    solves and are never cleared.
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;
#define SM 0x1FFFULL
#define SUITM(s) (SM << ((s) * 13))

static inline u64 to_low(u64 h) {
  u64 out = 0;
  for (int s = 0; s < 4; s++) {
    u64 m = (h >> (13 * s)) & SM;
    out |= (((m & 0xFFFULL) << 1) | (m >> 12)) << (13 * s);
  }
  return out;
}
static inline int card_low(int c) { int s = c / 13, r = c % 13; return s * 13 + (r == 12 ? 0 : r + 1); }

typedef struct { u64 k0, k1; uint8_t val, used; } STE;
#define STBITS 18
static __thread STE *stt = NULL;
static __thread long nodes;

// h[0], h[1]: the RAMI players (h[L] leads), h[2]: the soolaaja.
typedef struct { u64 h[3]; } SPos;

static void key_of(const SPos *p, int L, u64 *k0, u64 *k1) {
  u64 live = p->h[0] | p->h[1] | p->h[2];
  u64 part[4];
  for (int s = 0; s < 4; s++) {
    u64 m = (live >> (13 * s)) & SM, code = 0;
    while (m) {
      int r = __builtin_ctzll(m);
      m &= m - 1;
      u64 b = 1ULL << (13 * s + r);
      int owner = (p->h[L] & b) ? 1 : (p->h[1 - L] & b) ? 2 : 3;
      code = code << 2 | (u64)owner;
    }
    part[s] = code;
  }
  *k0 = part[0] | part[1] << 26;
  *k1 = part[2] | part[3] << 26;
}

static inline u64 mix(u64 x) {
  x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL; x ^= x >> 33; return x;
}

// Representatives: the lowest card of every run of `hand`'s cards that are
// adjacent among `live` cards (same suit). Written in ascending order.
static int reps(u64 hand, u64 live, int *mv) {
  int k = 0;
  u64 m = hand;
  while (m) {
    int c = __builtin_ctzll(m);
    m &= m - 1;
    int base = (c / 13) * 13;
    u64 below = live & ((1ULL << c) - 1) & ~((1ULL << base) - 1);
    if (below) {
      int prev = 63 - __builtin_clzll(below);
      if (hand >> prev & 1ULL) continue;
    }
    mv[k++] = c;
  }
  return k;
}

static int lead_node(SPos *p, int L);

// Soolaaja to play last; `hi` is the highest led-suit card so far (low layout)
// and `winner` the RAMI player holding it. Returns 1 if the soolaaja survives.
static int third(SPos *p, int L, int led, int hi, int winner, u64 trick_live) {
  u64 hs = p->h[2], follow = hs & SUITM(led);
  u64 options;
  if (follow) {
    options = follow & ((1ULL << hi) - 1);
    if (!options) return 0;  // must win the trick
  } else {
    options = hs;
  }
  int mv[13];
  int k = reps(options, p->h[0] | p->h[1] | p->h[2] | trick_live, mv);
  // Highest first: keep low cards for later.
  for (int i = k - 1; i >= 0; i--) {
    u64 b = 1ULL << mv[i];
    p->h[2] &= ~b;
    int r = lead_node(p, winner);
    p->h[2] |= b;
    if (r) return 1;
  }
  return 0;
}

static int second(SPos *p, int L, int a) {
  int O = 1 - L, led = a / 13;
  u64 ho = p->h[O], follow = ho & SUITM(led);
  u64 trick_live = 1ULL << a;
  int mv[13];
  int k = reps(follow ? follow : ho, p->h[0] | p->h[1] | p->h[2] | trick_live, mv);
  // Follow low; discard high.
  for (int j = 0; j < k; j++) {
    int b = follow ? mv[j] : mv[k - 1 - j];
    u64 bb = 1ULL << b;
    p->h[O] &= ~bb;
    int hi = a, winner = L;
    if (b / 13 == led && b > a) { hi = b; winner = O; }
    int r = third(p, L, led, hi, winner, trick_live | bb);
    p->h[O] |= bb;
    if (!r) return 0;
  }
  return 1;
}

static int lead_node(SPos *p, int L) {
  nodes++;
  u64 hs = p->h[2];
  if (!hs) return 1;
  const int O = 1 - L;
  int certain = 1;
  for (int s = 0; s < 4; s++) {
    u64 S = (hs >> (13 * s)) & SM;
    if (!S) continue;
    u64 Ls = (p->h[L] >> (13 * s)) & SM, Os = (p->h[O] >> (13 * s)) & SM;
    int minS = __builtin_ctzll(S);
    if (Ls && __builtin_ctzll(Ls) < minS && (!Os || __builtin_ctzll(Os) < minS)) return 0;
    if (certain) {
      u64 R = Ls | Os;
      while (S && R) {
        if (__builtin_ctzll(S) > __builtin_ctzll(R)) { certain = 0; break; }
        S &= S - 1;
        R &= R - 1;
      }
    }
  }
  if (certain) return 1;

  if (!stt) stt = calloc((size_t)1 << STBITS, sizeof(STE));
  u64 k0, k1;
  key_of(p, L, &k0, &k1);
  STE *e = &stt[mix(k0 * 0x9E3779B97F4A7C15ULL ^ k1) & (((u64)1 << STBITS) - 1)];
  if (e->used && e->k0 == k0 && e->k1 == k1) return e->val;

  int mv[13];
  int k = reps(p->h[L], p->h[0] | p->h[1] | p->h[2], mv);
  // Suits the soolaaja holds first, low cards first.
  int order[13], n = 0;
  for (int pass = 0; pass < 2; pass++)
    for (int i = 0; i < k; i++) {
      int has = (hs & SUITM(mv[i] / 13)) != 0;
      if (has == (pass == 0)) order[n++] = mv[i];
    }
  int result = 1;
  for (int i = 0; i < n && result; i++) {
    u64 b = 1ULL << order[i];
    p->h[L] &= ~b;
    if (!second(p, L, order[i])) result = 0;
    p->h[L] |= b;
  }
  e->k0 = k0;
  e->k1 = k1;
  e->val = (uint8_t)result;
  e->used = 1;
  return result;
}

// Position of a TcDeal in sooli play, in the solver's layout. Returns the
// number of cards already in the current trick (0..2) and fills them.
static int load(const TcDeal *d, SPos *p, int *L, int trick[2]) {
  int D = d->declarer, P = (D + 2) & 3, S = d->soolaaja;
  int pos = d->n_played % 3, leader = pos ? d->play_seat[d->n_played - pos] : d->cur;
  int seat_of[2] = {leader, leader == D ? P : D};
  p->h[0] = to_low(d->hand[seat_of[0]]);
  p->h[1] = to_low(d->hand[seat_of[1]]);
  p->h[2] = to_low(d->hand[S]);
  *L = 0;
  for (int i = 0; i < pos; i++) trick[i] = card_low(d->play_card[d->n_played - pos + i]);
  return pos;
}

static int solve_from(SPos *p, int L, int pos, const int trick[2]) {
  if (pos == 0) return lead_node(p, L);
  if (pos == 1) return second(p, L, trick[0]);
  int a = trick[0], b = trick[1], led = a / 13, hi = a, winner = L;
  if (b / 13 == led && b > a) { hi = b; winner = 1 - L; }
  return third(p, L, led, hi, winner, (1ULL << a) | (1ULL << b));
}

// 1 if the soolaaja survives the rest of the deal under perfect-information
// play, 0 if the RAMI pair can force a trick on them; -1 if not in sooli play.
int tc_sooli_solve(const TcDeal *d) {
  if (d->phase == TC_PH_DONE && d->soolaaja >= 0) return d->sooli_won;
  if (d->phase != TC_PH_SOOLI_PLAY) return -1;
  SPos p;
  int L, trick[2];
  int pos = load(d, &p, &L, trick);
  return solve_from(&p, L, pos, trick);
}

// Solver values of the current actor's legal moves in sooli play: out[i] = 1
// if the soolaaja survives after actions[i]. Returns 0, or -1 if not in sooli
// play or an action is illegal.
int tc_sooli_move_values(const TcDeal *d, const int *actions, int k, int *out) {
  if (d->phase != TC_PH_SOOLI_PLAY) return -1;
  for (int i = 0; i < k; i++) {
    TcDeal c = *d;
    if (tc_apply(&c, actions[i]) != 0) return -1;
    out[i] = tc_sooli_solve(&c);
  }
  return 0;
}

// Finishes a deal in sooli play with its perfect-information result.
void tc_sooli_finish(TcDeal *d) {
  int safe = tc_sooli_solve(d);
  if (safe < 0 || d->phase == TC_PH_DONE) return;
  d->phase = TC_PH_DONE;
  d->sooli_won = (uint8_t)safe;
  d->winner_team = (int8_t)(safe ? (d->soolaaja & 1) : (d->declarer & 1));
  d->points = TC_SOOLI_POINTS;
  d->stolen = 0;
}

long tc_sooli_nodes(void) { long n = nodes; nodes = 0; return n; }
