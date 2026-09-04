"""Move a flat native terrain export beneath its immutable capture directory.

Greyhound does not classify derived output because it never creates any. Every
native artifact is source evidence and is therefore filed beneath ``capture/``.
"""

from __future__ import annotations

import argparse
import os
import pathlib as _tool_pathlib
import shutil
import sys as _tool_sys

_tool_sys.path.insert(0, str(_tool_pathlib.Path(__file__).resolve().parents[1]))
import tool_bootstrap as _tool_bootstrap

_tool_bootstrap.activate(__file__)
import layout  # noqa: E402


def _move_over(destination, source):
    if os.path.isdir(source):
        os.makedirs(destination, exist_ok=True)
        replaced = 0
        for entry in sorted(os.listdir(source)):
            replaced += _move_over(
                os.path.join(destination, entry), os.path.join(source, entry)
            )
        if not os.listdir(source):
            os.rmdir(source)
        return replaced
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    replaced = int(os.path.exists(destination))
    if replaced:
        os.remove(destination)
    shutil.move(source, destination)
    return replaced


def plan(root):
    root = os.path.abspath(root)
    return [
        (os.path.join(layout.capture_dir(root), name), os.path.join(root, name))
        for name in sorted(os.listdir(root))
        if name != layout.CAPTURE
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.export_dir)
    root_manifest = os.path.join(root, layout.MANIFEST)
    filed_manifest = layout.manifest_path(root)
    if os.path.exists(filed_manifest) and not os.path.exists(root_manifest):
        print(f"{root} is already organized")
        return 0
    if not os.path.exists(root_manifest):
        raise SystemExit(f"{root} has no {layout.MANIFEST}; not a terrain export")

    refiling = os.path.exists(filed_manifest)
    if refiling and os.path.getmtime(root_manifest) <= os.path.getmtime(filed_manifest):
        print(f"{root} already contains a newer sealed capture; leaving it unchanged")
        return 0

    moves = plan(root)
    print(f"{root}: {len(moves)} source entries -> {layout.CAPTURE}/")
    if args.dry_run:
        return 0

    replaced = 0
    for destination, source in moves:
        if refiling:
            replaced += _move_over(destination, source)
        else:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.move(source, destination)

    if not layout.is_organized(root):
        raise SystemExit("source organization finished without a capture manifest")
    print(f"source capture organized; replaced {replaced} prior file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
