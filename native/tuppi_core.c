#include "tuppi_core.h"

#include <string.h>

typedef uint64_t u64;

#define FULL_DECK ((1ULL << 52) - 1)
#define SUIT_MASK(s) (0x1FFFULL << ((s) * 13))
// Ranks 3..9 are rank indices 1..7 within a suit.
#define ELIGIBLE (0xFEULL | (0xFEULL << 13) | (0xFEULL << 26) | (0xFEULL << 39))
#define RED (SUIT_MASK(0) | SUIT_MASK(1))
#define BLACK (SUIT_MASK(2) | SUIT_MASK(3))

static inline int suit_of(int c) { return c / 13; }
static inline int rank_of(int c) { return c % 13; }

uint64_t tc_valid_show_cards(uint64_t hand, int contract) {
  u64 colour = contract == TC_RAMI ? RED : BLACK;
  u64 m = hand & ELIGIBLE & colour;
  if (m) return m;
  m = hand & ELIGIBLE;
  if (m) return m;
  return hand;
}

int tc_verbal_required(int card, int contract) {
  u64 colour = contract == TC_RAMI ? RED : BLACK;
  return !((ELIGIBLE & colour) >> card & 1ULL);
}

// Lets the Python bindings refuse a stale library with a different layout.
void tc_struct_sizes(int *out) { out[0] = (int)sizeof(TcDeal); out[1] = (int)sizeof(TcObs); }

int tc_sooli_rank(int card) { int r = card % 13; return r == 12 ? 0 : r + 1; }

void tc_deal_init_v(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1, int ruleset) {
  tc_deal_init(d, hands, dealer, score0, score1);
  d->ruleset = (uint8_t)(ruleset == 2 || ruleset == 3 ? ruleset : 1);
}

void tc_deal_init(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1) {
  memset(d, 0, sizeof *d);
  d->ruleset = 1;
  d->trick_size = 4;
  d->soolaaja = -1;
  d->given = -1;
  d->returned = -1;
  for (int i = 0; i < 4; i++) d->hand[i] = hands[i];
  d->dealer = (uint8_t)dealer;
  d->phase = TC_PH_SHOW;
  d->cur = (uint8_t)((dealer + 1) & 3);
  d->contract = -1;
  d->declarer = -1;
  d->winner_team = -1;
  d->score[0] = (uint8_t)score0;
  d->score[1] = (uint8_t)score1;
}

static int legal_from(u64 hand, int phase, int n_played, const uint8_t *play_card, int trick_size, int given,
                      int *actions) {
  int k = 0;
  if (phase == TC_PH_SOOLI_OFFER) {
    actions[0] = TC_ACT_SOOLI_DECLINE;
    actions[1] = TC_ACT_SOOLI_ACCEPT;
    return 2;
  }
  if (phase == TC_PH_SOOLI_GIVE || phase == TC_PH_SOOLI_RETURN) {
    u64 m = hand;
    if (phase == TC_PH_SOOLI_RETURN && given >= 0) m &= ~(1ULL << given);
    while (m) { int c = __builtin_ctzll(m); m &= m - 1; actions[k++] = TC_ACT_EXCHANGE + c; }
    return k;
  }
  if (phase == TC_PH_SHOW) {
    for (int contract = 0; contract < 2; contract++) {
      u64 m = tc_valid_show_cards(hand, contract);
      while (m) {
        int c = __builtin_ctzll(m);
        m &= m - 1;
        actions[k++] = 52 + 52 * contract + c;
      }
    }
    return k;
  }
  if (phase != TC_PH_PLAY && phase != TC_PH_SOOLI_PLAY) return 0;
  u64 legal = hand;
  int pos = trick_size == 3 ? n_played % 3 : n_played & 3;
  if (pos) {
    int led = suit_of(play_card[n_played - pos]);
    u64 f = hand & SUIT_MASK(led);
    if (f) legal = f;
  }
  while (legal) {
    int c = __builtin_ctzll(legal);
    legal &= legal - 1;
    actions[k++] = c;
  }
  return k;
}

int tc_legal(const TcDeal *d, int *actions) {
  return legal_from(d->hand[d->cur], d->phase, d->n_played, d->play_card, d->trick_size, d->given, actions);
}

