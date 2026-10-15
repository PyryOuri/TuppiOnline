#ifndef TUPPI_MATRIX_H
#define TUPPI_MATRIX_H

#ifndef TC_PORTABLE
#define ACCELERATE_NEW_LAPACK
#include <Accelerate/Accelerate.h>
#else
#ifdef TC_HOSTED_BLAS
/* Portable weights are stored inner-by-output. Optimised native BLAS can
 * multiply that layout directly; browser builds keep explicit SIMD below. */
#ifdef __APPLE__
#define ACCELERATE_NEW_LAPACK
#include <Accelerate/Accelerate.h>
#else
#include <cblas.h>
#endif
static void tc_hosted_sgemm(int order, int ta, int tb, int rows, int cols, int inner,
                           float alpha, const float *a, int lda, const float *b,
                           int ldb, float beta, float *out, int ldc) {
  (void)order; (void)ta; (void)tb; (void)ldb;
  cblas_sgemm(CblasRowMajor, CblasNoTrans, CblasNoTrans, rows, cols, inner,
              alpha, a, lda, b, cols, beta, out, ldc);
}
#define cblas_sgemm tc_hosted_sgemm
#else
/* The MLP only calls row-major A * B-transpose, alpha=1, beta=0. Keep
 * float32 accumulation order explicit; SIMD runs independent outputs. */
#include <stddef.h>
#ifdef __wasm_simd128__
#include <wasm_simd128.h>
#elif defined(__SSE2__)
#include <emmintrin.h>
#elif defined(__ARM_NEON)
#include <arm_neon.h>
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
#if defined(__SSE2__) && !defined(__wasm_simd128__)
    for (; c + 4 <= cols; c += 4) {
      __m128 sum = _mm_setzero_ps();
      for (int k = 0; k < inner; ++k)
        sum = _mm_add_ps(sum, _mm_mul_ps(_mm_set1_ps(a[(size_t)r * lda + k]),
                                       _mm_loadu_ps(b + (size_t)k * cols + c)));
      _mm_storeu_ps(out + (size_t)r * ldc + c, sum);
    }
#elif defined(__ARM_NEON) && !defined(__wasm_simd128__)
    for (; c + 4 <= cols; c += 4) {
      float32x4_t sum = vdupq_n_f32(0);
      for (int k = 0; k < inner; ++k)
        sum = vaddq_f32(sum, vmulq_f32(vdupq_n_f32(a[(size_t)r * lda + k]),
                                     vld1q_f32(b + (size_t)k * cols + c)));
      vst1q_f32(out + (size_t)r * ldc + c, sum);
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
#endif
