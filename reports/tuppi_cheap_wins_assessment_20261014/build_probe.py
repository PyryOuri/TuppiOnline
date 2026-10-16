#!/usr/bin/env python3
"""Capture the tiny DD implementation and compile a separate probe library."""
from pathlib import Path
import json
import hashlib
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
native = ROOT / "TuppiAI/native"
capture = OUT / "source_capture"
capture.mkdir(exist_ok=True)
original = (native / "tuppi_dd.c").read_text()
modified = original.replace("int tc_dd_team0_tricks(const TcDeal *d)", "int review_full_tricks(const TcDeal *d)")
needle = "static int search(const Ctx *x, Pos *p, int alpha, int beta) {"
assert modified.count(needle) == 1
modified = modified.replace(needle, "static long review_nodes = 0, review_probes = 0;\n" + needle + "\n  review_nodes++;")
needle = "int review_full_tricks(const TcDeal *d) {"
modified = modified.replace(needle, needle + "\n  review_nodes = review_probes = 0;")
needle = "Pos q = p;\n    if (search(&x, &q, m - 1, m)"
assert modified.count(needle) == 1
modified = modified.replace(needle, "Pos q = p;\n    review_probes++;\n    if (search(&x, &q, m - 1, m)")
(capture / "tuppi_dd_original.c").write_text(original)
(capture / "tuppi_core.h").write_bytes((native / "tuppi_core.h").read_bytes())
suffix = "\n" + (OUT / "dd_probe_suffix.c").read_text()
(capture / "dd_probe.c").write_text(modified + suffix)
# At a DD trick boundary, suit names have no effect on this pure trick-count
# function. This does NOT imply suit invariance for a learned rollout policy.
needle = "      c[q] |= 1ULL << j;\n    }\n  }\n}"
assert modified.count(needle) == 1
sort_suits = r'''
  u64 pattern[4];
  for (int s = 0; s < 4; s++) {
    pattern[s] = 0;
    for (int q = 0; q < 4; q++) pattern[s] |= ((c[q] >> (13*s)) & 0x1FFFULL) << (13*q);
  }
  for (int s = 1; s < 4; s++) {
    u64 x = pattern[s]; int j = s;
    while (j > 0 && pattern[j-1] > x) { pattern[j] = pattern[j-1]; j--; }
    pattern[j] = x;
  }
  for (int q = 0; q < 4; q++) {
    c[q] = 0;
    for (int s = 0; s < 4; s++) c[q] |= ((pattern[s] >> (13*q)) & 0x1FFFULL) << (13*s);
  }
'''
canon = modified.replace(needle, needle[:-1] + sort_suits + "}")
(capture / "dd_probe_suits.c").write_text(canon + suffix)
compiler = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], env={"DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer"}, text=True).strip()
cmd = [compiler, "-O3", "-Wall", "-Wextra", "-isysroot", sdk, "-dynamiclib", str(capture / "dd_probe.c"), "-o", str(OUT / "dd_probe.dylib")]
subprocess.run(cmd, check=True)
# Use an explicit argument list; both outputs stay under OUT.
canon_cmd = [compiler, "-O3", "-Wall", "-Wextra", "-isysroot", sdk, "-dynamiclib", str(capture / "dd_probe_suits.c"), "-o", str(OUT / "dd_probe_suits.dylib")]
subprocess.run(canon_cmd, check=True)
metadata = {"commands": [cmd, canon_cmd], "original_dd_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "scope": "Copied solver plus probe counters and payoff-bucket entrypoint; installed library unchanged."}
(OUT / "BUILD.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps({"probe_library": str(OUT / "dd_probe.dylib"), "original_dd_sha256": metadata["original_dd_sha256"]}))
