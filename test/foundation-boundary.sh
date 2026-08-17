#!/usr/bin/env bash
# Trust-independent foundation gate for the public-app split.
set -euo pipefail

# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

set +e
python3 - "$FOUNDATION" "${CORE_ROOT:-}" "$APP_ROOT" <<'PY' | tee "$TMP/py.out"
import hashlib, json, re, sys
from pathlib import Path

foundation = Path(sys.argv[1])
core_root = Path(sys.argv[2]) if sys.argv[2] else None
app_root = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
failed = 0

def ok(msg):
    print(f"ok   {msg}")

def bad(msg):
    global failed
    failed += 1
    print(f"FAIL {msg}")

sys.path.insert(0, str(foundation / "test"))
from validate_lifecycle import APPS, validate

# --- ABI files present -------------------------------------------------------
for rel in ("abi/core-app-manifest.md", "abi/lifecycle.schema.json",
            "lock/schema.md", "builder/build-release.py",
            "builder/digest_tree.py", "TRANSFER.md", "foundation.json"):
    if (foundation / rel).is_file():
        ok(f"present {rel}")
    else:
        bad(f"missing {rel}")

# --- lifecycle declarations: 9/9, closed ------------------------------------
lifecycle_errors = validate(foundation, app_root)
if lifecycle_errors:
    for item in lifecycle_errors:
        bad(item)
else:
    ok("lifecycle 9/9")

# --- foundation.json ---------------------------------------------------------
pin_path = foundation / "foundation.json"
try:
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    bad(f"foundation.json: {exc}")
    pin = {}

def expect(obj, key, value, label):
    if obj.get(key) == value:
        ok(label)
    else:
        bad(f"{label}: got {obj.get(key)!r} want {value!r}")

expect(pin, "milestone", "public-app-split/foundation", "milestone id")
expect(pin, "trust_independent", True, "trust-independent flag")
abi = pin.get("abi") if isinstance(pin.get("abi"), dict) else {}
expect(abi, "id", "public-app-split/v1", "abi id")
if abi.get("core_contract") == [1]:
    ok("core contract window [1]")
else:
    bad(f"core contract window: {abi.get('core_contract')!r}")

repo = pin.get("repository") if isinstance(pin.get("repository"), dict) else {}
if repo.get("status") in {"uncreated", "created"}:
    ok(f"repository status {repo.get('status')}")
else:
    bad(f"repository status: {repo.get('status')!r}")
if repo.get("planned_name") != "airlock-apps":
    bad(f"planned_name {repo.get('planned_name')!r}")
else:
    ok("planned repository name recorded")

lock = pin.get("lock") if isinstance(pin.get("lock"), dict) else {}
expect(lock, "tag_role", "display-label", "tag is a label")
if lock.get("rebuild_input") == ["source_sha", "tree_digest", "artifact_digest"]:
    ok("lock rebuild input")
else:
    bad(f"lock rebuild input: {lock.get('rebuild_input')!r}")

history = pin.get("history") if isinstance(pin.get("history"), dict) else {}
if history.get("apps") == list(APPS):
    ok("history app list")
else:
    bad(f"history apps: {history.get('apps')!r}")
if history.get("export_rev") == "HEAD" and history.get("rehearsal_asserts") == [
        "manifest-byte-identical", "commit-count-equal"]:
    ok("history evidence asserts")
else:
    bad(f"history evidence asserts: {history!r}")

# pin digest over the ABI/lock contract files
digest_files = [
    "abi/core-app-manifest.md",
    "abi/lifecycle.schema.json",
    "lock/schema.md",
]
digest_files += [f"abi/apps/{name}.toml" for name in APPS]
hasher = hashlib.sha256()
for rel in digest_files:
    data = (foundation / rel).read_bytes()
    hasher.update(len(rel.encode()).to_bytes(8, "big"))
    hasher.update(rel.encode())
    hasher.update(len(data).to_bytes(8, "big"))
    hasher.update(data)
actual_digest = hasher.hexdigest()
if abi.get("digest") == actual_digest:
    ok("foundation abi digest")
else:
    bad(f"foundation abi digest mismatch\n  pinned: {abi.get('digest')}\n  actual: {actual_digest}")

# --- builder refuses tags ----------------------------------------------------
builder = (foundation / "builder" / "build-release.py").read_text(encoding="utf-8")
if re.search(r"--tag\b", builder):
    bad("builder accepts --tag")
else:
    ok("builder has no --tag input")
if "LOCK_KEYS" in builder and "source_sha" in builder:
    ok("builder lock keys named")
else:
    bad("builder does not name lock keys")

# --- core still path-only ----------------------------------------------------
if core_root is not None:
    cfg = (core_root / "bin" / "airlock-config").read_text(encoding="utf-8")
    if "package manager: no " in cfg and "no fetching" in cfg:
        ok("core still rejects remote package sources")
    else:
        bad("core lost the D1 path-only rejection")
    if "digest_tree" in (core_root / "bin" / "airlock-ledger").read_text(encoding="utf-8"):
        ok("core digest_tree still present to reuse")
    else:
        bad("bin/airlock-ledger lost digest_tree")
else:
    ok("core not in this checkout (post-transfer layout)")

sys.exit(1 if failed else 0)
PY
status=${PIPESTATUS[0]}
set -e
while IFS= read -r line; do
  case "$line" in
    ok*) pass=$((pass + 1)) ;;
    FAIL*) fail=$((fail + 1)) ;;
  esac
