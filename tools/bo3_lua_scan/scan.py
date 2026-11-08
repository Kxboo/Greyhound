#!/usr/bin/env python3
"""bo3_lua_scan: find Black Ops III Lua errors with no game running.

    python scan.py <file or folder> [...]            readable report
    python scan.py <file or folder> --json           machine readable, for scripts and agents
    python scan.py <file or folder> --static-only    syntax + globals only, no run pass

Exit code: 0 clean, 1 findings at or above --fail-on, 2 could not run. Standard library only. See README.md.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
LUA = os.path.join(HERE, "bin", "lua51.exe")
LUAC = os.path.join(HERE, "bin", "luac51.exe")
HARNESS = os.path.join(HERE, "runtime", "harness.lua")
MARK = "\x01BO3SCAN "
LUA_STD = {"assert", "collectgarbage", "dofile", "error", "gcinfo", "getfenv", "getmetatable", "ipairs", "load", "loadfile",
           "loadstring", "module", "newproxy", "next", "pairs", "pcall", "print", "rawequal", "rawget", "rawset", "require",
           "select", "setfenv", "setmetatable", "tonumber", "tostring", "type", "unpack", "xpcall", "_G", "_VERSION", "coroutine",
           "debug", "io", "math", "os", "package", "string", "table"}
# Exist in plain Lua, so the run pass can't see a problem, but L3akMod (the linker) fails on them with
# "attempt to index global 'ERR'" and never names the file. _handoff\lua-rules.md. A local from require("io") is fine.
LINKER_BANNED = {"io", "os", "getmetatable", "setmetatable", "rawset"}
NOT_ELEMENT_METHODS = {"lower", "upper", "sub", "len", "find", "gsub", "gmatch", "match", "rep", "byte", "format", "reverse"}
NATIVE_VALUES = {"Dvar"}
# what the game has loaded before a mod's Lua runs (the stock HUD and lobby both start from these)
BOOT = ["ui.LUI.lui", "ui.T6.CoDBase", "ui.uieditor.conditions", "ui.uieditor.actions", "ui.uieditor.datasources"]
SEVERITY = {"linker_global": "error", "syntax": "error", "load": "error", "build": "error", "missing_require": "error", "callback": "warning",
            "undefined_global": "warning", "not_zoned": "warning", "new_global": "warning", "callback_nil": "warning", "pcall": "note"}
RANK = {"note": 0, "warning": 1, "error": 2}
EXPLAIN = {"callback": "while a model callback ran with fake data (number 1)",
           "callback_nil": "while a model callback ran with no data, which a real model can have",
           "build": "while building the widget or menu", "pcall": "a pcall caught this, so it stays silent in the game", "load": "while the file loaded"}
# data the scanner invented can cause these: the code may be fine in a game
FAKE_DATA = ("attempt to compare", "got table", "attempt to perform arithmetic on field '?'", "a number value",
             "got number")
# decompiled stock names: stock's own code failed, on a stand-in or on dump damage more often than on the mod's input
DUMP_NAME = re.compile(r"f\d+_(?:local|arg)\d+|field '\?'")


def find_stock(start):
    env = os.environ.get("BO3_LUA_STOCK")
    if env:
        return env
    path = os.path.abspath(start)
    while True:
        dumps = os.path.join(path, "_extracted_source_files", "T7LuaRepo", "Dumps")
        if os.path.isdir(dumps):
            names = sorted(n for n in os.listdir(dumps) if n.startswith("PC_Ship"))
            if names:
                return os.path.join(dumps, names[-1])
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def find_root(path):
    """The folder a file's `require` paths start from: the parent of its ui/ or ui_mp/ folder."""
    path = os.path.abspath(path)
    probe = path
    while True:
        parent = os.path.dirname(probe)
        if parent == probe:
            return os.path.dirname(path) if os.path.isfile(path) else path
        if os.path.basename(probe).lower() in ("ui", "ui_mp", "lua"):
            return parent
        if os.path.isdir(os.path.join(probe, "ui")) and probe != path:
            return probe
        probe = parent


