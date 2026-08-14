"""Package-tree digest used by the release builder.

Same algorithm as bin/airlock-ledger.digest_tree. The foundation gate
compares both implementations on a fixture so this copy cannot drift
while it still lives next to the ledger. After the airlock-apps transfer
this file is the release-layer SoT.
"""
from __future__ import annotations

import hashlib
import os
import stat


class DigestError(Exception):
    pass


def _length_prefixed(hasher: "hashlib._Hash", field: bytes) -> None:
    hasher.update(len(field).to_bytes(8, "big"))
    hasher.update(field)


def digest_tree(root: str) -> str:
    """Hash every package entry in byte-sorted relative-path order."""
    try:
        root_stat = os.stat(root)
    except OSError as exc:
        raise DigestError(f"cannot digest package tree {root}: {exc}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise DigestError(f"cannot digest package tree {root}: package path is not a directory")

    entries: list[tuple[bytes, bytes, int, bytes]] = []

    def visit(directory: str, prefix: str) -> None:
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            raise DigestError(f"cannot read package tree {root}: {exc}") from exc
        for child in children:
            relative = child.name if not prefix else f"{prefix}/{child.name}"
            relative_bytes = os.fsencode(relative)
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise DigestError(
                    f"cannot stat package entry {os.path.join(root, relative)}: {exc}"
                ) from exc
            mode = stat.S_IMODE(child_stat.st_mode)
            if stat.S_ISREG(child_stat.st_mode):
                try:
                    with open(child.path, "rb") as fh:
                        content = fh.read()
                except OSError as exc:
                    raise DigestError(
                        f"cannot read package entry {os.path.join(root, relative)}: {exc}"
                    ) from exc
                entries.append((relative_bytes, b"f", mode, content))
            elif stat.S_ISDIR(child_stat.st_mode):
                entries.append((relative_bytes, b"d", mode, b""))
                visit(child.path, relative)
            elif stat.S_ISLNK(child_stat.st_mode):
                try:
                    target = os.fsencode(os.readlink(child.path))
                except OSError as exc:
                    raise DigestError(
                        f"cannot read package symlink {os.path.join(root, relative)}: {exc}"
                    ) from exc
                entries.append((relative_bytes, b"l", mode, target))
            else:
                raise DigestError(
                    f"special file is not allowed in package tree: {os.path.join(root, relative)}"
                )

    visit(root, "")
    entries.sort(key=lambda item: item[0])
    hasher = hashlib.sha256()
    for relative, kind, mode, content in entries:
        _length_prefixed(hasher, relative)
        _length_prefixed(hasher, kind)
        _length_prefixed(hasher, str(mode).encode("ascii"))
        _length_prefixed(hasher, content)
    return hasher.hexdigest()
