// Native forward pass of tuppi_ai.model.QNet, for rollouts without Python.
//
// QNet: h = relu(W_in x + b_in); for each block: h += fc2(relu(fc1(LN(h))));
// out = W_out relu(LN(h)) + b_out. Inputs are 0/1 features, so the first layer
// is a sum of weight columns over active features. Dense layers use
// Accelerate's sgemm. Results match PyTorch to float rounding, not bitwise.
#define ACCELERATE_NEW_LAPACK
#include <Accelerate/Accelerate.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"
#include "tuppi_mlp.h"

#define MAX_BLOCKS 8

struct TcMlpS {
  int in_dim, width, blocks, out_dim, encoder;
  float *w_in_t;  // [in_dim][width]: column j of W_in, contiguous
  float *b_in;
  float *ln_g[MAX_BLOCKS], *ln_b[MAX_BLOCKS];
  float *w1[MAX_BLOCKS], *b1[MAX_BLOCKS], *w2[MAX_BLOCKS], *b2[MAX_BLOCKS];
  float *lnf_g, *lnf_b, *w_out, *b_out;  // w_out: [out_dim][width]
};

static float *copy_floats(const float *src, size_t n) {
  float *d = malloc(sizeof(float) * n);
  memcpy(d, src, sizeof(float) * n);
  return d;
}

// `params` holds, in order: W_in [width][in_dim], b_in, then per block
// LN gamma, LN beta, W1 [width][width], b1, W2, b2, then final LN gamma, beta,
// W_out [out_dim][width], b_out - exactly the PyTorch state_dict layout.
TcMlp *tc_mlp_new(int in_dim, int width, int blocks, int out_dim, int encoder, const float *params) {
  if (blocks > MAX_BLOCKS || in_dim > 2048) return NULL;  // first_layer_row lists at most 2048 features
  TcMlp *m = calloc(1, sizeof *m);
  m->in_dim = in_dim; m->width = width; m->blocks = blocks; m->out_dim = out_dim; m->encoder = encoder;
  const float *p = params;
  m->w_in_t = malloc(sizeof(float) * (size_t)in_dim * width);
  for (int r = 0; r < width; r++)
    for (int j = 0; j < in_dim; j++) m->w_in_t[(size_t)j * width + r] = p[(size_t)r * in_dim + j];
  p += (size_t)width * in_dim;
  m->b_in = copy_floats(p, width); p += width;
  for (int b = 0; b < blocks; b++) {
    m->ln_g[b] = copy_floats(p, width); p += width;
    m->ln_b[b] = copy_floats(p, width); p += width;
    m->w1[b] = copy_floats(p, (size_t)width * width); p += (size_t)width * width;
    m->b1[b] = copy_floats(p, width); p += width;
    m->w2[b] = copy_floats(p, (size_t)width * width); p += (size_t)width * width;
    m->b2[b] = copy_floats(p, width); p += width;
  }
  m->lnf_g = copy_floats(p, width); p += width;
  m->lnf_b = copy_floats(p, width); p += width;
  m->w_out = copy_floats(p, (size_t)out_dim * width); p += (size_t)out_dim * width;
  m->b_out = copy_floats(p, out_dim);
  return m;
}

void tc_mlp_free(TcMlp *m) {
  if (!m) return;
  free(m->w_in_t); free(m->b_in);
  for (int b = 0; b < m->blocks; b++) {
    free(m->ln_g[b]); free(m->ln_b[b]); free(m->w1[b]); free(m->b1[b]); free(m->w2[b]); free(m->b2[b]);
  }
  free(m->lnf_g); free(m->lnf_b); free(m->w_out); free(m->b_out);
  free(m);
}

int tc_mlp_encoder(const TcMlp *m) { return m->encoder; }

static void layer_norm_row(const float *xr, float *yr, int width, const float *g, const float *b) {
  double mean = 0.0, var = 0.0;
  for (int i = 0; i < width; i++) mean += xr[i];
  mean /= width;
  for (int i = 0; i < width; i++) { double d = xr[i] - mean; var += d * d; }
  var /= width;
  float inv = (float)(1.0 / sqrt(var + 1e-5));
  float mu = (float)mean;
  for (int i = 0; i < width; i++) yr[i] = (xr[i] - mu) * inv * g[i] + b[i];
}