def lua_files(paths):
    out = []
    for path in paths:
        if os.path.isdir(path):
            for d, _, names in os.walk(path):
                out += [os.path.join(d, n) for n in names if n.lower().endswith(".lua")]
        elif os.path.isfile(path):
            out.append(path)
    return sorted({os.path.abspath(p) for p in out})


def mod_files(root):
    return lua_files([os.path.join(root, d) for d in ("ui", "ui_mp", "lua") if os.path.isdir(os.path.join(root, d))])


def lua_string(s):
    return '"' + s.replace("\\", "/").replace('"', '\\"') + '"'


def compile_file(path):
    """(syntax error or None, [(op, name, line)]) for every global read and write, from the compiler's own listing."""
    r = subprocess.run([LUAC, "-l", "-p", path], capture_output=True, text=True, errors="replace")
    if r.returncode:
        return r.stderr.strip(), []
    out = []
    for line in r.stdout.splitlines():
        m = re.search(r"\[(\d+)\]\s+(GETGLOBAL|SETGLOBAL)\s+.*;\s*(\S+)", line)
        if m:
            out.append((m.group(2), m.group(3), int(m.group(1))))
    return None, out


def compile_all(files):
    with ThreadPoolExecutor(8) as pool:
        return dict(zip(files, pool.map(compile_file, files)))


def build_index(stock, cache_dir):
    """What stock Lua expects from the engine: names it uses and never defines. Cached per dump."""
    key = hashlib.sha1(stock.lower().encode()).hexdigest()[:12]
    lua_path = os.path.join(cache_dir, "index_%s.lua" % key)
    json_path = os.path.join(cache_dir, "index_%s.json" % key)
    if os.path.exists(lua_path) and os.path.exists(json_path):
        with open(json_path, encoding="utf8") as f:
            return lua_path, json.load(f)
    os.makedirs(cache_dir, exist_ok=True)
    files = lua_files([stock])
    calls, defined, engine, called_words = set(), set(), set(), set()
    global_files, cod_files, lui_files, implicit = {}, {}, {}, {}
    indented = {"CoD": {}, "LUI": {}}
    def where(table, names, path):
        module = os.path.relpath(path, stock)[:-4].replace(os.sep, ".")
        for name in names:
            name = "".join(name) if isinstance(name, tuple) else name
            if "-" not in module and len(module) < len(table.get(name, module + "x")):
                table[name] = module
    for path in files:
        with open(path, encoding="utf8", errors="replace") as f:
            s = f.read()
        calls.update(re.findall(r":\s*([A-Za-z_]\w*)\s*\(", s))
        defined.update(re.findall(r"\.([A-Za-z_]\w*)\s*=\s*function", s))
        defined.update(re.findall(r"function\s+[\w.]*[.:]([A-Za-z_]\w*)\s*\(", s))
        engine.update(re.findall(r"\bEngine\.([A-Za-z_]\w*)", s))
        called_words.update(re.findall(r"(?<![.:\w])([A-Za-z_]\w*)\s*\(", s))
        for table, field in re.findall(r"^([A-Z]\w*)\.(\w+)\s*=", s, re.M):
            where(implicit.setdefault(table, {}), [field], path)
        where(global_files, re.findall(r"^(?:function\s+([A-Za-z_]\w*)\s*\(|([A-Za-z_]\w*)\s*=[^=])", s, re.M), path)
        for table, name in ((cod_files, "CoD"), (lui_files, "LUI")):
            # at the top of a file first; inside an `if not CoD.X then` only if nothing sets it at the top
            where(table, re.findall(r"^(?:function\s+%s\.(\w+)\s*\(|%s\.(\w+)\s*=[^=])" % (name, name), s, re.M), path)
            for found in re.findall(r"^\s+%s\.(\w+)\s*=[^=]" % name, s, re.M):
                indented[name].setdefault(found, os.path.relpath(path, stock)[:-4].replace(os.sep, "."))
    for table, name in ((cod_files, "CoD"), (lui_files, "LUI")):
        for found, module in indented[name].items():
            table.setdefault(found, module)
    reads, writes = set(), set()
    for _, entries in compile_all(files).values():
        for op, name, _ in entries:
            (reads if op == "GETGLOBAL" else writes).add(name)
    # native means stock calls it and nothing defines it. A value stock reads and never sets is a bug in stock (its
    # newChildElement crashes UIText.addElementBefore in the real game), so it stays nil here too
    native_globals = sorted(((reads - writes) & called_words) - LUA_STD - {"Engine", "Enum"} | NATIVE_VALUES)
    # all of them: a name stock defines on one class can still be native on another (UIImage's setImage). Anything
    # really defined on UIElement keeps its Lua version
    methods = sorted(calls - NOT_ELEMENT_METHODS)
    for name in list(implicit):
        if name in writes or name in ("CoD", "LUI", "Engine", "Enum"):
            del implicit[name]
    for name in ("function", "if", "for", "while", "local", "return", "end", "CoD", "LUI", "Engine", "Enum"):
        global_files.pop(name, None)
    data = {"methods": methods, "engine": sorted(engine), "native_globals": native_globals,
            "stock_globals": sorted(writes | set(implicit))}
    with open(lua_path, "w", encoding="utf8") as f:
        f.write("return {\n")
        for name in ("methods", "engine", "native_globals"):
            f.write("%s = {" % name)
            f.write(",".join("[%s]=true" % lua_string(n) for n in data[name]))
            f.write("},\n")
        f.write("implicit_tables = {")
        for name, table in sorted(implicit.items()):
            f.write("[%s]={%s}," % (lua_string(name), ",".join("[%s]=%s" % (lua_string(k), lua_string(v))
                                                              for k, v in sorted(table.items()))))
        f.write("},\n")
        for name, table in (("global_files", global_files), ("cod_files", cod_files), ("lui_files", lui_files)):
            f.write("%s = {" % name)
            f.write(",".join("[%s]=%s" % (lua_string(k), lua_string(v)) for k, v in sorted(table.items())))
            f.write("},\n")
        f.write("}\n")
    with open(json_path, "w", encoding="utf8") as f:
        json.dump(data, f)
    return lua_path, data


