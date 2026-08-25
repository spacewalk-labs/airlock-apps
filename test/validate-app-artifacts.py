#!/usr/bin/env python3
"""Validate app manifests before release artifacts are minted."""

import sys
import tomllib
from pathlib import Path


APPS = (
    "code-server", "dev-monitor", "devterm", "feedback",
    "fileview", "learning", "notepad", "notes", "orca", "paseo", "publish",
)
EXPECTED_UNITS = {
    "code-server": ("airlock-code-server@.service", "airlock-code-server-manager.service"),
    "dev-monitor": ("airlock-dev-monitor.service",),
    "devterm": ("airlock-devterm.service", "airlock-devterm-gate.service"),
    "feedback": ("airlock-feedback.service",),
    "learning": ("airlock-learning.service", "airlock-learning-ingest.service"),
    "fileview": ("airlock-fileview.service",),
    "notepad": (),
    "notes": ("airlock-notes-editor.service",),
    "orca": ("airlock-orca-xvfb.service", "airlock-orca.service", "airlock-orca-firewall.service@system"),
    "paseo": ("airlock-paseo.service", "airlock-paseo-browse-host.service"),
    "publish": ("airlock-publish.service", "airlock-publish-cleanup.service", "airlock-publish-cleanup.timer"),
}
ARTIFACT_CLASSES = {
    "units", "fragments", "webroot", "files", "rooted", "serve_ports", "containers",
}


def unit_key(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        if set(value) != {"name", "scope"}:
            raise ValueError(f"typed unit keys must be name/scope: {value!r}")
        if not isinstance(value.get("name"), str) or not value["name"]:
            raise ValueError(f"typed unit name must be a non-empty string: {value!r}")
        scope = value.get("scope", "user")
        if scope not in {"user", "system"}:
            raise ValueError(f"typed unit scope must be user/system: {value!r}")
        return value["name"] if scope == "user" else f"{value['name']}@{scope}"
    raise ValueError(f"invalid unit declaration: {value!r}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate-app-artifacts.py <repository-root>")
    root = Path(sys.argv[1])
    actual_apps = tuple(sorted(path.name for path in (root / "apps").iterdir() if path.is_dir()))
    if actual_apps != tuple(sorted(APPS)):
        raise SystemExit(f"app directory set drift: {actual_apps} != {tuple(sorted(APPS))}")
    for app in APPS:
        path = root / "apps" / app / "airlock-app.toml"
        try:
            manifest = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise SystemExit(f"{app}: unreadable manifest: {error}") from error
        if manifest.get("contract") != 1:
            raise SystemExit(f"{app}: contract must be 1")
        if manifest.get("id") != app:
            raise SystemExit(f"{app}: id {manifest.get('id')!r} does not match directory")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            raise SystemExit(f"{app}: [artifacts] must be a non-empty table")
        unknown_classes = sorted(set(artifacts) - ARTIFACT_CLASSES)
        if unknown_classes:
            raise SystemExit(f"{app}: unknown artifact class(es): {unknown_classes}")
        for kind, values in artifacts.items():
            if not isinstance(values, list) or not values:
                raise SystemExit(f"{app}: artifacts.{kind} must be a non-empty list")
            if kind != "units" and any(not isinstance(value, str) or not value for value in values):
                raise SystemExit(f"{app}: artifacts.{kind} entries must be non-empty strings")
            normalized = [unit_key(value) for value in values] if kind == "units" else values
            if len(normalized) != len(set(normalized)):
                raise SystemExit(f"{app}: artifacts.{kind} contains duplicates")
        try:
            units = tuple(unit_key(value) for value in artifacts.get("units", []))
        except ValueError as error:
            raise SystemExit(f"{app}: {error}") from error
        if units != EXPECTED_UNITS[app]:
            raise SystemExit(f"{app}: unit ownership drift: {units} != {EXPECTED_UNITS[app]}")
    print(f"ok: {len(APPS)}/{len(APPS)} manifests contract/id/artifacts/unit ownership")


if __name__ == "__main__":
    main()