int tc_next_score(const uint8_t score[2], int winner_team, int points, uint8_t out[2]) {
  int s0 = score[0], s1 = score[1];
  if (s0 == 0 && s1 == 0) {
    if (winner_team == 0) s0 = points; else s1 = points;
  } else {
    int up = s0 > 0 ? 0 : 1;
    if (winner_team == up) {
      if (up == 0) s0 += points; else s1 += points;
    } else {
      s0 = 0;
      s1 = 0;
    }
  }
  out[0] = (uint8_t)s0;
  out[1] = (uint8_t)s1;
  return s0 >= TC_TARGET || s1 >= TC_TARGET;
}

static void finish(TcDeal *d) {
  d->phase = TC_PH_DONE;
  int t0 = d->team_tricks[0], t1 = d->team_tricks[1];
  if (d->contract == TC_NOLO) {
    int w = t0 < t1 ? 0 : 1;
    d->winner_team = (int8_t)w;
    d->points = (uint8_t)(4 * (7 - d->team_tricks[w]));
    d->stolen = 0;
  } else {
    int dt = d->declarer & 1;
    if (d->team_tricks[dt] >= 7) {
      d->winner_team = (int8_t)dt;
      d->points = (uint8_t)(4 * (d->team_tricks[dt] - 6));
      d->stolen = 0;
    } else {
      d->winner_team = (int8_t)(1 - dt);
      d->points = (uint8_t)(8 * (d->team_tricks[1 - dt] - 6));
      d->stolen = 1;
    }
  }
}

void tc_finish_with_tricks(TcDeal *d, int team0_tricks) {
  d->team_tricks[0] = (uint8_t)team0_tricks;
  d->team_tricks[1] = (uint8_t)(13 - team0_tricks);
  finish(d);
}

static void finish_sooli(TcDeal *d, int soolaaja_won_trick) {
  d->phase = TC_PH_DONE;
  d->sooli_won = (uint8_t)!soolaaja_won_trick;
  d->winner_team = (int8_t)(soolaaja_won_trick ? (d->declarer & 1) : (d->soolaaja & 1));
  d->points = TC_SOOLI_POINTS;
  d->stolen = 0;
}

static int apply_sooli(TcDeal *d, int action) {
  int seat = d->cur;
  if (d->phase == TC_PH_SOOLI_OFFER) {
    if (action != TC_ACT_SOOLI_DECLINE && action != TC_ACT_SOOLI_ACCEPT) return -1;
    int i = d->n_decisions++;
    d->decision_seat[i] = (uint8_t)seat;
    d->decision_accept[i] = (uint8_t)(action == TC_ACT_SOOLI_ACCEPT);
    if (action == TC_ACT_SOOLI_ACCEPT) {
      d->soolaaja = (int8_t)seat;
      d->phase = TC_PH_SOOLI_GIVE;
    } else if (d->n_decisions == 1) {
      d->cur = (uint8_t)((d->declarer + 3) & 3);
    } else {
      d->phase = TC_PH_PLAY;  // both declined: an ordinary RAMI deal
      d->cur = d->first_leader;
    }
    return 0;
  }
  if (d->phase == TC_PH_SOOLI_GIVE || d->phase == TC_PH_SOOLI_RETURN) {
    int c = action - TC_ACT_EXCHANGE;
    if (c < 0 || c >= 52 || !(d->hand[seat] >> c & 1ULL)) return -1;
    int partner = (d->soolaaja + 2) & 3;
    if (d->phase == TC_PH_SOOLI_GIVE) {
      d->hand[seat] &= ~(1ULL << c);
      d->hand[partner] |= 1ULL << c;
      d->given = (int8_t)c;
      d->phase = TC_PH_SOOLI_RETURN;
      d->cur = (uint8_t)partner;
    } else {
      if (c == d->given) return -1;
      d->hand[seat] &= ~(1ULL << c);
      d->hand[(int)d->soolaaja] |= 1ULL << c;
      d->returned = (int8_t)c;
      d->phase = TC_PH_SOOLI_PLAY;
      d->trick_size = 3;
      d->cur = (uint8_t)d->declarer;  // the declarer leads the first sooli trick
    }
    return 0;
  }
  // TC_PH_SOOLI_PLAY
  if (action < 0 || action >= 52) return -1;
  u64 b = 1ULL << action;
  if (!(d->hand[seat] & b)) return -1;
  int pos = d->n_played % 3;
  if (pos) {
    int led = suit_of(d->play_card[d->n_played - pos]);
    if (suit_of(action) != led && (d->hand[seat] & SUIT_MASK(led))) return -1;
  }
  d->hand[seat] &= ~b;
  d->play_card[d->n_played] = (uint8_t)action;
  d->play_seat[d->n_played] = (uint8_t)seat;
  d->n_played++;
  if (pos == 0) { d->cur = (uint8_t)((seat + 2) & 3); return 0; }        // other RAMI player
  if (pos == 1) { d->cur = (uint8_t)d->soolaaja; return 0; }             // soolaaja last
  int start = d->n_played - 3, led = suit_of(d->play_card[start]), best = start;
  for (int i = start + 1; i < start + 3; i++)
    if (suit_of(d->play_card[i]) == led && tc_sooli_rank(d->play_card[i]) > tc_sooli_rank(d->play_card[best])) best = i;
  int winner = d->play_seat[best];
  d->team_tricks[winner & 1]++;
  if (winner == d->soolaaja) { finish_sooli(d, 1); return 0; }
  if (d->n_played == 39) { finish_sooli(d, 0); return 0; }
  d->cur = (uint8_t)winner;
  return 0;
}

