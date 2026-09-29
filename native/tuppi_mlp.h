#ifndef TUPPI_MLP_H
#define TUPPI_MLP_H
#include <stdint.h>
typedef struct TcMlpS TcMlp;
TcMlp *tc_mlp_new(int in_dim, int width, int blocks, int out_dim, int encoder, const float *params);
void tc_mlp_free(TcMlp *m);
int tc_mlp_encoder(const TcMlp *m);
void tc_mlp_forward(const TcMlp *m, const uint8_t *feat, int rows, float *out);
// Incremental first layer (self-play only; not bitwise equal to tc_mlp_forward).
int tc_mlp_width(const TcMlp *m);
int tc_mlp_in_dim(const TcMlp *m);
void tc_mlp_h0_init(const TcMlp *m, float *h);
void tc_mlp_h0_add(const TcMlp *m, float *h, int feature, float sign);
void tc_mlp_forward_h0(const TcMlp *m, const float *h0, int rows, float *out);
#endif
