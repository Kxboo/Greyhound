"""Convert a local echo000/cod-name-db CSV checkout into a separate BO4 WNI set.

Does not modify the checkout or Greyhound's bundled databases. Only BO4's five
FNV1a asset-name files are imported; no network access or CDB runtime is needed.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import csv
import hashlib
import io
import json
import struct
from pathlib import Path

import lz4.block

FILES = ("fnv1a_xanims", "fnv1a_ximages", "fnv1a_xmaterials", "fnv1a_xmodels", "fnv1a_xsounds")
MASK = (1 << 60) - 1


def fnv(data):
    value = 0xCBF29CE484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001B3) & ((1 << 64) - 1)
    return value & MASK


def convert(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not (source / "csv").is_dir():
        candidates = list(source.glob("*/csv"))
        if len(candidates) == 1:
            source = candidates[0].parent
    # Preflight the complete set before writing anything.
    for stem in FILES:
        if not (source / "csv" / (stem + ".csv")).is_file():
            raise ValueError(f"Missing {stem}.csv under {source}")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "greyhound-echo000-bo4-names-v1",
              "repository": "https://github.com/echo000/cod-name-db", "source": str(source), "files": []}
    for stem in FILES:
        raw = (source / "csv" / (stem + ".csv")).read_bytes()
        entries, rejected, duplicates = {}, 0, 0
        ambiguous = set()
        for row in csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")):
            if len(row) != 2:
                rejected += 1
                continue
            try:
                key, name = int(row[0], 16) & MASK, row[1].encode("utf-8")
            except ValueError:
                rejected += 1
                continue
            if not name or b"\0" in name or fnv(name) != key:
                rejected += 1
                continue
            if key in ambiguous:
                continue
            if key in entries:
                if entries[key] != name:
                    # Both names hash correctly: retain the unresolved hash
                    # rather than silently select a CSV-order winner.
                    ambiguous.add(key)
                    del entries[key]
                    continue
                duplicates += 1
            entries[key] = name
        if not entries:
            raise ValueError(f"No verified BO4 names in {stem}")
        payload = b"".join(struct.pack("<Q", key) + name + b"\0" for key, name in sorted(entries.items()))
        packed = lz4.block.compress(payload, store_size=False)
        wni = struct.pack("<I H III", 0x20494E57, 1, len(entries), len(packed), len(payload)) + packed
        assert lz4.block.decompress(wni[18:], uncompressed_size=len(payload)) == payload
        target = output / (stem + ".wni")
        temp = target.with_suffix(".wni.tmp")
        temp.write_bytes(wni)
        temp.replace(target)
        item = {"file": target.name, "entries": len(entries), "rejected_invalid_rows": rejected,
                "ambiguous_hashes_excluded": [f"{key:x}" for key in sorted(ambiguous)],
                "duplicate_rows": duplicates, "source_sha256": hashlib.sha256(raw).hexdigest(),
                "wni_sha256": hashlib.sha256(wni).hexdigest(), "bytes": len(wni)}
        report["files"].append(item)
        print(f"{stem}: {len(entries):,} verified names; {rejected} rejected; {len(wni):,} bytes", flush=True)
    (output / "source.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.checkout, args.output)