int tc_apply(TcDeal *d, int action) {
  int seat = d->cur;
  if (d->phase >= TC_PH_SOOLI_OFFER) return apply_sooli(d, action);
  if (d->phase == TC_PH_SHOW) {
    if (action < 52 || action >= TC_NUM_ACTIONS) return -1;
    int contract = (action - 52) / 52, card = (action - 52) % 52;
    if (!(tc_valid_show_cards(d->hand[seat], contract) >> card & 1ULL)) return -1;
    int i = d->n_shows++;
    d->show_seat[i] = (uint8_t)seat;
    d->show_card[i] = (uint8_t)card;
    d->show_contract[i] = (uint8_t)contract;
    d->show_verbal[i] = (uint8_t)tc_verbal_required(card, contract);
    if (contract == TC_RAMI) {
      d->contract = TC_RAMI;
      d->declarer = (int8_t)seat;
      d->first_leader = (uint8_t)((seat + 3) & 3);
      if (d->ruleset >= 2) {  // defenders are asked about sooli first
        d->phase = TC_PH_SOOLI_OFFER;
        d->cur = (uint8_t)((seat + 1) & 3);
        return 0;
      }
      d->phase = TC_PH_PLAY;
      d->cur = d->first_leader;
    } else if (d->n_shows == 4) {
      d->contract = TC_NOLO;
      d->declarer = -1;
      d->first_leader = (uint8_t)((d->dealer + 1) & 3);
      d->phase = TC_PH_PLAY;
      d->cur = d->first_leader;
    } else {
      d->cur = (uint8_t)((seat + 1) & 3);
    }
    return 0;
  }
  if (d->phase != TC_PH_PLAY) return -1;
  if (action < 0 || action >= 52) return -1;
  u64 b = 1ULL << action;
  if (!(d->hand[seat] & b)) return -1;
  int pos = d->n_played & 3;
  if (pos) {
    int led = suit_of(d->play_card[d->n_played - pos]);
    if (suit_of(action) != led && (d->hand[seat] & SUIT_MASK(led))) return -1;
  }
  d->hand[seat] &= ~b;
  d->play_card[d->n_played] = (uint8_t)action;
  d->play_seat[d->n_played] = (uint8_t)seat;
  d->n_played++;
  if (pos == 3) {
    int start = d->n_played - 4, led = suit_of(d->play_card[start]), best = start;
    for (int i = start + 1; i < start + 4; i++)
      if (suit_of(d->play_card[i]) == led && rank_of(d->play_card[i]) > rank_of(d->play_card[best])) best = i;
    int winner = d->play_seat[best];
    d->team_tricks[winner & 1]++;
    d->cur = (uint8_t)winner;
    if (d->n_played == 52) finish(d);
  } else {
    d->cur = (uint8_t)((seat + 1) & 3);
  }
  return 0;
}

