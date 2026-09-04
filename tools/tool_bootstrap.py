"""Make Greyhound's small source-capture helper tree importable."""

from __future__ import annotations

import pathlib
import sys


CATEGORIES = ("core", "capture")


def tool_root(file_name) -> pathlib.Path:
    directory = pathlib.Path(file_name).resolve().parent
    return directory.parent if directory.name in CATEGORIES else directory


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