done <"$TMP/py.out"
if [[ "$status" -ne 0 && "$fail" -eq 0 ]]; then
  bad "python foundation checks crashed"
fi

# Negative: a missing lifecycle file must be red. Probe the same validator
# logic by hiding one declaration in a copy.
mkdir -p "$TMP/probe/abi/apps"
cp -a "$FOUNDATION/abi/." "$TMP/probe/abi/"
cp -a "$FOUNDATION/lock" "$TMP/probe/lock"
cp -a "$FOUNDATION/builder" "$TMP/probe/builder"
cp "$FOUNDATION/TRANSFER.md" "$FOUNDATION/foundation.json" "$TMP/probe/"
rm -f "$TMP/probe/abi/apps/notepad.toml"
if python3 "$FOUNDATION/test/validate_lifecycle.py" "$TMP/probe" \
     >/dev/null 2>"$TMP/probe.err"; then
  bad "missing lifecycle declaration was not detected"
else
  if grep -q 'notepad' "$TMP/probe.err"; then
    ok "missing lifecycle declaration is red"
  else
    bad "validator failed for another reason: $(cat "$TMP/probe.err")"
  fi
fi

# Content: a fabricated retained path must be red when app sources are checked.
mkdir -p "$TMP/probe-content/abi/apps"
cp -a "$FOUNDATION/abi/." "$TMP/probe-content/abi/"
python3 - "$TMP/probe-content/abi/apps/paseo.toml" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8").replace("~/.paseo/", "~/.not-a-real-paseo-home/")
path.write_text(text, encoding="utf-8")
PY
if python3 "$FOUNDATION/test/validate_lifecycle.py" "$TMP/probe-content" "$APP_ROOT" \
     >/dev/null 2>"$TMP/probe-content.err"; then
  bad "fabricated lifecycle path was accepted"
else
  if grep -q 'not-a-real-paseo-home' "$TMP/probe-content.err"; then
    ok "fabricated lifecycle path is red"
  else
    bad "content check failed for another reason: $(cat "$TMP/probe-content.err")"
  fi
fi

# Content: removing one known retained path must also be red. Otherwise a
# lifecycle fixture could stay green by iterating only an incomplete ABI list.
mkdir -p "$TMP/probe-omission/abi/apps"
cp -a "$FOUNDATION/abi/." "$TMP/probe-omission/abi/"
python3 - "$TMP/probe-omission/abi/apps/dev-monitor.toml" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
line = '  "~/.local/share/airlock-dev-monitor/history.csv",\n'
text = path.read_text(encoding="utf-8")
if text.count(line) != 1:
    raise SystemExit("fixture anchor drift")
path.write_text(text.replace(line, ""), encoding="utf-8")
PY
if python3 "$FOUNDATION/test/validate_lifecycle.py" "$TMP/probe-omission" "$APP_ROOT" \
     >/dev/null 2>"$TMP/probe-omission.err"; then
  bad "omitted retained lifecycle path was not detected"
else
  if grep -q 'history.csv' "$TMP/probe-omission.err"; then
    ok "omitted retained lifecycle path is red"
  else
    bad "omission check failed for another reason: $(cat "$TMP/probe-omission.err")"
  fi
fi

# digest_tree reuse: builder copy matches ledger on a fixture, when core exists
if [[ -n "$CORE_ROOT" ]]; then
  mkdir -p "$TMP/fixture/sub"
  printf 'alpha\n' >"$TMP/fixture/a.txt"
  printf 'beta\n' >"$TMP/fixture/sub/b.txt"
  ln -s a.txt "$TMP/fixture/link"
  chmod 644 "$TMP/fixture/a.txt" "$TMP/fixture/sub/b.txt"
  ledger_digest="$(python3 - "$CORE_ROOT" "$TMP/fixture" <<'PY'
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
path = Path(sys.argv[1]) / "bin" / "airlock-ledger"
mod = SourceFileLoader("_airlock_ledger", str(path)).load_module()
print(mod.digest_tree(sys.argv[2]))
PY
)"
  builder_digest="$(python3 - "$FOUNDATION" "$TMP/fixture" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "builder"))
from digest_tree import digest_tree
print(digest_tree(sys.argv[2]))
PY
)"
  if [[ "$ledger_digest" == "$builder_digest" && -n "$ledger_digest" ]]; then
    ok "builder digest_tree matches ledger on fixture"
  else
    bad "digest_tree mismatch ledger=$ledger_digest builder=$builder_digest"
  fi
fi

# history evidence: each app path has at least one commit in this clone
if git -C "$APP_ROOT/.." rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  hist_ok=1
  for app in "${PUBLIC_APPS[@]}"; do
    count="$(git -C "$APP_ROOT/.." rev-list --count HEAD -- "apps/$app" 2>/dev/null || echo 0)"
    if [[ "$count" -lt 1 ]]; then
      bad "no git history for apps/$app"
      hist_ok=0
    fi
  done
  if [[ "$hist_ok" -eq 1 ]]; then
    ok "git history exists for all 9 app paths"
  fi
else
  ok "skip history count (not a git checkout)"
fi

if git -C "$APP_ROOT/.." rev-parse --is-inside-work-tree >/dev/null 2>&1 \
   && [[ -f "$FOUNDATION/rehearsal/transfer-dry-run.sh" ]]; then
  if bash "$FOUNDATION/rehearsal/transfer-dry-run.sh"; then
    ok "history-preserving transfer rehearsal"
  else
    bad "history-preserving transfer rehearsal"
  fi
fi

finish
