# bo3_lua_scan

Finds Black Ops III Lua errors with no game running. Point it at a Lua file or a folder:

```bash
python scan.py path/to/mod/ui
```

```bash
python scan.py path/to/MyWidget.lua --json
```

Standard-library Python plus the two small exes in `bin/`. Exit code: 0 clean, 1 findings at or above `--fail-on`
(default `error`), 2 could not run.

## What it does

1. **Static pass.** Compiles every file with a Lua 5.1 patched to take HavokScript's syntax (`&`, `|`, `<<`, `>>`, BOMs,
   more upvalues). Reports syntax errors, globals the linker rejects, globals nothing defines, `require`s with no file,
and files missing from
   `zone_source` when the mod has one.
2. **Run pass.** Loads the real stock LUI code from a Lua dump, with stand-ins for what the engine does natively. Then it
   builds every `CoD.X.new` and `LUI.createMenu.X`, and fires their model callbacks with a number and with no value.
   Errors come back with real file, line and function names, like the in-game trace.

Scanning one file still runs the rest of the mod, because a widget in one file often calls code in another. Only errors
with a scanned file on the stack are reported. `--no-context` turns that off.

It needs a stock Lua dump, which isn't included. It finds a `T7LuaRepo` dump above the scanned files, or use `--stock` or
the `BO3_LUA_STOCK` environment variable.

## Reading the results

- **error**: would fail in the game or the link as far as the scan can tell (syntax, a crash while loading or building,
  or `linker_global`: bare `io`, `os`, `getmetatable`, `setmetatable` or `rawset`, which fail the link with
  `attempt to index global 'ERR'`. They exist in plain Lua, so only this check sees them).
- **warning**: depends on the data, so check it (a callback failed on stand-in data, an undefined global, a missing
  zone entry).
- **note**: probably not the scanned file's fault, or silent in the game: a `pcall` caught it, it failed inside stock code,
  or stand-in data caused it. When stock code stops a widget's build, the rest of that widget doesn't get checked.

The summary always ends with what wasn't checked: real game data and timing, native engine behaviour, visuals, engine
limits. A clean scan doesn't mean the game can't error.

## When the game finds something the scan missed

The scanner only improves if misses go back into it:

1. Take the trace from `zone\MZO_LuaErrors.log`, or the link error.
2. Work out why the scan missed it. Usually a stand-in behaves differently from the engine (`runtime/harness.lua`), or the
   stock dump is wrong (`runtime/stock_fixes.lua`).
3. Add a small case in `tests/cases` and list it in `tests/run_tests.py`.
4. Run `python tests/run_tests.py`.

`tests/samples/skin_bug` is a real broken copy of the MZO HUD, kept as a test. Don't fix it.

## Files

- `scan.py`: the CLI.
- `runtime/harness.lua`: the run pass and engine stand-ins. Scanned code gets no file writes, DLLs or processes, but this
  isn't a security boundary, so only scan code you trust.
- `runtime/stock_fixes.lua`: stock functions the decompiled dump got wrong.
- `vendor/lua51`: Lua 5.1.5 (MIT), with changes marked `BO3SCAN`. `build.bat` rebuilds `bin/`.
