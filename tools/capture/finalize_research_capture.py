"""Seal a NEW organized source-only capture with hashes and honest coverage.

No capture data is changed. --verify is read-only and can run with the game shut.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time

REPORT = "research_capture.report.json"
GOOD_READ = {"captured", "reused_file", "empty"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def contained_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path escapes capture: {relative}")
    return path


def safe_relative(relative: str) -> str:
    path = PurePosixPath(relative.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in str(path):
        raise ValueError(f"Path escapes capture: {relative}")
    return path.as_posix()


def scan_files(root: Path, progress):
    """Validate entries once with scandir; avoid opening each file to resolve its path."""
    files = []
    directories = [root]
    while directories:
        directory = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                st = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(st, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C):
                    raise ValueError(f"Capture contains a link/junction: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append((Path(entry.path), st))
        progress("enumerating", len(files), None)
    return sorted(files, key=lambda x: str(x[0]))


def stable_digest(path, before):
    with path.open("rb") as f:
        opened = os.fstat(f.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        # Windows DirEntry.stat may omit st_ino/st_dev; compare metadata here,
        # then use full identity from the open handle for the second check.
        if (before.st_size, before.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
            raise RuntimeError(f"Capture still changing: {path}")
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
        if identity(opened) != identity(os.fstat(f.fileno())):
            raise RuntimeError(f"Capture still changing: {path}")
    return h.hexdigest()


class Progress:
    def __init__(self, path=None):
        self.path = path
        self.last = 0
        self.stage = None
        self.last_warning = {}

    def __call__(self, stage, done, total):
        now = time.monotonic()
        if stage == self.stage and now - self.last < 1 and done != total:
            return
        self.last, self.stage = now, stage
        percent = {"enumerating": 42, "validating": 97, "toolchain": 98, "sealed": 99}.get(stage, 43)
        if stage == "hashing" and total:
            percent = 43 + int(53 * done / total)
        state = {"stage": stage, "files_done": done, "files_total": total, "percent": percent,
                 "utc": datetime.now(timezone.utc).isoformat()}
        print(json.dumps(state), flush=True)
        if self.path:
            # Other readers (for example sync/indexing software) may temporarily
            # deny replacement despite the native poller's share flags. Progress
            # is advisory: retry on the next tick without aborting evidence hashing.
            for dest, text in ((self.path, str(percent)), (self.path.with_suffix(".json"), json.dumps(state))):
                temp = dest.with_name(dest.name + ".tmp")
                try:
                    temp.write_text(text, encoding="utf-8")
                    os.replace(temp, dest)
                    self.last_warning.pop(dest, None)
                except OSError as exc:
                    if dest not in self.last_warning or now - self.last_warning[dest] >= 60:
                        print(json.dumps({"warning": "progress_file_update_failed",
                                          "path": str(dest), "error": str(exc),
                                          "evidence_finalization_continues": True}), flush=True)
                        self.last_warning[dest] = now


def walk_status(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else key
            if key.endswith("status") and isinstance(child, str):
                yield {"field": name, "status": child}
            elif isinstance(child, (dict, list)):
                yield from walk_status(child, name)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from walk_status(child, f"{prefix}[{i}]")


def finalize(source: Path, progress=None) -> dict:
    source = source.resolve(strict=True)
    if not any(p.name == "exported_files" for p in source.parents):
        raise ValueError("Research reports must stay under exported_files.")
    target = source / REPORT
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}; use --verify.")
    progress = progress or (lambda *args: None)
    capture = source / "capture"
    metadata = json.loads((capture / "terraingfx.json").read_text(encoding="utf-8"))
    if metadata.get("source_only") is not True:
        raise ValueError("This is not a new source-only capture; old exports remain untouched.")
    evidence_file = capture / "research" / "evidence.json"
    evidence = json.loads(evidence_file.read_text(encoding="utf-8")) if evidence_file.exists() else {}
    files = []
    progress("enumerating", 0, None)
    candidates = scan_files(source, progress)
    progress("hashing", 0, len(candidates))
    for done, (path, before) in enumerate(candidates, 1):
        sha = stable_digest(path, before)
        files.append({"path": path.relative_to(source).as_posix(),
                      "bytes": before.st_size, "sha256": sha})
        progress("hashing", done, len(candidates))
    progress("validating", len(files), len(files))
    sizes = {f["path"]: f["bytes"] for f in files}
    reads = evidence.get("reads", [])
    problems = [r for r in reads if r.get("status") not in GOOD_READ]
    missing = []
    storage = evidence.get("storage", {})
    def stored_size(name):
        name = safe_relative(name)
        record = storage.get(name)
        if record is None:
            return sizes.get("capture/research/" + name)
        path = "capture/research/" + safe_relative(record["file"])
        offset, length = record["offset"], record["bytes"]
        if offset < 0 or length < 0 or path not in sizes or offset + length > sizes[path]:
            return None
        return length
    for name in storage:
        if stored_size(name) is None:
            missing.append(name + ": invalid packed record range")
    for r in reads:
        if r.get("status") in {"captured", "reused_file", "partial_read"}:
            size = stored_size(r["file"])
            if size is None:
                missing.append(r["file"])
            elif r.get("status") == "captured" and size != r["read_bytes"]:
                missing.append(r["file"] + ": byte count mismatch")
    for package in evidence.get("packages", []):
        for key, count in (("raw_file", "raw_bytes"), ("file", "extracted_bytes")):
            if key in package and stored_size(package[key]) != package.get(count):
                missing.append(package[key] + ": package missing/size mismatch")
    legacy_status = list(walk_status(metadata))
    result = {
        "schema": "superterrain-research-inventory-v1",
        "sealed_utc": datetime.now(timezone.utc).isoformat(),
        "capture_root": str(source),
        "source_only": True,
        "evidence_manifest_present": bool(evidence),
        "complete_game_memory_dump": False,
        "files": files,
        "total_bytes": sum(f["bytes"] for f in files),
        "coverage": {
            "additional_read_status_counts": dict(Counter(r.get("status", "missing") for r in reads)),
            "additional_read_problems": problems,
            "package_status_counts": dict(Counter(p.get("status", "missing") for p in evidence.get("packages", []))),
            "pool_status_counts": dict(Counter(p.get("status", "missing") for p in evidence.get("pools", []))),
            "candidate_array_status_counts": dict(Counter(p.get("status", "missing") for p in evidence.get("array_candidates", []))),
            "decal_candidates": evidence.get("decals", []),
            "legacy_capture_statuses": legacy_status,
            "missing_or_mismatched_files": missing,
            "limits": evidence.get("limits"),
            "budget_charged_by_lane": evidence.get("budget_charged_by_lane"),
            "packed_record_count": len(storage),
            "unresolved": evidence.get("unresolved", ["additional evidence capture failed"]),
        },
        "comparison": {
            "stable_keys": ["terrain name hash", "material/image name hash", "package key", "pool index + asset name hash", "SHA-256"],
            "process_addresses": "session-local; never reuse in another game process without resolving again",
            "atomic_snapshot": False,
            "terrain_header_unchanged": evidence.get("terrain_header_unchanged_during_evidence_pass"),
            "pool_descriptors_unchanged": evidence.get("pool_descriptors_unchanged_during_evidence_pass"),
        },
        "toolchain": {"finalizer_sha256": digest(Path(__file__))},
    }
    progress("toolchain", len(files), len(files))
    runtime = next(p.parent for p in source.parents if p.name == "exported_files")
    for relative in ("Greyhound.exe", "Greyhound-cli.exe"):
        p = runtime / relative
        if p.is_file():
            result["toolchain"][relative] = {"bytes": p.stat().st_size, "sha256": digest(p)}
    result["verification_ready"] = bool(evidence) and not missing
    # Exclusive creation: the manifest itself becomes part of the immutable session.
    with target.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    progress("sealed", len(files), len(files))
    return result


def verify(source: Path) -> dict:
    source = source.resolve(strict=True)
    report = json.loads((source / REPORT).read_text(encoding="utf-8"))
    failures = []
    indexed = {f["path"] for f in report["files"]}
    for entry in report["files"]:
        path = contained_file(source, entry["path"])
        if not path.is_file():
            failures.append({"path": entry["path"], "status": "missing"})
        elif path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            failures.append({"path": entry["path"], "status": "changed"})
    added = sorted(p.relative_to(source).as_posix() for p in source.rglob("*")
                   if p.is_file() and p.name != REPORT and p.relative_to(source).as_posix() not in indexed)
    return {"integrity_ok": not failures and not added, "failures": failures, "added_files": added,
            "file_count": len(indexed), "complete_game_memory_dump": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--progress-file", type=Path)
    args = parser.parse_args()
    try:
        if args.progress_file:
            expected = (args.source.resolve().parent / "logs" / "source_capture.progress").resolve()
            if args.verify or args.progress_file.resolve() != expected:
                raise ValueError("Progress must go to this session's logs/source_capture.progress.")
        result = verify(args.source) if args.verify else finalize(args.source, Progress(args.progress_file))
        if args.verify:
            print(json.dumps(result, indent=2))
            return 0 if result["integrity_ok"] else 1
        print(json.dumps({"report": str(args.source / REPORT),
                          "files": len(result["files"]), "bytes": result["total_bytes"],
                          "verification_ready": result["verification_ready"],
                          "read_problems": len(result["coverage"]["additional_read_problems"])}))
        return 0 if result["verification_ready"] else 1
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
