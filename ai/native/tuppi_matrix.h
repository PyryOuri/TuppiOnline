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
  int r = 0;
#if defined(__wasm_simd128__) && !defined(TC_WASM_REFERENCE)
  /* Two rows by sixteen outputs: reuse each input splat across four SIMD
   * accumulators and each weight load across both rows. Each output still
   * adds products in exactly k=0..inner-1 order, without fused operations. */
  for (; r + 1 < rows; r += 2) {
    int c = 0;
    for (; c + 16 <= cols; c += 16) {
      v128_t x0 = wasm_f32x4_splat(0), x1 = x0, x2 = x0, x3 = x0;
      v128_t y0 = x0, y1 = x0, y2 = x0, y3 = x0;
      for (int k = 0; k < inner; ++k) {
        const v128_t av = wasm_f32x4_splat(a[(size_t)r * lda + k]);
        const v128_t bv = wasm_f32x4_splat(a[(size_t)(r + 1) * lda + k]);
        const float *weight = b + (size_t)k * cols + c;
        const v128_t w0 = wasm_v128_load(weight), w1 = wasm_v128_load(weight + 4);
        const v128_t w2 = wasm_v128_load(weight + 8), w3 = wasm_v128_load(weight + 12);
        x0 = wasm_f32x4_add(x0, wasm_f32x4_mul(av, w0));
        x1 = wasm_f32x4_add(x1, wasm_f32x4_mul(av, w1));
        x2 = wasm_f32x4_add(x2, wasm_f32x4_mul(av, w2));
        x3 = wasm_f32x4_add(x3, wasm_f32x4_mul(av, w3));
        y0 = wasm_f32x4_add(y0, wasm_f32x4_mul(bv, w0));
        y1 = wasm_f32x4_add(y1, wasm_f32x4_mul(bv, w1));
        y2 = wasm_f32x4_add(y2, wasm_f32x4_mul(bv, w2));
        y3 = wasm_f32x4_add(y3, wasm_f32x4_mul(bv, w3));
      }
      float *x = out + (size_t)r * ldc + c, *y = x + ldc;
      wasm_v128_store(x, x0); wasm_v128_store(x + 4, x1);
      wasm_v128_store(x + 8, x2); wasm_v128_store(x + 12, x3);
      wasm_v128_store(y, y0); wasm_v128_store(y + 4, y1);
      wasm_v128_store(y + 8, y2); wasm_v128_store(y + 12, y3);
    }
    for (; c + 4 <= cols; c += 4) {
      v128_t x = wasm_f32x4_splat(0), y = x;
      for (int k = 0; k < inner; ++k) {
        const v128_t weight = wasm_v128_load(b + (size_t)k * cols + c);
        x = wasm_f32x4_add(x, wasm_f32x4_mul(wasm_f32x4_splat(a[(size_t)r * lda + k]), weight));
        y = wasm_f32x4_add(y, wasm_f32x4_mul(wasm_f32x4_splat(a[(size_t)(r + 1) * lda + k]), weight));
      }
      wasm_v128_store(out + (size_t)r * ldc + c, x);
      wasm_v128_store(out + (size_t)(r + 1) * ldc + c, y);
    }
    for (; c < cols; ++c) {
      float x = 0, y = 0;
      for (int k = 0; k < inner; ++k) {
        const float weight = b[(size_t)k * cols + c];
        x += a[(size_t)r * lda + k] * weight;
        y += a[(size_t)(r + 1) * lda + k] * weight;
      }
      out[(size_t)r * ldc + c] = x;
      out[(size_t)(r + 1) * ldc + c] = y;
    }
  }
#endif
  for (; r < rows; ++r) {
    int c = 0;
#ifdef __wasm_simd128__
#if !defined(TC_WASM_REFERENCE)
    for (; c + 16 <= cols; c += 16) {
      v128_t s0 = wasm_f32x4_splat(0), s1 = s0, s2 = s0, s3 = s0;
      for (int k = 0; k < inner; ++k) {
        const v128_t value = wasm_f32x4_splat(a[(size_t)r * lda + k]);
        const float *weight = b + (size_t)k * cols + c;
        s0 = wasm_f32x4_add(s0, wasm_f32x4_mul(value, wasm_v128_load(weight)));
        s1 = wasm_f32x4_add(s1, wasm_f32x4_mul(value, wasm_v128_load(weight + 4)));
        s2 = wasm_f32x4_add(s2, wasm_f32x4_mul(value, wasm_v128_load(weight + 8)));
        s3 = wasm_f32x4_add(s3, wasm_f32x4_mul(value, wasm_v128_load(weight + 12)));
      }
      float *target = out + (size_t)r * ldc + c;
      wasm_v128_store(target, s0); wasm_v128_store(target + 4, s1);
      wasm_v128_store(target + 8, s2); wasm_v128_store(target + 12, s3);
    }
#endif
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
