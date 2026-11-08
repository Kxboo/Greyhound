"""Finds functions a Workshop map needs that the mod's scripts don't have. Read-only.

The mod's copy of a script replaces a map's own copy of it. Two ways that stops the game at script linking:
- MISSING: another map script calls a function only the map's copy has: Unresolved external "XXXXXXXX".
- PARAMS: the function exists in ours, but the map calls it with more arguments than ours takes:
  Unresolved external "XXXXXXXX" with N parameters. Fix by adding optional arguments to ours (`arg = default`).
And one way that stops it on connect:
- SPLIT: the map ships both halves of a script (.gsc and .csc) and the mod zones only one. The map's other half then
  pairs with ours, and any clientfield only one side registers gives "Server Disconnected - Clientfield Mismatch".
  Fix by zoning both halves, or neither.

Only scripts the mod's zones actually list (core_mod.zone, zm_mod.zone and the zpkgs they include) count as ours.

Input is the folder acts writes with `acts ffrbo3 <map.ff>`:
    python map_script_check.py E:\\MZO_backups\\work\\<run>\\scriptparsetree_t7ff\\1c000a0d43534780

A result is only a lead: the mod's names are read from source, so a macro-made function can show as missing.
A server (.gsc) hit in a map that already got past script linking is one of those. Guide: _handoff/custom-map-fixes.md
"""
import pathlib
import re
import struct
import sys

MOD = pathlib.Path(r'D:\SteamLibrary\steamapps\common\Call of Duty Black Ops III\mods\modern_zombies_overhaul')
FUNCTION = re.compile(r'^\s*function\s+(?:autoexec\s+|private\s+)*([A-Za-z_]\w*)\s*\(([^)]*)\)', re.M)
COMMENTS = re.compile(r'/\*.*?\*/|//[^\n]*', re.S)
ZONES = ('core_mod.zone', 'zm_mod.zone')


def zoned_scripts(zone_source=None):
    """Script paths ('scripts/zm/x.gsc') the mod's zones list, following include,<name> to <name>.zpkg."""
    zone_source = zone_source or MOD / 'zone_source'
    found, seen = set(), set()
    pending = [zone_source / name for name in ZONES]
    while pending:
        path = pending.pop()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for line in path.read_text(encoding='latin1').splitlines():
            parts = [part.strip() for part in line.split('//')[0].split(',')]
            if len(parts) >= 2 and parts[0] == 'scriptparsetree':
                found.add(parts[1].replace('\\', '/').lower())
            elif len(parts) >= 2 and parts[0] == 'include':
                pending.append(zone_source / (parts[1] + '.zpkg'))
    return found


def script_hash(text):
    """The engine's name hash: FNV-1a 32 over the lowercase name, Treyarch's basis, one extra multiply."""
    value = 0x4B9ACE2F
    for byte in text.lower().encode():
        value = ((value ^ byte) * 0x1000193) & 0xFFFFFFFF
    return (value * 0x1000193) & 0xFFFFFFFF


def read_script(path):
    """Returns (exports, imports) of a compiled T7 script.

    exports: set of (namespace hash, name hash). imports: dict (namespace hash, name hash) -> most parameters any call
    passes (one import entry per distinct call shape; the u8 after the reference count is the parameter count).
    """
    data = path.read_bytes()
    exports_offset, imports_offset = struct.unpack_from('<II', data, 0x20)
    export_count, import_count = struct.unpack_from('<HH', data, 0x3A)
    exports = set()
    for index in range(export_count):
        _, _, name, namespace = struct.unpack_from('<IIII', data, exports_offset + index * 0x14)
        exports.add((namespace, name))
    imports = {}
    offset = imports_offset
    for _ in range(import_count):
        name, namespace, references, params = struct.unpack_from('<IIHB', data, offset)
        key = (namespace, name)
        imports[key] = max(imports.get(key, 0), params)
        offset += 12 + references * 4
    return exports, imports


def mod_functions(path):
    """name hash -> (name, parameter count) from the mod's source."""
    source = COMMENTS.sub('', path.read_text(encoding='latin1'))
    functions = {}
    for match in FUNCTION.finditer(source):
        args = match.group(2).strip()
        functions[script_hash(match.group(1))] = (match.group(1), args.count(',') + 1 if args else 0)
    if 'REGISTER_SYSTEM' in source:
        functions[script_hash('__init__sytem__')] = ('__init__sytem__', 0)
    return functions


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = pathlib.Path(sys.argv[1])
    scripts = {}
    for path in list(root.rglob('*.gscc')) + list(root.rglob('*.cscc')):
        scripts[path.relative_to(root).as_posix()[:-1]] = read_script(path)
    zoned = zoned_scripts()
    shared = {name: mod_functions(MOD / name) for name in scripts
              if name.lower() in zoned and (MOD / name).exists()}
    print(f'{len(scripts)} map scripts, {len(shared)} also in the mod:')
    for name in sorted(shared):
        print(f'  {name}')

    found = 0
    for name in sorted(shared):
        other = name[:-3] + ('csc' if name.endswith('.gsc') else 'gsc')
        if other in scripts and other not in shared:
            found += 1
            print(f'SPLIT   {name} is ours but the map\'s {other} is not replaced (clientfield mismatch risk)')
    for name, ours in sorted(shared.items()):
        for namespace, function in sorted(scripts[name][0]):
            calls = {other: imports[(namespace, function)] for other, (_, imports) in scripts.items()
                     if other != name and other[-3:] == name[-3:] and (namespace, function) in imports}
            if not calls:
                continue
            if function not in ours:
                found += 1
                print(f'MISSING {name} ns={namespace:08x} func={function:08x} used by {", ".join(sorted(calls))}')
                continue
            label, params = ours[function]
            short = sorted(f'{other} ({count})' for other, count in calls.items() if count > params)
            if short:
                found += 1
                print(f'PARAMS  {name} {label} takes {params}, called with more by {", ".join(short)}')
    print(f'{found} function(s) to check')


if __name__ == '__main__':
    main()
