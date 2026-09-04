"""On-disk contract for a sealed Greyhound terrain source export."""

from __future__ import annotations

import os


CAPTURE = "capture"
MANIFEST = "terraingfx.json"


def capture_dir(root):
    return os.path.join(os.path.abspath(root), CAPTURE)


def capture(root, *parts):
    cleaned = []
    for part in parts:
        cleaned.extend(str(part).replace("\\", "/").split("/"))
    return os.path.join(capture_dir(root), *[part for part in cleaned if part])


def manifest_path(root):
    return capture(root, MANIFEST)


def is_organized(root):
    return os.path.exists(manifest_path(root))
