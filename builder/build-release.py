#!/usr/bin/env python3
"""Offline app-release builder. Lock in, artifact out. Tags are not inputs.

Mint and rebuild both materialize `source_sha` from a git repo. A working
tree, a tag, and the process umask are not rebuild inputs.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from digest_tree import DigestError, digest_tree

ABI = "public-app-split/v1"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
LOCK_KEYS = frozenset({"abi", "id", "source_sha", "tree_digest", "artifact_digest"})
SOURCE_PATH_RE = re.compile(r"^(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+$")


def die(message: str) -> None:
    sys.stderr.write(f"build-release: {message}\n")
    raise SystemExit(1)


def load_lock(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read lock {path}: {exc}")
    if not isinstance(raw, dict):
        die(f"lock {path} must be a JSON object")
    unknown = sorted(set(raw) - LOCK_KEYS)
    if unknown:
        die(f"lock has unknown key(s): {', '.join(unknown)}")
    missing = sorted(LOCK_KEYS - set(raw))
    if missing:
        die(f"lock is missing key(s): {', '.join(missing)}")
    lock = {key: raw[key] for key in sorted(LOCK_KEYS)}
    if lock["abi"] != ABI:
        die(f"unsupported lock abi {lock['abi']!r} (want {ABI})")
    if not isinstance(lock["id"], str) or ID_RE.fullmatch(lock["id"]) is None:
        die(f"lock id is not a package id: {lock['id']!r}")
    if not isinstance(lock["source_sha"], str) or SHA_RE.fullmatch(lock["source_sha"]) is None:
        die("lock source_sha must be a 40-hex resolved commit")
    for field in ("tree_digest", "artifact_digest"):
        if not isinstance(lock[field], str) or DIGEST_RE.fullmatch(lock[field]) is None:
            die(f"lock {field} must be a bare lowercase 64-hex digest")
    return lock


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        die(f"output already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(src, dst, symlinks=True, copy_function=shutil.copy2)
    except OSError as exc:
        die(f"cannot copy {src} -> {dst}: {exc}")


def write_lock(path: Path, lock: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: lock[key] for key in ("abi", "id", "source_sha", "tree_digest", "artifact_digest")}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_output(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False, capture_output=True, text=True,
        )
    except OSError as exc:
        die(f"cannot run git: {exc}")
    if proc.returncode != 0:
        die(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def materialize_from_sha(repo: Path, source_path: str, source_sha: str, dest: Path) -> None:
    """Extract the commit path with archive modes intact.

    `tar -x` applies the process umask, so tree_digest would become
    (commit × umask). `-p` keeps the modes git archive wrote.
    """
    if SOURCE_PATH_RE.fullmatch(source_path) is None:
        die(f"source-path is not a relative package path: {source_path!r}")
    git_output(repo, "cat-file", "-e", f"{source_sha}^{{commit}}")
    dest.mkdir(parents=True)
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", source_sha, source_path],
        check=False, capture_output=True,
    )
    if archive.returncode != 0:
        die(f"git archive {source_sha} {source_path} failed: "
            + archive.stderr.decode("utf-8", "replace").strip())
    extract = subprocess.run(
        ["tar", "--no-same-owner", "-xp", "-C", str(dest)],
        check=False, input=archive.stdout, capture_output=True,
    )
    if extract.returncode != 0:
        die("cannot extract archived source: "
            + extract.stderr.decode("utf-8", "replace").strip())
    staged = dest / source_path
    if not staged.is_dir():
        die(f"archived {source_sha}:{source_path} is not a directory")
    hoisted = dest.parent / (dest.name + ".pkg")
    staged.rename(hoisted)
    shutil.rmtree(dest)
    hoisted.rename(dest)


def digest_or_die(root: Path) -> str:
    try:
        return digest_tree(str(root))
    except DigestError as exc:
        die(str(exc))


def build_from_sha(repo: Path, source_path: str, source_sha: str, out: Path) -> tuple[str, str]:
    staged_root = Path(tempfile.mkdtemp(prefix="airlock-release-"))
    staged = staged_root / "src"
    try:
        materialize_from_sha(repo, source_path, source_sha, staged)
        tree_digest = digest_or_die(staged)
        copy_tree(staged, out)
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)
    return tree_digest, digest_or_die(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--repo", type=Path, required=True,
                        help="git repo used to materialize source_sha")
    parser.add_argument("--source-path", required=True,
                        help="path inside --repo, e.g. apps/demo")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--id", help="package id when writing a new lock")
    parser.add_argument("--source-sha", help="resolved commit when writing a new lock")
    parser.add_argument("--lock", type=Path, help="existing lock to rebuild")
    parser.add_argument("--write-lock", type=Path, help="write the produced lock here")
    args = parser.parse_args()

    if getattr(args, "source", None) is not None:
        die("working trees are not an input; use --repo --source-path")

    repo = args.repo.resolve()
    if args.lock:
        expected = load_lock(args.lock)
        tree_digest, artifact_digest = build_from_sha(
            repo, args.source_path, expected["source_sha"], args.out.resolve())
        if tree_digest != expected["tree_digest"]:
            die(
                "source_sha tree does not match lock.tree_digest\n"
                f"  lock:   {expected['tree_digest']}\n"
                f"  sha:    {tree_digest}"
            )
        if artifact_digest != expected["artifact_digest"]:
            die(
                "artifact_digest does not match lock\n"
                f"  lock:     {expected['artifact_digest']}\n"
                f"  artifact: {artifact_digest}"
            )
        lock = expected
    else:
        if not args.id or not args.source_sha:
            die("--id and --source-sha are required when minting a lock")
        if ID_RE.fullmatch(args.id) is None:
            die(f"--id is not a package id: {args.id!r}")
        if SHA_RE.fullmatch(args.source_sha) is None:
            die("--source-sha must be a 40-hex resolved commit")
        tree_digest, artifact_digest = build_from_sha(
            repo, args.source_path, args.source_sha, args.out.resolve())
        lock = {
            "abi": ABI,
            "id": args.id,
            "source_sha": args.source_sha,
            "tree_digest": tree_digest,
            "artifact_digest": artifact_digest,
        }

    if args.write_lock:
        write_lock(args.write_lock, lock)

    json.dump(lock, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
