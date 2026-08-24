"""Validate public-app lifecycle declarations. Exit 1 if the set is incomplete."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

APPS = (
    "code-server", "dev-monitor", "devterm", "feedback",
    "markwand", "notepad", "notes", "orca", "paseo", "publish",
)
REQUIRED = (
    "id", "state", "quiesce", "snapshot", "forward",
    "write_capture", "reverse", "rpo", "paths", "capabilities",
)
NONE_FIELDS = ("quiesce", "snapshot", "forward", "write_capture", "reverse")
CAPABILITIES = ("rooted-artifact", "system-unit")
EXPECTED_CAPABILITIES = {
    "orca": ("rooted-artifact", "system-unit"),
}
EXPECTED_PATHS = {
    "code-server": (
        "~/.local/share/airlock-code-server/",
        "~/.config/airlock-code-server/tabs.json",
        "~/.config/code-server/",
    ),
    "dev-monitor": (
        "~/.local/state/airlock/dev-monitor/",
        "~/.local/share/airlock-dev-monitor/history.csv",
    ),
    "devterm": (
        "~/.config/airlock-devterm/tabs.json",
        "~/.local/state/airlock/devterm/codex-usage.json",
    ),
    "feedback": (),
    "markwand": ("~/.config/filebrowser/fb.db",),
    "notepad": (),
    "notes": (),
    "orca": (),
    "paseo": ("~/.paseo/",),
    "publish": (
        "/opt/airlock/share",
        "~/uploads",
        "~/.local/state/airlock/publish-public.json",
    ),
}


def schema_drift(foundation: Path) -> list[str]:
    path = foundation / "abi" / "lifecycle.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    if set(schema.get("required", [])) != set(REQUIRED):
        errors.append(
            f"schema.required {schema.get('required')} != validator {list(REQUIRED)}"
        )
    if schema.get("additionalProperties") is not False:
        errors.append("schema must set additionalProperties false")
    state = (schema.get("properties") or {}).get("state") or {}
    if set(state.get("enum") or []) != {"stateless", "stateful"}:
        errors.append(f"schema state enum drifted: {state}")
    rpo = (schema.get("properties") or {}).get("rpo") or {}
    if set(rpo.get("enum") or []) != {"none", "0"}:
        errors.append(f"schema rpo enum drifted: {rpo}")
    caps = (((schema.get("properties") or {}).get("capabilities") or {}).get("items") or {})
    if set(caps.get("enum") or []) != set(CAPABILITIES):
        errors.append(f"schema capabilities enum drifted: {caps}")
    return errors


def path_mentioned(app_root: Path, name: str, retained: str) -> bool:
    needle = retained.rstrip("/")
    for rel in (f"{name}/airlock-app.toml", f"{name}/deactivate.sh"):
        path = app_root / rel
        if path.is_file() and needle in path.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def validate(foundation: Path, app_root: Path | None = None) -> list[str]:
    errors = schema_drift(foundation)
    present = sorted(p.stem for p in (foundation / "abi" / "apps").glob("*.toml"))
    if present != list(APPS):
        errors.append(f"abi/apps set {present} != {list(APPS)}")
        return errors
    for name in APPS:
        path = foundation / "abi" / "apps" / f"{name}.toml"
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        unknown = sorted(set(doc) - set(REQUIRED))
        missing = [key for key in REQUIRED if key not in doc]
        if unknown:
            errors.append(f"{name}: unknown key(s) {unknown}")
            continue
        if missing:
            errors.append(f"{name}: missing key(s) {missing}")
            continue
        if doc["id"] != name:
            errors.append(f"{name}: id {doc['id']!r} does not match filename")
        if doc["state"] not in {"stateless", "stateful"}:
            errors.append(f"{name}: bad state {doc['state']!r}")
            continue
        if not isinstance(doc["paths"], list) or any(
                not isinstance(item, str) or not item for item in doc["paths"]):
            errors.append(f"{name}: paths must be a list of non-empty strings")
            continue
        if tuple(doc["paths"]) != EXPECTED_PATHS[name]:
            errors.append(
                f"{name}: paths {doc['paths']} != {list(EXPECTED_PATHS[name])}"
            )
        if not isinstance(doc["capabilities"], list) or any(
                item not in CAPABILITIES for item in doc["capabilities"]):
            errors.append(f"{name}: capabilities must be a list from {CAPABILITIES}")
            continue
        if tuple(doc["capabilities"]) != EXPECTED_CAPABILITIES.get(name, ()):
            errors.append(
                f"{name}: capabilities {doc['capabilities']} != "
                f"{list(EXPECTED_CAPABILITIES.get(name, ()))}"
            )
        if doc["state"] == "stateless":
            if any(doc[key] != "none" for key in NONE_FIELDS) or doc["rpo"] != "none" or doc["paths"]:
                errors.append(f"{name}: stateless declaration must be all none with empty paths")
        else:
            if doc["rpo"] != "0":
                errors.append(f"{name}: stateful rpo must be \"0\"")
            for key in ("forward", "write_capture", "reverse"):
                if doc[key] == "pending-parity":
                    errors.append(f"{name}: {key} is still pending-parity")
            if not doc["paths"]:
                errors.append(f"{name}: stateful declaration needs at least one retained path")
            if all(doc[key] == "none" for key in NONE_FIELDS):
                errors.append(f"{name}: stateful declaration cannot be all-none procedures")
            if app_root is not None:
                for retained in doc["paths"]:
                    if not path_mentioned(app_root, name, retained):
                        errors.append(
                            f"{name}: declared path {retained!r} is not mentioned "
                            f"in apps/{name}/airlock-app.toml or deactivate.sh"
                        )
    return errors


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        sys.stderr.write("usage: validate_lifecycle.py <foundation-root> [app-root]\n")
        raise SystemExit(2)
    app_root = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    errors = validate(Path(sys.argv[1]), app_root)
    if errors:
        sys.stderr.write("\n".join(errors) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
