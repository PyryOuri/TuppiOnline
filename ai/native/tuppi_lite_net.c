// Face-up safety net with play-inference layouts for the lite bot (C1;
// audit_deliverables/tuppi_faceup_improvements_20261020). Shared by the
// research harness (tuppi_match.c) and the hosted lite bot, and reads only
// the deciding seat's observation.
//
// In trick play near the end of a deal the network proposes a card. The net:
//   1. draws one uniform layout of the hidden cards (gate cursor); if the
//      card is optimal there with all cards face up, keeps it;
//   2. otherwise draws worlds * mult uniform layouts (belief cursor), weights
//      each by the network's likelihood of the other three seats' past
//      unforced choices replayed in it (temperature 2, eps 0.5, as confirmed
//      for the search bot's play inference), and resamples `worlds` of them;
//   3. replaces the card only if it is optimal in none of those layouts and
//      another card is optimal in all of them (the lowest such card id).
// The _h variants read the moves of seats known to be people more loosely
// (temperature 4, eps 0.8 measured best on people's games;
// audit_deliverables/tuppi_human_games, private). With no person marked,
// they are exactly the plain functions.
// "Optimal" compares the acting team's match-equity change of the deal under
// perfect play afterwards (tuppi_dd_wr.c, exact), with the bot's equity
// table.
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"
#include "tuppi_mlp.h"

typedef uint64_t u64;

int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out);
int tc_dd_wr_team0_tricks(const TcDeal *d);
int tc_dd_wr_team0_at_least(const TcDeal *d, int final_tricks);