// Four rows at a time: each row's double-precision sums run in exactly the
// same order as layer_norm_row (so the result is bitwise the same), but the
// four independent dependency chains overlap instead of waiting on each other.
static void layer_norm(const float *x, float *y, int rows, int width, const float *g, const float *b) {
  int r = 0;
  for (; r + 4 <= rows; r += 4) {
    const float *x0 = x + (size_t)r * width, *x1 = x0 + width, *x2 = x1 + width, *x3 = x2 + width;
    double m0 = 0.0, m1 = 0.0, m2 = 0.0, m3 = 0.0;
    for (int i = 0; i < width; i++) { m0 += x0[i]; m1 += x1[i]; m2 += x2[i]; m3 += x3[i]; }
    m0 /= width; m1 /= width; m2 /= width; m3 /= width;
    double v0 = 0.0, v1 = 0.0, v2 = 0.0, v3 = 0.0;
    for (int i = 0; i < width; i++) {
      double d0 = x0[i] - m0, d1 = x1[i] - m1, d2 = x2[i] - m2, d3 = x3[i] - m3;
      v0 += d0 * d0; v1 += d1 * d1; v2 += d2 * d2; v3 += d3 * d3;
    }
    const double mean[4] = {m0, m1, m2, m3}, var[4] = {v0 / width, v1 / width, v2 / width, v3 / width};
    for (int k = 0; k < 4; k++) {
      const float *xr = x + (size_t)(r + k) * width;
      float *yr = y + (size_t)(r + k) * width;
      float inv = (float)(1.0 / sqrt(var[k] + 1e-5));
      float mu = (float)mean[k];
      for (int i = 0; i < width; i++) yr[i] = (xr[i] - mu) * inv * g[i] + b[i];
    }
  }
  for (; r < rows; r++) layer_norm_row(x + (size_t)r * width, y + (size_t)r * width, width, g, b);
}

// First layer of one row: b_in plus the weight columns of the active (1)
// features, added in increasing feature order - the order of the plain loop,
// so the sums are bitwise the same - then ReLU. The active features are found
// eight bytes at a time, and the sum is kept in registers one 32-wide tile at
// a time instead of re-reading and re-writing the whole row per feature.
#define TILE 32
static void first_layer_row(const TcMlp *m, const uint8_t *fr, float *hr) {
  const int W = m->width, D = m->in_dim;
  int active[2048], na = 0;
  int j = 0;
  for (; j + 8 <= D; j += 8) {
    uint64_t word;
    memcpy(&word, fr + j, 8);
    if (!word) continue;
    for (int t = 0; t < 8; t++) if (fr[j + t]) active[na++] = j + t;
  }
  for (; j < D; j++) if (fr[j]) active[na++] = j;
  int i0 = 0;
  for (; i0 + TILE <= W; i0 += TILE) {
    float acc[TILE];
    memcpy(acc, m->b_in + i0, sizeof acc);
    for (int a = 0; a < na; a++) {
      const float *col = m->w_in_t + (size_t)active[a] * W + i0;
      for (int t = 0; t < TILE; t++) acc[t] += col[t];
    }
    for (int t = 0; t < TILE; t++) hr[i0 + t] = acc[t] < 0 ? 0 : acc[t];
  }
  for (; i0 < W; i0++) {
    float v = m->b_in[i0];
    for (int a = 0; a < na; a++) v += m->w_in_t[(size_t)active[a] * W + i0];
    hr[i0] = v < 0 ? 0 : v;
  }
}