void tc_observe(const TcDeal *d, int seat, TcObs *o) {
  memset(o, 0, sizeof *o);
  o->hand = d->hand[seat];
  o->seat = (uint8_t)seat;
  o->dealer = d->dealer;
  o->phase = d->phase;
  o->n_shows = d->n_shows;
  if (!(d->ruleset == 3 && d->phase == TC_PH_SHOW)) {  // locked bids: the count only
    memcpy(o->show_seat, d->show_seat, 4);
    memcpy(o->show_card, d->show_card, 4);
    memcpy(o->show_contract, d->show_contract, 4);
    memcpy(o->show_verbal, d->show_verbal, 4);
  }
  o->contract = d->contract;
  o->declarer = d->declarer;
  o->first_leader = d->first_leader;
  o->n_played = d->n_played;
  memcpy(o->play_card, d->play_card, d->n_played);
  memcpy(o->play_seat, d->play_seat, d->n_played);
  o->score[0] = d->score[0];
  o->score[1] = d->score[1];
  o->ruleset = d->ruleset;
  o->trick_size = d->trick_size;
  o->n_decisions = d->n_decisions;
  memcpy(o->decision_seat, d->decision_seat, 2);
  memcpy(o->decision_accept, d->decision_accept, 2);
  o->soolaaja = d->soolaaja;
  int knows = d->soolaaja >= 0 && (seat == d->soolaaja || seat == ((d->soolaaja + 2) & 3));
  o->known_given = knows ? d->given : -1;
  o->known_returned = knows ? d->returned : -1;
}

int tc_legal_obs(const TcObs *o, int *actions) {
  return legal_from(o->hand, o->phase, o->n_played, o->play_card, o->trick_size, o->known_given, actions);
}

// ---------------------------------------------------------------- encoder
enum {
  F_HAND = 0,
  F_PLAYED = F_HAND + 52,          // 4 x 52, by relative seat
  F_LED = F_PLAYED + 208,          // 4 x 52, cards each seat led
  F_DISCARD = F_LED + 208,         // 4 x 52, cards played off the led suit
  F_TRICK = F_DISCARD + 208,       // 3 x 52, current trick by relative seat 1..3
  F_LED_SUIT = F_TRICK + 156,      // 4
  F_VOID = F_LED_SUIT + 4,         // 3 x 4, relative seats 1..3
  F_SHOW = F_VOID + 12,            // 4 x 56: card, NOLO, RAMI, verbal, shown
  F_SHOWN_HELD = F_SHOW + 224,     // 4
  F_UNSEEN = F_SHOWN_HELD + 4,     // 52
  F_CONTRACT = F_UNSEEN + 52,      // 3: undecided, NOLO, RAMI
  F_DECLARER = F_CONTRACT + 3,     // 5: relative seat, none
  F_LEADER = F_DECLARER + 5,       // 4
  F_POSITION = F_LEADER + 4,       // 4: my position in the trick
  F_TRICKS = F_POSITION + 4,       // 2 x 14: own team, other team
  F_TRICK_INDEX = F_TRICKS + 28,   // 13
  F_SCORE = F_TRICK_INDEX + 13,    // 2 x 13: own level, other level
  F_DEALER = F_SCORE + 26,         // 4
  F_SHOW_POS = F_DEALER + 4,       // 4: number of shows before me
  F_WINNING = F_SHOW_POS + 4,      // 4: relative seat currently winning the trick
  F_DIM = F_WINNING + 4
};

int tc_feature_dim(void) { return F_DIM; }

