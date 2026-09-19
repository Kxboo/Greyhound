"""Resolve the same game-organized tool tree in source and packaged runtimes."""

from __future__ import annotations

import pathlib
import sys


CATEGORIES = (
    "shared/core", "shared/capture", "shared/brushes", "shared/runtime",
    "shared/name_db", "black_ops_3/reference",
    "cold_war/capture", "cold_war/placements", "cold_war/brushes", "cold_war/research",
    "black_ops_4/capture", "black_ops_4/placements", "black_ops_4/brushes", "black_ops_4/research",
)


def tool_root(file_name) -> pathlib.Path:
    for directory in pathlib.Path(file_name).resolve().parents:
        if (directory / "tool_bootstrap.py").is_file():
            return directory
    raise FileNotFoundError("Cannot locate Greyhound's tool_bootstrap.py")


def activate(file_name) -> pathlib.Path:
    root = tool_root(file_name)
    paths = [root / name for name in CATEGORIES] + [root]
    for path in paths:
        value = str(path)
        while value in sys.path:
            sys.path.remove(value)
    for path in reversed(paths):
        if path.is_dir():
            sys.path.insert(0, str(path))
    return root
