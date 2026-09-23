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
  if (blocks > MAX_BLOCKS) return NULL;
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

static void layer_norm(const float *x, float *y, int rows, int width, const float *g, const float *b) {
  for (int r = 0; r < rows; r++) {
    const float *xr = x + (size_t)r * width;
    float *yr = y + (size_t)r * width;
    double mean = 0.0, var = 0.0;
    for (int i = 0; i < width; i++) mean += xr[i];
    mean /= width;
    for (int i = 0; i < width; i++) { double d = xr[i] - mean; var += d * d; }
    var /= width;
    float inv = (float)(1.0 / sqrt(var + 1e-5));
    float mu = (float)mean;
    for (int i = 0; i < width; i++) yr[i] = (xr[i] - mu) * inv * g[i] + b[i];
  }
}

// out[rows][out_dim] for 0/1 features feat[rows][in_dim] (uint8).
void tc_mlp_forward(const TcMlp *m, const uint8_t *feat, int rows, float *out) {
  const int W = m->width;
  float *h = malloc(sizeof(float) * (size_t)rows * W);
  float *t = malloc(sizeof(float) * (size_t)rows * W);
  float *u = malloc(sizeof(float) * (size_t)rows * W);
  for (int r = 0; r < rows; r++) {
    float *hr = h + (size_t)r * W;
    memcpy(hr, m->b_in, sizeof(float) * W);
    const uint8_t *fr = feat + (size_t)r * m->in_dim;
    for (int j = 0; j < m->in_dim; j++) {
      if (!fr[j]) continue;
      const float *col = m->w_in_t + (size_t)j * W;
      for (int i = 0; i < W; i++) hr[i] += col[i];
    }
    for (int i = 0; i < W; i++) if (hr[i] < 0) hr[i] = 0;
  }
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