def finding(stage, file, line, func, message, frames=None):
    return {"severity": SEVERITY.get(stage, "warning"), "stage": stage, "file": file, "line": line, "function": func,
            "message": message, "frames": frames or []}


def static_pass(files, root, index):
    found = []
    # every global any file of the mod sets counts as defined: load order is the game's business
    compiled = compile_all(sorted(set(mod_files(root)) | set(files)))
    mod_writes = {name for _, entries in compiled.values() for op, name, _ in entries if op == "SETGLOBAL"}
    known = LUA_STD | set(index["native_globals"]) | set(index["stock_globals"]) | mod_writes | {"Engine", "Enum"}
    for path in files:
        error, entries = compiled[path]
        if error:
            m = re.search(r"\.lua:(\d+): (.*)$", error)
            found.append(finding("syntax", path, int(m.group(1)) if m else 0, None, m.group(2) if m else error))
        seen = set()
        for op, name, line in entries:
            if op == "GETGLOBAL" and name in LINKER_BANNED:
                found.append(finding("linker_global", path, line, None,
                                     "uses global '%s': the link fails with \"index global 'ERR'\" (see lua-rules.md)" % name))
            if op == "GETGLOBAL" and name not in known and name not in seen:
                seen.add(name)
                found.append(finding("undefined_global", path, line, None,
                                     "reads global '%s', which nothing in the mod or stock Lua defines" % name))
    for path in files:
        with open(path, encoding="utf8", errors="replace") as f:
            source = f.read()
        for m in re.finditer(r"""\brequire\s*\(?\s*["']([\w.]+)["']\s*(?:\)|$)""", source, re.M):
            rel = m.group(1).replace(".", os.sep) + ".lua"
            if rel.lower() in ("io.lua", "os.lua", "debug.lua", "string.lua", "table.lua", "math.lua", "package.lua"):
                continue
            # a compiled .luac is there for the game, just not readable here
            if not any(os.path.isfile(os.path.join(r, rel)) for r in (root, index["stock_path"])) \
                    and not os.path.isfile(os.path.join(root, rel + "c")):
                found.append(finding("missing_require", path, source.count("\n", 0, m.start()) + 1, None,
                                     "requires '%s', which isn't in the mod or the stock dump" % m.group(1)))
                # indented: inside a function or a guard, so it only fails if that code runs
                if source[source.rfind("\n", 0, m.start()) + 1:m.start()][:1] in (" ", "\t"):
                    found[-1]["severity"] = "warning"
    return found


