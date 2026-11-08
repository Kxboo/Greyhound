#!/usr/bin/env python3
"""Every bug the scanner must keep catching, and code it must keep passing. python tests/run_tests.py

A bug the game found and the scan missed gets a case here (a small folder in tests/cases) when the scanner is fixed.
Each case: (folder, expected error messages and the functions that must be on their stacks; [] = must pass clean).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "..", "scan.py")

CASES = [
    # in game 2026-11-04: UI Error 90768. Stock UIText.addElementBefore reads an undefined global
    ("samples/skin_bug", [("newChildElement", ["LUI.UIText.addElementBefore", "skin", "H.Compass", "CoD.AetheriumCompass.new"])]),
    ("cases/uitext_add_before", [("newChildElement", ["LUI.UIText.addElementBefore", "CoD.TestUIText.new"])]),
    # in game 2026-11-04: an empty model gives no value at all, so tonumber() has no argument. Subscribing calls back at once
    ("cases/empty_model_tonumber", [("bad argument #1 to 'tonumber'", ["CoD.TestEmptyModel.new"])]),
    ("cases/syntax_error", [("expected", [])]),
    ("cases/typo_function", [("NotARealFunction", ["CoD.TestTypo.new"])]),
    # link 2026-11-08: "index global 'ERR'" from getmetatable. The linker rejects it, plain Lua is happy
    ("cases/linker_banned_global", [("uses global 'getmetatable'", [])]),
    ("cases/clean_widget", []),
    # HavokScript syntax plain Lua 5.1 refuses, and a UTF-8 BOM
    ("cases/havok_syntax", []),
]


def main():
    failed = 0
    for folder, expected in CASES:
        path = os.path.normpath(os.path.join(HERE, folder))
        r = subprocess.run([sys.executable, SCAN, path, "--json"], capture_output=True, text=True, errors="replace")
        result = json.loads(r.stdout)
        errors = [f for f in result["findings"] if f["severity"] == "error"]
        problems = []
        for text, functions in expected:
            match = [f for f in errors if text in str(f["message"])]
            if not match:
                problems.append("missed: " + text)
                continue
            stack = [frame["function"] for frame in match[0]["frames"]]
            problems += ["%r not on the stack %r" % (name, stack) for name in functions if name not in stack]
        if not expected and errors:
            problems += ["false alarm: %s" % f["message"] for f in errors]
        print("%-5s %s" % ("FAIL" if problems else "ok", folder))
        for problem in problems:
            print("      " + problem)
        failed += bool(problems)
    print("%d of %d failed" % (failed, len(CASES)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
