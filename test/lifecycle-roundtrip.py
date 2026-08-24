#!/usr/bin/env python3
"""Deterministic, host-safe lifecycle fixture for one public app package.

The ABI names the retained paths and the reversible procedures.  This runner
maps every path into a temporary legacy/package namespace, snapshots it,
forwards it, captures a post-cutover write, and reverses it without touching a
real home directory or rooted path.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = (
    "code-server", "dev-monitor", "devterm", "feedback", "learning",
    "markwand", "notepad", "notes", "orca", "paseo", "publish",
)
PROCEDURES = {
    "forward": "copy-retained-paths",
    "write_capture": "capture-post-cutover-writes",
    "reverse": "restore-retained-paths",
}
NONE_FIELDS = ("quiesce", "snapshot", "forward", "write_capture", "reverse")
DIRECTORY_PATHS = {"/opt/airlock/share", "~/uploads"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL lifecycle: {message}")


def digest(path: Path) -> str:
    """Hash names, kinds, modes, bytes, and symlink targets deterministically."""
    out = hashlib.sha256()

    def visit(item: Path, rel: str) -> None:
        info = item.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if item.is_symlink():
            kind, payload = "link", os.readlink(item).encode()
        elif item.is_dir():
            kind, payload = "dir", b""
        elif item.is_file():
            kind, payload = "file", item.read_bytes()
        else:
            fail(f"unsupported fixture kind: {item}")
        out.update(f"{rel}\0{kind}\0{mode:o}\0".encode())
        out.update(payload)
        out.update(b"\0")
        if kind == "dir":
            for child in sorted(item.iterdir(), key=lambda value: value.name):
                visit(child, f"{rel}/{child.name}")

    visit(path, ".")
    return out.hexdigest()


def copy_path(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        fail(f"copy target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        target.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)
    elif source.is_file():
        shutil.copy2(source, target, follow_symlinks=False)
    else:
        fail(f"copy source is not retained data: {source}")


def seed(path: Path, app: str, retained: str, directory: bool) -> None:
    marker = f"legacy:{app}:{retained}\n".encode()
    if not directory:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker + b"\x00fixture\n")
        path.chmod(0o600)
        return
    path.mkdir(parents=True)
    path.chmod(0o750)
    (path / ".state").write_bytes(marker)
    (path / ".state").chmod(0o600)
    nested = path / "nested"
    nested.mkdir()
    nested.chmod(0o700)
    (nested / "record.json").write_text('{"generation":1}\n', encoding="utf-8")
    (nested / "record.json").chmod(0o640)
    (path / "latest").symlink_to("nested/record.json")


def capture_write(path: Path, app: str, index: int) -> None:
    payload = f"post-cutover:{app}:{index}\n".encode()
    if path.is_dir():
        with (path / ".state").open("ab") as stream:
            stream.write(payload)
        written = path / "post-cutover.bin"
        written.write_bytes(payload + b"\x00rpo-zero\n")
        written.chmod(0o600)
    else:
        with path.open("ab") as stream:
            stream.write(payload)


def check_stateless(app: str, doc: dict[str, object]) -> None:
    if doc.get("state") != "stateless":
        fail(f"{app}: expected stateless ABI")
    if doc.get("paths") != [] or doc.get("rpo") != "none":
        fail(f"{app}: stateless ABI retains data")
    if any(doc.get(field) != "none" for field in NONE_FIELDS):
        fail(f"{app}: stateless lifecycle is not explicit none")


def check_stateful(app: str, doc: dict[str, object], rpo_zero: bool) -> int:
    paths = doc.get("paths")
    if doc.get("state") != "stateful" or not isinstance(paths, list) or not paths:
        fail(f"{app}: stateful ABI has no retained paths")
    if doc.get("rpo") != "0":
        fail(f"{app}: stateful ABI must declare RPO=0")
    for field, procedure in PROCEDURES.items():
        if doc.get(field) != procedure:
            fail(f"{app}: {field} is not closed ({doc.get(field)!r})")

    with tempfile.TemporaryDirectory(prefix=f"airlock-lifecycle-{app}-") as raw:
        base = Path(raw)
        for index, retained in enumerate(paths):
            if not isinstance(retained, str) or not retained:
                fail(f"{app}: invalid retained path {retained!r}")
            slot = f"slot-{index:02d}"
            legacy = base / "legacy" / slot
            snapshot = base / "snapshot" / slot
            package = base / "package" / slot
            restored = base / "restored" / slot

            seed(legacy, app, retained,
                 retained.endswith("/") or retained in DIRECTORY_PATHS)
            initial = digest(legacy)
            copy_path(legacy, snapshot)
            if digest(snapshot) != initial:
                fail(f"{app}: snapshot changed {retained}")
            copy_path(snapshot, package)
            if digest(package) != initial:
                fail(f"{app}: forward changed {retained}")

            capture_write(package, app, index)
            captured = digest(package)
            if captured == initial:
                fail(f"{app}: write capture was not discriminating for {retained}")
            if digest(snapshot) != initial:
                fail(f"{app}: write capture mutated the snapshot for {retained}")

            copy_path(package, restored)
            if digest(restored) != captured:
                fail(f"{app}: reverse lost post-cutover data for {retained}")
            if rpo_zero and digest(restored) != digest(package):
                fail(f"{app}: RPO=0 digest mismatch for {retained}")
        return len(paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, choices=APPS)
    parser.add_argument("--data-roundtrip", action="store_true")
    parser.add_argument("--rpo-zero", action="store_true")
    args = parser.parse_args()
    if not args.data_roundtrip:
        fail("--data-roundtrip is required")
    if args.rpo_zero and not args.data_roundtrip:
        fail("--rpo-zero requires --data-roundtrip")

    path = ROOT / "abi" / "apps" / f"{args.app}.toml"
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    if doc.get("id") != args.app:
        fail(f"{args.app}: ABI id mismatch")
    if doc.get("state") == "stateless":
        check_stateless(args.app, doc)
        print(f"ok: lifecycle {args.app} stateless=none rpo=none")
        return
    count = check_stateful(args.app, doc, args.rpo_zero)
    print(f"ok: lifecycle {args.app} paths={count} forward+capture+reverse rpo=0")


if __name__ == "__main__":
    main()
