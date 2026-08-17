#!/usr/bin/env python3
"""Prove both delta directions against the census, decisions, and destination."""

import importlib.util
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent / "fixtures" / "parity"
REPOSITORY = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
INTERNAL = ROOT / "internal"
EXPECTED_PUBLIC_ONLY = {"devterm/DT-S1"}
EXPECTED_INTERNAL_ONLY = {"dev-monitor/DM-U1"}
EXPECTED_MARKERS = {
    "devterm/DT-S1": "persistent-codex-usage-cache\n",
    "dev-monitor/DM-U1": "bulk-message-actions\n",
}
EXPECTED_CASES = {
    "DT-S1": ("public", "keep"),
    "DM-U1": ("internal", "migrate"),
}


def inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def matrix_sides() -> dict[str, str]:
    result = {}
    for line in (REPOSITORY / "census" / "parity-matrix.md").read_text().splitlines():
        if line.startswith("|"):
            row = cells(line)
            if row and re.fullmatch(r"[A-Z]{2}-[A-Z]\d+", row[0]):
                result[row[0]] = row[2]
    return result


def dispositions() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "parity-dispositions.py"
    spec = importlib.util.spec_from_file_location("parity_dispositions", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = {}
    for ids, (_, _, disposition) in module.read_dispositions().items():
        for matrix_id in ids:
            result[matrix_id] = disposition
    return result


def main() -> None:
    public = inventory(PUBLIC)
    internal = inventory(INTERNAL)
    public_only = set(public) - set(internal)
    internal_only = set(internal) - set(public)
    if public_only != EXPECTED_PUBLIC_ONLY:
        raise SystemExit(
            f"public-only fixture drift: {sorted(public_only)} != {sorted(EXPECTED_PUBLIC_ONLY)}"
        )
    if internal_only != EXPECTED_INTERNAL_ONLY:
        raise SystemExit(
            f"internal-only fixture drift: {sorted(internal_only)} != {sorted(EXPECTED_INTERNAL_ONLY)}"
        )
    for relative, marker in EXPECTED_MARKERS.items():
        actual = public.get(relative, internal.get(relative))
        if actual != marker:
            raise SystemExit(f"fixture marker drift: {relative}: {actual!r} != {marker!r}")
    sides = matrix_sides()
    decisions = dispositions()
    for matrix_id, (side, disposition) in EXPECTED_CASES.items():
        if sides.get(matrix_id) != side:
            raise SystemExit(
                f"fixture census direction drift: {matrix_id}: {sides.get(matrix_id)!r} != {side!r}"
            )
        if decisions.get(matrix_id) != disposition:
            raise SystemExit(
                f"fixture disposition drift: {matrix_id}: {decisions.get(matrix_id)!r} != {disposition!r}"
            )

    devterm_source = (REPOSITORY / "apps/devterm/backend/devterm-gate.py").read_text()
    if "CODEX_USAGE_STATE" not in devterm_source or "codex-usage.json" not in devterm_source:
        raise SystemExit("DT-S1 destination anchor missing from apps/devterm/backend/devterm-gate.py")
    monitor_path = REPOSITORY / "apps/dev-monitor/frontend/dev-monitor.html"
    monitor_source = monitor_path.read_text()
    if 'id="messages"' not in monitor_source:
        raise SystemExit("DM-U1 positive control missing: message console")
    for marker in ('id="msg-bulk"', "function selectedVisible()", "function runPool("):
        if marker not in monitor_source:
            raise SystemExit(f"DM-U1 destination anchor missing: {marker}")
    print(
        "ok: synthetic sample directional controls "
        "public-only=devterm/DT-S1 internal-only=dev-monitor/DM-U1 "
        "measured=test/fixtures/parity/{public,internal}; "
        "destination sample=apps/devterm/backend/devterm-gate.py," 
        "apps/dev-monitor/frontend/dev-monitor.html "
        "positive-control=dev-monitor#messages; "
        "selected-destination=dev-monitor#msg-bulk"
    )


if __name__ == "__main__":
    main()
