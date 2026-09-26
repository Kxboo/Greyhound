"""Convert build_bo4_map_usd.py's chunk .usda files to binary .usdc (run with a Python that has pxr).

Each .usdc is reopened and its prims counted against the .usda before the text
file is removed (--keep keeps it). Afterwards rerun build_bo4_map_usd.py with
--root-only so the root points at the .usdc files.

  usd_crate.py OUTPUT [--keep]
"""
import argparse
import sys
from pathlib import Path

from pxr import Sdf, Usd


def convert(usda, keep=False):
    usdc = usda.with_suffix(".usdc")
    layer = Sdf.Layer.FindOrOpen(str(usda))
    if layer is None:
        raise RuntimeError(f"{usda}: does not open")
    if not layer.Export(str(usdc)):
        raise RuntimeError(f"{usda}: export failed")
    text_stage, crate_stage = Usd.Stage.Open(layer), Usd.Stage.Open(str(usdc))
    a = sum(1 for _ in text_stage.Traverse())
    b = sum(1 for _ in crate_stage.Traverse())
    if a != b:
        raise RuntimeError(f"{usdc}: {b} prims, the text layer has {a}")
    size = usda.stat().st_size, usdc.stat().st_size
    if not keep:
        usda.unlink()
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--keep", action="store_true", help="keep the .usda files")
    args = parser.parse_args()
    files = sorted((args.output / "terrain").glob("sector_*/chunk_*.usda"))
    text = crate = 0
    for k, f in enumerate(files, 1):
        a, b = convert(f, args.keep)
        text, crate = text + a, crate + b
        print(f"{k}/{len(files)} {f.relative_to(args.output)}: {a / 1e6:.1f} MB -> {b / 1e6:.1f} MB", flush=True)
    print(f"total {text / 1e9:.2f} GB text -> {crate / 1e9:.2f} GB crate", flush=True)


if __name__ == "__main__":
    sys.exit(main())
