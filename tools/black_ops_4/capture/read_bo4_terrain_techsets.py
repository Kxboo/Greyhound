"""Read the technique set of every terrain layer material from a running BO4 (read-only).

The engine streams a sector's 112-byte layer records (t14) only near the
player, so a capture holds records for the sectors around the player and none
for the rest. A layer's shading flags come from its material's technique set:
materials that share a technique set share every flag the terrain pixel
shader reads, except 0x8 (gloss mask), which follows the bound gloss map.
bo4_terrain_records uses this to rebuild records for the materials no
capture reached.

A material keeps its technique set pointer at +0x30; the technique set's
first qword is its name hash (low 60 bits). Only those two reads are made per
material. Writes <package>/capture/material_techsets.json.

The package's material pointers are only valid in the game session it was
captured in. --probe takes them instead from the terraingfx_probe.json of a
capture made in the running session, slot for slot: the package names each
sector's layer materials by slot, and the probe gives the same slots' material
pointers.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse
import ctypes as c
import json
import struct
import subprocess
from pathlib import Path

MATERIAL_TECHSET_OFFSET = 0x30
NAME_MASK = 0x0FFFFFFFFFFFFFFF


def open_process(image="BlackOps4.exe"):
    out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"]).decode()
    if image.lower() not in out.lower():
        raise RuntimeError(f"{image} is not running")
    pid = int(out.split(",")[1].strip('"'))
    k = c.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [c.c_uint32, c.c_int, c.c_uint32]
    k.OpenProcess.restype = c.c_void_p
    k.ReadProcessMemory.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    handle = k.OpenProcess(0x410, False, pid)      # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    if not handle:
        raise OSError(c.get_last_error())

    def read(at, n):
        buf, got = c.create_string_buffer(n), c.c_size_t()
        if not k.ReadProcessMemory(handle, at, buf, n, c.byref(got)) or got.value != n:
            raise OSError(c.get_last_error(), f"read {n} bytes at {at:#x}")
        return buf.raw

    return read


def probe_pointers(doc, probe):
    """Material name -> its pointer in the session the capture behind probe (terraingfx_probe.json) ran in."""
    slots = {}
    for s in json.loads(Path(probe).read_text())["sectors"]:
        for side in s.get("side_arrays", []):
            for layer in side.get("layers") or []:
                if layer.get("material"):
                    slots[(s["sector"], layer["layer"])] = layer["material"]
    out = {}
    for s in doc["sectors"]:
        for layer in s["layers"]:
            pointer = slots.get((s["sector"], layer["slot"]))
            if pointer is None:
                raise ValueError(f"sector {s['sector']} slot {layer['slot']} is not in {probe}")
            if out.setdefault(layer["material"], pointer) != pointer:
                raise ValueError(f"{layer['material']} has two pointers in {probe}: {out[layer['material']]}, {pointer}")
    return out


def capture(package, probe=None):
    package = Path(package)
    doc = json.loads((package / "capture" / "terraingfx.json").read_text())
    live = probe_pointers(doc, probe) if probe else {}
    read = open_process()
    rows = {}
    for m in doc["materials"]:
        pointer = int(live[m["name"]] if probe else m["pointer"], 16)
        head = read(pointer, MATERIAL_TECHSET_OFFSET + 8)
        name = struct.unpack_from("<Q", head, 0)[0] & NAME_MASK
        techset = struct.unpack_from("<Q", head, MATERIAL_TECHSET_OFFSET)[0]
        expected = m.get("hash")
        if isinstance(expected, str) and int(expected, 16) != name:
            raise ValueError(f"{m['name']}: material at {pointer:#x} hashes {name:#x}, not {expected}; "
                             "the capture is from another session")
        rows[m["name"]] = {"pointer": "0x%X" % pointer, "techset": "0x%X" % techset,
                           "techset_name_hash": "0x%X" % (struct.unpack("<Q", read(techset, 8))[0] & NAME_MASK)}
    out = {"schema": "superterrain-bo4-material-techsets-v1", "material_offset": "0x%X" % MATERIAL_TECHSET_OFFSET,
           "materials": rows}
    (package / "capture" / "material_techsets.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", type=Path, help="package_bo4_terrain.py output")
    parser.add_argument("--probe", type=Path,
                        help="terraingfx_probe.json of a capture made in the running session, when the package's "
                             "own capture is from an earlier one")
    args = parser.parse_args()
    out = capture(args.package, args.probe)
    print(len(out["materials"]), "materials,", len({r["techset"] for r in out["materials"].values()}), "technique sets")


if __name__ == "__main__":
    main()