void tc_encode(const TcObs *o, uint8_t *out) {
  memset(out, 0, F_DIM);
  const int s = o->seat;
#define REL(x) (((x) - s) & 3)
  u64 m = o->hand;
  while (m) { int c = __builtin_ctzll(m); m &= m - 1; out[F_HAND + c] = 1; }

  u64 played_all = 0;
  int void_mask[4] = {0, 0, 0, 0};
  int tricks[2] = {0, 0};
  const int ts = o->trick_size == 3 ? 3 : 4;
  const int ace_low = ts == 3;
#define RANKV(c) (ace_low ? tc_sooli_rank(c) : rank_of(c))
  int n = o->n_played, full = n - (n % ts);
  int leader = ts == 3 ? o->declarer : o->first_leader;
  for (int t = 0; t < full; t += ts) {
    int led = suit_of(o->play_card[t]), best = t;
    for (int i = t; i < t + ts; i++) {
      int c = o->play_card[i], r = REL(o->play_seat[i]);
      played_all |= 1ULL << c;
      out[F_PLAYED + 52 * r + c] = 1;
      if (i == t) out[F_LED + 52 * r + c] = 1;
      else if (suit_of(c) != led) { out[F_DISCARD + 52 * r + c] = 1; void_mask[r] |= 1 << led; }
      if (i > t && suit_of(c) == led && RANKV(c) > RANKV(o->play_card[best])) best = i;
    }
    int w = o->play_seat[best];
    tricks[w & 1]++;
    leader = w;
  }
  int pos = n % ts;
  if ((o->phase == TC_PH_PLAY || o->phase == TC_PH_SOOLI_PLAY) && pos) {
    int t = full, led = suit_of(o->play_card[t]), best = t;
    leader = o->play_seat[t];
    out[F_LED_SUIT + led] = 1;
    for (int i = t; i < n; i++) {
      int c = o->play_card[i], r = REL(o->play_seat[i]);
      played_all |= 1ULL << c;
      out[F_PLAYED + 52 * r + c] = 1;
      if (r >= 1) out[F_TRICK + 52 * (r - 1) + c] = 1;
      if (i == t) out[F_LED + 52 * r + c] = 1;
      else if (suit_of(c) != led) { out[F_DISCARD + 52 * r + c] = 1; void_mask[r] |= 1 << led; }
      if (i > t && suit_of(c) == led && RANKV(c) > RANKV(o->play_card[best])) best = i;
    }
    out[F_WINNING + REL(o->play_seat[best])] = 1;
  }
  for (int r = 1; r < 4; r++)
    for (int v = 0; v < 4; v++)
      if (void_mask[r] >> v & 1) out[F_VOID + 4 * (r - 1) + v] = 1;

  for (int i = 0; i < (TC_LOCKED(o) ? 0 : o->n_shows); i++) {
    int r = REL(o->show_seat[i]), c = o->show_card[i];
    uint8_t *b = out + F_SHOW + 56 * r;
    b[c] = 1;
    b[52 + o->show_contract[i]] = 1;
    b[54] = o->show_verbal[i];
    b[55] = 1;
    if (!(played_all >> c & 1ULL)) out[F_SHOWN_HELD + r] = 1;
  }
  u64 unseen = FULL_DECK & ~o->hand & ~played_all;
  while (unseen) { int c = __builtin_ctzll(unseen); unseen &= unseen - 1; out[F_UNSEEN + c] = 1; }

  out[F_CONTRACT + (o->contract < 0 ? 0 : 1 + o->contract)] = 1;
  out[F_DECLARER + (o->declarer < 0 ? 4 : REL(o->declarer))] = 1;
  if (o->phase == TC_PH_PLAY || o->phase == TC_PH_SOOLI_PLAY) {
    out[F_LEADER + REL(leader)] = 1;
    out[F_POSITION + pos] = 1;
    out[F_TRICK_INDEX + (n / ts > 12 ? 12 : n / ts)] = 1;
  }
  int own = s & 1;
  out[F_TRICKS + tricks[own]] = 1;
  out[F_TRICKS + 14 + tricks[own ^ 1]] = 1;
  int lo = o->score[own] / 4, lt = o->score[own ^ 1] / 4;
  out[F_SCORE + (lo > 12 ? 12 : lo)] = 1;
  out[F_SCORE + 13 + (lt > 12 ? 12 : lt)] = 1;
  out[F_DEALER + REL(o->dealer)] = 1;
#undef RANKV
  if (o->phase == TC_PH_SHOW) out[F_SHOW_POS + (o->n_shows & 3)] = 1;
#undef REL
}

// ------------------------------------------------------------- encoder v2
// v1 plus the complete play order: for every played card, the index of the
// trick it was played in (with the seat already in v1 this recovers the whole
// sequence), and which card won each completed trick.
enum { F2_TRICK_OF = F_DIM, F2_WON = F2_TRICK_OF + 52 * 13, F2_DIM = F2_WON + 52 };

int tc_feature_dim_v(int version) { return version == 2 ? F2_DIM : F_DIM; }

void tc_encode_v(const TcObs *o, uint8_t *out, int version) {
  tc_encode(o, out);
  if (version != 2) return;
  memset(out + F_DIM, 0, F2_DIM - F_DIM);
  int n = o->n_played, ts = o->trick_size == 3 ? 3 : 4;
  for (int i = 0; i < n; i++) out[F2_TRICK_OF + 13 * o->play_card[i] + i / ts] = 1;
  for (int t = 0; t + ts <= n; t += ts) {
    int led = suit_of(o->play_card[t]), best = t;
    for (int i = t + 1; i < t + ts; i++) {
      int c = o->play_card[i], b = o->play_card[best];
      int higher = ts == 3 ? tc_sooli_rank(c) > tc_sooli_rank(b) : rank_of(c) > rank_of(b);
      if (suit_of(c) == led && higher) best = i;
    }
    out[F2_WON + o->play_card[best]] = 1;
  }
}