def zone_pass(files, root):
    """A mod file the game never sees: on disk but in no zone, so `require` fails only in the game."""
    zone_dir = os.path.join(root, "zone_source")
    if not os.path.isdir(zone_dir):
        return [], False
    listed = set()
    for name in os.listdir(zone_dir):
        if name.lower().endswith((".zone", ".zpkg")):
            with open(os.path.join(zone_dir, name), encoding="utf8", errors="replace") as f:
                listed.update(m.lower().replace("\\", "/") for m in re.findall(r"rawfile,\s*([^\s,]+)", f.read()))
    found = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/").lower()
        if rel.startswith(("ui/", "ui_mp/")) and rel not in listed:
            found.append(finding("not_zoned", path, 0, None,
                                 "not listed as a rawfile in any zone or zpkg: the game won't find it"))
    return found, True


def run_pass(files, context, root, stock, index_path, fire, timeout):
    config = ["return {", "root = %s," % lua_string(root), "stock = %s," % lua_string(stock),
              "index = %s," % lua_string(index_path), "fire = %s," % ("true" if fire else "false"), "boot = {"]
    config += [lua_string(m) + "," for m in BOOT]
    config += ["},", "targets = {"] + [lua_string(p) + "," for p in files]
    config += ["},", "context = {"] + [lua_string(p) + "," for p in context] + ["},", "}"]
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf8") as f:
        f.write("\n".join(config))
        config_path = f.name
    records, crash = [], None
    try:
        r = subprocess.run([LUA, HARNESS, config_path], capture_output=True, timeout=timeout, cwd=HERE)
        for raw in r.stdout.decode("utf8", "replace").split("\n"):
            at = raw.find(MARK)
            if at >= 0:
                try:
                    records.append(json.loads(raw[at + len(MARK):]))
                except ValueError:
                    pass
        if r.returncode != 0:
            crash = r.stderr.decode("utf8", "replace").strip()[-600:] or "exit code %d" % r.returncode
    except subprocess.TimeoutExpired:
        crash = "the run pass passed its %d s limit" % timeout
    finally:
        os.unlink(config_path)
    return records, crash


def from_record(record):
    frames = [{"file": f.get("file"), "line": f.get("line"), "function": f.get("func"), "defined": f.get("defined"),
               "target": f.get("target")} for f in record.get("frames", [])]
    top = next((f for f in frames if f["target"]), None)
    file, line = (top["file"], top["line"]) if top else (record.get("target"), 0)
    if record["stage"] == "syntax":
        m = re.search(r":(\d+):", record["message"])
        line = int(m.group(1)) if m else 0
    out = finding(record["stage"], file, line, top["function"] if top else None, record["message"], frames)
    if any(text in record["message"] for text in FAKE_DATA):
        out["severity"] = "note" if record["stage"].startswith("callback") else "warning"
        out["note"] = "could come from the scanner's stand-in data: check it"
    elif frames and not frames[0]["target"] and DUMP_NAME.search(record["message"]):
        out["severity"] = "note"
        out["note"] = "failed inside stock code: more likely the stand-ins or the dump than this file"
    return out


def short(path, root):
    try:
        rel = os.path.relpath(path, root)
        return path if rel.startswith("..") else rel.replace("\\", "/")
    except (ValueError, TypeError):
        return str(path)


def clean_message(message):
    """The error text without Lua's own (often cut short) path: the file and line are printed already."""
    return re.sub(r"^.*?\.lua:\d+: ", "", str(message))


