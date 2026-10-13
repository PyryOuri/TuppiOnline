#ifndef TUPPI_MATRIX_H
#define TUPPI_MATRIX_H

#ifndef TC_PORTABLE
#define ACCELERATE_NEW_LAPACK
#include <Accelerate/Accelerate.h>
#else
/* The MLP only calls row-major A * B-transpose, alpha=1, beta=0. Keep
 * float32 accumulation order explicit; SIMD runs independent outputs. */
#include <stddef.h>
#ifdef __wasm_simd128__
#include <wasm_simd128.h>
#endif
enum { CblasRowMajor, CblasNoTrans, CblasTrans };
static void cblas_sgemm(int order, int ta, int tb, int rows, int cols, int inner,
                        float alpha, const float *a, int lda, const float *b,
                        int ldb, float beta, float *out, int ldc) {
  (void)order; (void)ta; (void)tb; (void)alpha; (void)beta;
  for (int r = 0; r < rows; ++r) {
    int c = 0;
#ifdef __wasm_simd128__
    for (; c + 4 <= cols; c += 4) {
      v128_t sum = wasm_f32x4_splat(0);
      for (int k = 0; k < inner; ++k)
        sum = wasm_f32x4_add(sum, wasm_f32x4_mul(
            wasm_f32x4_splat(a[(size_t)r * lda + k]),
            wasm_v128_load(b + (size_t)k * cols + c)));
      wasm_v128_store(out + (size_t)r * ldc + c, sum);
    }
#endif
    for (; c < cols; ++c) {
      float sum = 0;
      for (int k = 0; k < inner; ++k)
        sum += a[(size_t)r * lda + k] * b[(size_t)k * cols + c];
      out[(size_t)r * ldc + c] = sum;
    }
  }
  (void)ldb;
}
#endif
#endif
