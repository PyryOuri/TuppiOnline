#ifndef TUPPI_MLP_H
#define TUPPI_MLP_H
#include <stdint.h>
typedef struct TcMlpS TcMlp;
TcMlp *tc_mlp_new(int in_dim, int width, int blocks, int out_dim, int encoder, const float *params);
void tc_mlp_free(TcMlp *m);
int tc_mlp_encoder(const TcMlp *m);
void tc_mlp_forward(const TcMlp *m, const uint8_t *feat, int rows, float *out);
#endif