def print_report(result, root):
    for f in result["findings"]:
        where = short(f["file"], root)
        if f["line"]:
            where += ":%d" % f["line"]
        print("%-7s %s" % (f["severity"].upper(), where + (" in " + f["function"] if f["function"] else "")))
        print("        " + clean_message(f["message"]))
        if f["stage"] in EXPLAIN:
            print("        " + EXPLAIN[f["stage"]])
        if f.get("note"):
            print("        " + f["note"])
        for frame in f["frames"][:10]:
            print("          %s:%s  %s" % (short(frame["file"], root), frame["line"], frame["function"]))
        print()
    s = result["summary"]
    print("%d files: %d errors, %d warnings, %d notes" % (s["files"], s["error"], s["warning"], s["note"]))
    print("run pass: %s" % s["run"])
    print("not checked: real game data and timing, native engine behaviour, visuals, engine limits")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="Lua files or folders")
    ap.add_argument("--files-from", help="a text file listing more paths, one per line")
    ap.add_argument("--root", help="folder that `require` paths start from (default: found from the paths)")
    ap.add_argument("--stock", help="stock Lua dump folder (default: BO3_LUA_STOCK, or a T7LuaRepo dump above the paths)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--static-only", action="store_true", help="syntax, globals, requires, zones: no run pass")
    ap.add_argument("--no-context", action="store_true", help="run only the given files, not the rest of the mod")
    ap.add_argument("--no-fire", action="store_true", help="don't fire model callbacks with fake data")
    ap.add_argument("--fail-on", choices=["error", "warning", "note"], default="error")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "bo3_lua_scan"))
    args = ap.parse_args()

    def fail(text):
        print(json.dumps({"fatal": text}) if args.json else "bo3_lua_scan: " + text)
        return 2

    if not os.path.exists(LUA):
        return fail("bin\\lua51.exe is missing: run build.bat")
    if args.files_from:
        with open(args.files_from, encoding="utf8") as f:
            args.paths += [line.strip() for line in f if line.strip()]
    files = lua_files(args.paths)
    if not files:
        return fail("no .lua files in " + ", ".join(args.paths))
    root = os.path.abspath(args.root) if args.root else find_root(files[0])
    stock = args.stock or find_stock(files[0])
    if not stock or not os.path.isdir(stock):
        return fail("no stock Lua dump found: pass --stock or set BO3_LUA_STOCK")
    stock = os.path.abspath(stock)

    index_path, index = build_index(stock, args.cache)
    index["stock_path"] = stock
    found = static_pass(files, root, index)
    zone_found, zones = zone_pass(files, root)
    found += zone_found

    run_state = "skipped (--static-only)"
    environment, boot_errors = [], []
    if not args.static_only:
        targets = {os.path.normcase(p) for p in files}
        context = [] if args.no_context else [p for p in mod_files(root) if os.path.normcase(p) not in targets]
        records, crash = run_pass(files, context, root, stock, index_path, not args.no_fire, args.timeout)
        done = next((r for r in records if r["kind"] == "done"), None)
        for r in records:
            if r["kind"] == "finding":
                f = from_record(r)
                # the run pass finds syntax errors too: the static pass has them already
                if f["stage"] != "syntax":
                    found.append(f)
            elif r["kind"] == "environment":
                environment.append(r)
            elif r["kind"] == "boot":
                boot_errors.append(r)
        if crash:
            run_state = "STOPPED EARLY, results are partial: " + crash
        elif done:
            run_state = "built %d widgets and menus, %d model subscriptions" % (done["built"], done["subscriptions"])
        else:
            run_state = "ended without finishing"

    found.sort(key=lambda f: (-RANK[f["severity"]], str(f["file"]), f["line"] or 0))
    counts = {k: sum(1 for f in found if f["severity"] == k) for k in RANK}
    summary = dict(counts, files=len(files), run=run_state, environment=len(environment), boot_errors=len(boot_errors),
                   zones_checked=zones)
    result = {"root": root, "stock": stock, "summary": summary, "findings": found,
              "boot_errors": [{"module": b.get("module"), "message": b.get("message")} for b in boot_errors],
              "environment": [{"target": e.get("target"), "message": e.get("message")} for e in environment]}
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print_report(result, root)
    failed = any(RANK[f["severity"]] >= RANK[args.fail_on] for f in found)
    return 2 if run_state.startswith("STOPPED") and not failed else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