static inline u64 splitmix(u64 *x) {
  u64 z = (*x += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}
static inline double unit01(u64 *x) { return (splitmix(x) >> 11) * (1.0 / 9007199254740992.0); }

// Team-0 equity of a score about to be played with the given dealer; eq is
// the 25 x 2 table of tuppi_ai.equity.native_table.
static double team0(const double *eq, int s0, int s1, int dealer) {
  if (s0 >= TC_TARGET) return 1.0;
  if (s1 >= TC_TARGET) return 0.0;
  const int row = (s0 == 0 && s1 == 0) ? 0 : s0 ? s0 / 4 : 12 + s1 / 4;
  return eq[2 * row + ((dealer & 1) == 0)];
}

// The acting team's equity change of a deal ended with t0 team-0 tricks.
static double finish_value(const double *eq, TcDeal d, int t0, int team) {
  if (d.phase != TC_PH_DONE) tc_finish_with_tricks(&d, t0);
  uint8_t after[2];
  tc_next_score(d.score, d.winner_team, d.points, after);
  const double delta = team0(eq, after[0], after[1], d.dealer + 1) - team0(eq, d.score[0], d.score[1], d.dealer);
  return team == 0 ? delta : -delta;
}

static double solved_value(const double *eq, TcDeal d, int team) {
  return finish_value(eq, d, d.phase == TC_PH_DONE ? 0 : tc_dd_wr_team0_tricks(&d), team);
}

// 1 if card `chosen` is optimal in this full layout, 0 if not, -1 if the
// one-probe test does not apply (the value is not monotone in team-0 tricks;
// never for the bot's table) or the card is illegal. Solves that card, then
// asks once whether the side to move can reach a count worth more.
static int chosen_optimal(const double *eq, const TcDeal *world, int chosen, int team) {
  TcDeal child = *world;
  if (tc_apply(&child, chosen) != 0) return -1;
  const int base = world->team_tricks[0], top = base + 13 - (world->n_played >> 2);
  double f[14];
  for (int t = base; t <= top; t++) f[t] = finish_value(eq, *world, t, team);
  int up = 1, down = 1;
  for (int t = base; t < top; t++) { up &= f[t + 1] >= f[t]; down &= f[t + 1] <= f[t]; }
  if (!up && !down) return -1;
  const int tc = child.phase == TC_PH_DONE ? child.team_tricks[0] : tc_dd_wr_team0_tricks(&child);
  const double vc = finish_value(eq, child, tc, team);
  if (up) {
    int tb = tc + 1;
    while (tb <= top && f[tb] <= vc + 1e-12) tb++;
    return tb > top || !tc_dd_wr_team0_at_least(world, tb);
  }
  int tb = tc - 1;
  while (tb >= base && f[tb] <= vc + 1e-12) tb--;
  return tb < base || tc_dd_wr_team0_at_least(world, tb + 1);
}

// Replays a full world from the start of its deal and emits, for every past
// unforced decision of a seat in `seat_mask`, that seat's encoded observation,
// legal mask and action (TuppiAI-belief 276f968's tc_history_rows, with its
// v3 fixes: the world's own ruleset, declined sooli offers replayed).
static int history_rows(const TcDeal *world, int seat_mask, int encoder, int max_rows,
                        uint8_t *feat, uint8_t *mask, int32_t *action) {
  if (world->soolaaja >= 0) return -1;
  uint64_t init[4];
  for (int s = 0; s < 4; s++) init[s] = world->hand[s];
  for (int i = 0; i < world->n_played; i++) init[world->play_seat[i]] |= 1ULL << world->play_card[i];
  TcDeal d;
  tc_deal_init_v(&d, init, world->dealer, world->score[0], world->score[1], world->ruleset);
  const int dim = tc_feature_dim_v(encoder), n_actions = world->n_shows + world->n_played;
  int rows = 0, acts[TC_NUM_ACTIONS], decided = 0;
  TcObs o;
  for (int t = 0; t < n_actions && rows < max_rows; t++) {
    while (d.phase == TC_PH_SOOLI_OFFER) {
      if (decided >= world->n_decisions || world->decision_accept[decided]) return -1;
      if (tc_apply(&d, TC_ACT_SOOLI_DECLINE) != 0) return -1;
      decided++;
    }
    const int a = t < world->n_shows ? 52 + 52 * world->show_contract[t] + world->show_card[t]
                                     : world->play_card[t - world->n_shows];
    const int seat = d.cur;
    if (seat_mask >> seat & 1) {
      const int k = tc_legal(&d, acts);
      if (k > 1) {
        tc_observe(&d, seat, &o);
        tc_encode_v(&o, feat + (size_t)rows * dim, encoder);
        uint8_t *mk = mask + (size_t)rows * TC_NUM_ACTIONS;
        memset(mk, 0, TC_NUM_ACTIONS);
        for (int j = 0; j < k; j++) mk[acts[j]] = 1;
        action[rows++] = a;
      }
    }
    if (tc_apply(&d, a) != 0) return -1;
  }
  return rows;
}

// w layouts resampled (systematically) from w * mult uniform ones by the
// network's likelihood of the other three seats' past play. The moves of
// seats in human_mask (people) are weighted at temperature human_t and eps
// human_eps instead of 2 and 0.5; with human_mask 0 every seat is read as
// before, by the same steps. Returns 0, or -1.
static int belief_worlds(const TcMlp *m, const TcObs *o, int w, int mult, int human_mask, double human_t,
                         double human_eps, u64 *rng, TcDeal *out) {
  enum { MAXR = 64, BLOCK = 16 };
  const int M = w * mult, enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc);
  const int others = 0xF & ~(1 << o->seat), people = human_mask & others;
  // Passes over each candidate's history: all other seats at once, or the
  // bots' seats and the people's seats with their own settings.
  const int npass = people ? 2 : 1;
  const int pass_seats[2] = {people ? others & ~people : others, people};
  const double pass_inv_t[2] = {0.5, 1.0 / human_t}, pass_eps[2] = {0.5, human_eps};
  TcDeal *cand = malloc(sizeof(TcDeal) * (size_t)M);
  double *logw = calloc((size_t)M, sizeof(double));
  for (int i = 0; i < M; i++)
    if (tc_sample_world(o, rng, &cand[i]) != 0) { free(cand); free(logw); return -1; }
  uint8_t *feat = malloc((size_t)BLOCK * MAXR * dim), *mask = malloc((size_t)BLOCK * MAXR * TC_NUM_ACTIONS);
  int32_t *act = malloc(sizeof(int32_t) * BLOCK * MAXR), *owner = malloc(sizeof(int32_t) * BLOCK * MAXR);
  float *q = malloc(sizeof(float) * (size_t)BLOCK * MAXR * TC_NUM_ACTIONS);
  for (int pass = 0; pass < npass; pass++) {
    const int seats = pass_seats[pass];
    const double inv_t = pass_inv_t[pass], eps = pass_eps[pass];
    if (!seats) continue;
    for (int first = 0; first < M; first += BLOCK) {
      const int last = first + BLOCK < M ? first + BLOCK : M;
      int rows = 0;
      for (int i = first; i < last; i++) {
        if (logw[i] < -1e299) continue;
        const int r = history_rows(&cand[i], seats, enc, MAXR, feat + (size_t)rows * dim,
                                   mask + (size_t)rows * TC_NUM_ACTIONS, act + rows);
        if (r < 0) { logw[i] = -1e300; continue; }
        for (int j = 0; j < r; j++) owner[rows + j] = i;
        rows += r;
      }
      if (rows) tc_mlp_forward(m, feat, rows, q);
      for (int r = 0; r < rows; r++) {
        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;
        const uint8_t *mr = mask + (size_t)r * TC_NUM_ACTIONS;
        double top = -1e300, sum = 0.0;
        int legal = 0;
        for (int a = 0; a < TC_NUM_ACTIONS; a++) if (mr[a] && qr[a] > top) top = qr[a];
        for (int a = 0; a < TC_NUM_ACTIONS; a++) if (mr[a]) { sum += exp((qr[a] - top) * inv_t); legal++; }
        const double p = exp((qr[act[r]] - top) * inv_t) / sum;
        logw[owner[r]] += log((1.0 - eps) * p + eps / legal);
      }
    }
  }
  free(feat); free(mask); free(act); free(owner); free(q);
  double top = -1e300, total = 0.0;
  for (int i = 0; i < M; i++) if (logw[i] > top) top = logw[i];
  for (int i = 0; i < M; i++) { logw[i] = logw[i] < -1e299 ? 0.0 : exp(logw[i] - top); total += logw[i]; }
  if (total <= 0) { for (int i = 0; i < M; i++) logw[i] = 1.0; total = M; }
  double u = unit01(rng) / w * total, cum = logw[0];
  for (int j = 0, i = 0; j < w; j++) {
    const double target = u + j * (total / w);
    while (cum < target && i < M - 1) cum += logw[++i];
    out[j] = cand[i];
  }
  free(cand); free(logw);
  return 0;
}