// out[rows][out_dim] for 0/1 features feat[rows][in_dim] (uint8).
void tc_mlp_forward(const TcMlp *m, const uint8_t *feat, int rows, float *out) {
  const int W = m->width;
  float *h = malloc(sizeof(float) * (size_t)rows * W);
  float *t = malloc(sizeof(float) * (size_t)rows * W);
  float *u = malloc(sizeof(float) * (size_t)rows * W);
  for (int r = 0; r < rows; r++) first_layer_row(m, feat + (size_t)r * m->in_dim, h + (size_t)r * W);
  for (int b = 0; b < m->blocks; b++) {
    layer_norm(h, t, rows, W, m->ln_g[b], m->ln_b[b]);
    cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, W, W, 1.0f, t, W, m->w1[b], W, 0.0f, u, W);
    for (int r = 0; r < rows; r++) {
      float *ur = u + (size_t)r * W;
      for (int i = 0; i < W; i++) { float v = ur[i] + m->b1[b][i]; ur[i] = v > 0 ? v : 0; }
    }
    cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, W, W, 1.0f, u, W, m->w2[b], W, 0.0f, t, W);
    for (int r = 0; r < rows; r++) {
      float *hr = h + (size_t)r * W, *tr = t + (size_t)r * W;
      for (int i = 0; i < W; i++) hr[i] += tr[i] + m->b2[b][i];
    }
  }
  layer_norm(h, t, rows, W, m->lnf_g, m->lnf_b);
  for (size_t i = 0; i < (size_t)rows * W; i++) if (t[i] < 0) t[i] = 0;
  cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, m->out_dim, W, 1.0f, t, W, m->w_out, W, 0.0f,
              out, m->out_dim);
  for (int r = 0; r < rows; r++)
    for (int i = 0; i < m->out_dim; i++) out[(size_t)r * m->out_dim + i] += m->b_out[i];
  free(h); free(t); free(u);
}

// ------------------------------------------------ incremental first layer
// For self-play rollouts (tuppi_env.c, tc_env_set_incremental): the caller
// keeps each seat's first-layer pre-activation and updates it by the columns
// of the features that changed. Not bitwise equal to tc_mlp_forward (the sums
// run in another order); never used by the search's exact path.
int tc_mlp_width(const TcMlp *m) { return m->width; }
int tc_mlp_in_dim(const TcMlp *m) { return m->in_dim; }
void tc_mlp_h0_init(const TcMlp *m, float *h) { memcpy(h, m->b_in, sizeof(float) * (size_t)m->width); }
void tc_mlp_h0_add(const TcMlp *m, float *h, int feature, float sign) {
  const float *col = m->w_in_t + (size_t)feature * m->width;
  for (int i = 0; i < m->width; i++) h[i] += sign * col[i];
}

// As tc_mlp_forward, from given first-layer pre-activations h0[rows][width].
void tc_mlp_forward_h0(const TcMlp *m, const float *h0, int rows, float *out) {
  const int W = m->width;
  float *h = malloc(sizeof(float) * (size_t)rows * W);
  float *t = malloc(sizeof(float) * (size_t)rows * W);
  float *u = malloc(sizeof(float) * (size_t)rows * W);
  for (size_t i = 0; i < (size_t)rows * W; i++) h[i] = h0[i] < 0 ? 0 : h0[i];
  for (int b = 0; b < m->blocks; b++) {
    layer_norm(h, t, rows, W, m->ln_g[b], m->ln_b[b]);
    cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, W, W, 1.0f, t, W, m->w1[b], W, 0.0f, u, W);
    for (int r = 0; r < rows; r++) {
      float *ur = u + (size_t)r * W;
      for (int i = 0; i < W; i++) { float v = ur[i] + m->b1[b][i]; ur[i] = v > 0 ? v : 0; }
    }
    cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, W, W, 1.0f, u, W, m->w2[b], W, 0.0f, t, W);
    for (int r = 0; r < rows; r++) {
      float *hr = h + (size_t)r * W, *tr = t + (size_t)r * W;
      for (int i = 0; i < W; i++) hr[i] += tr[i] + m->b2[b][i];
    }
  }
  layer_norm(h, t, rows, W, m->lnf_g, m->lnf_b);
  for (size_t i = 0; i < (size_t)rows * W; i++) if (t[i] < 0) t[i] = 0;
  cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasTrans, rows, m->out_dim, W, 1.0f, t, W, m->w_out, W, 0.0f,
              out, m->out_dim);
  for (int r = 0; r < rows; r++)
    for (int i = 0; i < m->out_dim; i++) out[(size_t)r * m->out_dim + i] += m->b_out[i];
  free(h); free(t); free(u);
}
