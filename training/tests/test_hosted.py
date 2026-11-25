"""T10: the files the hosted image is built from are exactly the released ones.

SOURCE.json records the size and SHA-256 of every file of the hosted release. Training
work must not change any of them, nor add files to the directories the image copies.
"""

from __future__ import annotations

import hashlib
import json

import tuppi_train

REPO = tuppi_train.REPO
IMAGE_DIRS = ("ai", "engine", "web", "qualification", "browser-source")
BUILD_OUTPUTS = {"libtuppi.so", "libtuppi.dylib"}


def test_hosted_files_are_untouched():
    listed = {entry["path"]: entry for entry in json.loads((REPO / "SOURCE.json").read_text())["files"]}
    assert len(listed) > 700
    changed = []
    for path, entry in listed.items():
        blob = (REPO / path).read_bytes() if (REPO / path).exists() else None
        if blob is None or len(blob) != entry["bytes"] or hashlib.sha256(blob).hexdigest() != entry["sha256"]:
            changed.append(path)
    assert not changed, f"hosted files differ from SOURCE.json: {changed[:10]}"


def test_nothing_added_to_the_image_directories():
    listed = {entry["path"] for entry in json.loads((REPO / "SOURCE.json").read_text())["files"]}
    extra = []
    for top in IMAGE_DIRS:
        for path in (REPO / top).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.name in BUILD_OUTPUTS:
                continue
            rel = path.relative_to(REPO).as_posix()
            if rel not in listed:
                extra.append(rel)
    assert not extra, f"files not in the hosted release: {extra[:10]}"