// Whether the net checks this decision: trick play outside sooli, more than
// one legal card, at most `tricks` tricks left (or `rami_tricks` in RAMI).
int tc_lite_net_applies(const TcObs *o, int tricks, int rami_tricks) {
  if (o->phase != TC_PH_PLAY || o->soolaaja >= 0) return 0;
  int ids[TC_NUM_ACTIONS_V2];
  if (tc_legal_obs(o, ids) < 2) return 0;
  const int left = 13 - o->n_played / 4;
  return left <= tricks || (o->contract == TC_RAMI && left <= rami_tricks);
}

// Steps 2-3 alone (no gate), people's moves read with their own setting
// (human_mask 0: as tc_lite_belief_net). Returns the card to play.
int tc_lite_belief_net_h(const TcMlp *m, const double *eq, const TcObs *o, int chosen, int worlds, int mult,
                         int human_mask, double human_t, double human_eps, uint64_t *rng) {
  int ids[TC_NUM_ACTIONS_V2];
  const int k = tc_legal_obs(o, ids), team = o->seat & 1;
  TcDeal layouts[64];
  if (worlds > 64 || worlds < 1
      || belief_worlds(m, o, worlds, mult, human_mask, human_t, human_eps, rng, layouts) != 0) return chosen;
  int everywhere[13];
  for (int j = 0; j < k; j++) everywhere[j] = 1;
  for (int w = 0; w < worlds; w++) {
    if (chosen_optimal(eq, &layouts[w], chosen, team) == 1) return chosen;
    double vals[13], top = -1e300;
    for (int j = 0; j < k; j++) {
      TcDeal child = layouts[w];
      if (tc_apply(&child, ids[j]) != 0) return chosen;
      vals[j] = solved_value(eq, child, team);
      if (vals[j] > top) top = vals[j];
    }
    for (int j = 0; j < k; j++) everywhere[j] &= vals[j] >= top - 1e-12;
  }
  for (int j = 0; j < k; j++) if (everywhere[j]) return ids[j];
  return chosen;
}

int tc_lite_belief_net(const TcMlp *m, const double *eq, const TcObs *o, int chosen, int worlds, int mult,
                       uint64_t *rng) {
  return tc_lite_belief_net_h(m, eq, o, chosen, worlds, mult, 0, 4.0, 0.8, rng);
}

// The whole net (C1): the gate, then steps 2-3, people's moves read with
// their own setting (human_mask: their seats; 0: every seat as a bot).
int tc_lite_net_h(const TcMlp *m, const double *eq, const TcObs *o, int chosen, int worlds, int mult,
                  int human_mask, double human_t, double human_eps, uint64_t *gate_rng, uint64_t *belief_rng) {
  TcDeal w0;
  if (tc_sample_world(o, gate_rng, &w0) != 0 || chosen_optimal(eq, &w0, chosen, o->seat & 1) == 1) return chosen;
  return tc_lite_belief_net_h(m, eq, o, chosen, worlds, mult, human_mask, human_t, human_eps, belief_rng);
}

// C1 reading every seat as a bot.
int tc_lite_net(const TcMlp *m, const double *eq, const TcObs *o, int chosen, int worlds, int mult,
                uint64_t *gate_rng, uint64_t *belief_rng) {
  return tc_lite_net_h(m, eq, o, chosen, worlds, mult, 0, 4.0, 0.8, gate_rng, belief_rng);
}
