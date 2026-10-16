#!/usr/bin/env python3
"""Build private baseline and reward-bucket libraries; never installs them."""
from __future__ import annotations
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path(__file__).resolve().parent
NATIVE = OUT / "frozen/ai/native"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"Expected exactly one source pattern: {old[:80]}")
    return source.replace(old, new)


DD_BUCKET = r'''
// Evaluator-private utility query. Exact-trick callers keep the old API.
float tc_dd_reward_bucket(const TcDeal *d, const float payoff[14]) {
  int base = d->team_tricks[0], remaining = 13 - (d->n_played >> 2);
  int cuts[13], n = 0;
  for (int i = 1; i <= remaining; i++)
    if (payoff[base+i] != payoff[base+i-1]) cuts[n++] = i;
  if (!n) return payoff[base];
  if (!tt_tls) tt_tls = calloc(1ULL << TTBITS, sizeof(TTE));
  const Ctx x = {tt_tls, 1, d->contract == TC_NOLO};
  Pos p; to_pos(d, &p);
  int lo = 0, hi = n;
  while (lo < hi) {
    int mid = (lo + hi) / 2, target = cuts[mid];
    Pos q = p;
    if (search(&x, &q, target-1, target) >= target) lo = mid+1;
    else hi = mid;
  }
  return payoff[base + (lo ? cuts[lo-1] : 0)];
}
'''

PAYOFF_MAP = r'''
// One root's read-only table, built from the actual loaded environment equity.
// All sampled rows of a root search share the root's score and dealer.
static int reward_bucket_enabled = 0;
void tc_set_reward_buckets(int on) { reward_bucket_enabled = on != 0; }
float tc_dd_reward_bucket(const TcDeal *d, const float payoff[14]);
static void reward_maps(const TcEnv *e, const TcObs *o, float out[2][2][14]) {
  TcDeal d; memset(&d, 0, sizeof d);
  d.dealer = o->dealer; d.score[0] = o->score[0]; d.score[1] = o->score[1];
  for (int contract = 0; contract < 2; contract++) for (int declarer = 0; declarer < 2; declarer++) {
    d.contract = contract; d.declarer = declarer;
    for (int t = 0; t < 14; t++) {
      tc_finish_with_tricks(&d, t);
      uint8_t after[2]; tc_next_score(d.score, d.winner_team, d.points, after);
      out[contract][declarer][t] = (float)(equity0(e, after[0], after[1], d.dealer+1)
                                           - equity0(e, d.score[0], d.score[1], d.dealer));
    }
  }
}
'''


def candidate_sources():
    sources = {p.name: p.read_text() for p in NATIVE.iterdir() if p.suffix in {".c", ".h"}}
    sources["tuppi_dd.c"] += DD_BUCKET
    source = sources["tuppi_env.c"]
    source = replace_once(source, "static void record_if_done(TcEnv *e, int i, double *total) {",
                          PAYOFF_MAP + "\nstatic void record_if_done(TcEnv *e, int i, double *total) {")
    # Scope changes to ordinary root play_out; a later learner loop contains
    # another identical solver call and must remain untouched.
    begin = source.index("static void play_out(")
    end = source.index("\nstatic int search_core", begin)
    prefix, suffix = source[:begin], source[end:]
    source = source[begin:end]
    source = replace_once(source, "const Leaf *leaf, Capture *cap) {\n  const int enc",
                          "const Leaf *leaf, Capture *cap, const float (*buckets)[2][14]) {\n"
                          "  // Certified rows have an abstract utility, not a fabricated terminal deal.\n"
                          "  uint8_t *utility_done = buckets ? calloc((size_t)n, 1) : NULL;\n  const int enc")
    source = replace_once(source,
        "if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left + (d->contract == TC_NOLO ? dd_extra_nolo : 0))",
        "if ((!utility_done || !utility_done[i]) && d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left + (d->contract == TC_NOLO ? dd_extra_nolo : 0))")
    source = replace_once(source,
        "            tc_finish_with_tricks(d, tc_dd_team0_tricks(d));\n            record_if_done(e, idx[j], total);",
        "            if (buckets) {\n"
        "              const int row = idx[j], decl = d->contract == TC_RAMI ? (d->declarer & 1) : 0;\n"
        "              total[row] += (double)tc_dd_reward_bucket(d, buckets[d->contract][decl]);\n"
        "              utility_done[row] = 1;\n"
        "            } else {\n"
        "              tc_finish_with_tricks(d, tc_dd_team0_tricks(d));\n"
        "              record_if_done(e, idx[j], total);\n"
        "            }")
    source = replace_once(source,
        "for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;",
        "for (int i = 0; i < n; i++) if ((!utility_done || !utility_done[i]) && e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;")
    source = replace_once(source,
        "      free(feat);\n      free(q);\n    });\n  }\n}",
        "      free(feat);\n      free(q);\n    });\n  }\n  free(utility_done);\n}")
    source = prefix + source + suffix
    source = replace_once(source,
        "  play_out(e, m, n, dd_left, rng, total, idx, use_leaf ? &leaf : NULL, NULL);",
        "  float maps[2][2][14];\n"
        "  const float (*bucket_maps)[2][14] = NULL;\n"
        "  if (reward_bucket_enabled && !use_leaf && dd_left > 0) { reward_maps(e, o, maps); bucket_maps = maps; }\n"
        "  play_out(e, m, n, dd_left, rng, total, idx, use_leaf ? &leaf : NULL, NULL, bucket_maps);")
    source = source.replace("play_out(e, m, n, dd_left, rng, total, idx, NULL, &cap);",
                            "play_out(e, m, n, dd_left, rng, total, idx, NULL, &cap, NULL);")
    source = source.replace("play_out(e, m, total_games, dd_left, rng, total, idx, NULL, NULL);",
                            "play_out(e, m, total_games, dd_left, rng, total, idx, NULL, NULL, NULL);")
    sources["tuppi_env.c"] = source
    return sources


def main():
    build = OUT / "builds"
    if build.exists():
        raise SystemExit("Private build directory exists; preserve it and use a new version for later changes.")
    compiler = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                                  env={"DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer"}, text=True).strip()
    candidate = candidate_sources()
    files = ["tuppi_core.c", "tuppi_env.c", "tuppi_search.c", "tuppi_dd.c", "tuppi_mlp.c", "tuppi_sooli.c", "tuppi_sooli_policy.c"]
    record = {"schema": "tuppi.cheap_wins.native_build.v1", "libraries": {}}
    for arm in ("rebuilt", "reward_bucket"):
        folder = build / arm
        folder.mkdir(parents=True)
        for name, text in candidate.items():
            original = (NATIVE / name).read_text()
            (folder / name).write_text(text if arm == "reward_bucket" else original)
            if arm == "reward_bucket" and text != original:
                (folder / (name + ".patch")).write_text("".join(difflib.unified_diff(original.splitlines(True), text.splitlines(True), fromfile="frozen/" + name, tofile="candidate/" + name)))
        library = folder / "libtuppi.dylib"
        command = [compiler, "-O3", "-Wall", "-Wextra", "-Wno-unused-parameter", "-isysroot", sdk, "-dynamiclib",
                   "-framework", "Accelerate", "-o", str(library), *[str(folder / name) for name in files]]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        (folder / "compiler.log").write_text(result.stdout + result.stderr)
        record["libraries"][arm] = {"command": command, "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                                    "source_hashes": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in candidate}}
    (OUT / "NATIVE_BUILD.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"built": list(record["libraries"]), "installed_library_unchanged": True}))


if __name__ == "__main__":
    main()
