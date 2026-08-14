#!/usr/bin/env bash
# Rebuild input is the lock. A tag, a sibling app, or the process umask
# cannot move an existing artifact.
set -euo pipefail

# shellcheck source=lib.sh
source "$(cd "$(dirname "$0")" && pwd)/lib.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

digest() {
  python3 - "$FOUNDATION" "$1" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "builder"))
from digest_tree import digest_tree
print(digest_tree(sys.argv[2]))
PY
}

mint() {  # id sha out lock
  python3 "$BUILDER" --repo "$REPO" --source-path "apps/$1" \
    --id "$1" --source-sha "$2" --out "$3" --write-lock "$4" >/dev/null
}

rebuild() {  # path lock out
  python3 "$BUILDER" --repo "$REPO" --source-path "$1" \
    --lock "$2" --out "$3" >/dev/null
}

REPO="$TMP/relrepo"
mkdir -p "$REPO/apps/alpha" "$REPO/apps/beta"
printf 'alpha-v1\n' >"$REPO/apps/alpha/payload.txt"
printf 'beta-v1\n' >"$REPO/apps/beta/payload.txt"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.name probe
git -C "$REPO" config user.email probe@example.test
git -C "$REPO" add apps
git -C "$REPO" commit -q -m v1
sha1="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" tag release/v1

mint alpha "$sha1" "$TMP/alpha-v1" "$TMP/alpha.lock.json"
mint beta "$sha1" "$TMP/beta-v1" "$TMP/beta.lock.json"
alpha_v1="$(digest "$TMP/alpha-v1")"
beta_v1="$(digest "$TMP/beta-v1")"

# Cross-umask: mint at 022, rebuild at 077/002/027. Same lock, same bytes.
(
  umask 022
  mint alpha "$sha1" "$TMP/alpha-umask-mint" "$TMP/alpha-umask.lock.json"
)
for mask in 077 002 027; do
  (
    umask "$mask"
    rebuild apps/alpha "$TMP/alpha-umask.lock.json" "$TMP/alpha-umask-$mask"
  )
  if [[ "$(digest "$TMP/alpha-umask-$mask")" == "$(digest "$TMP/alpha-umask-mint")" ]]; then
    ok "rebuild under umask $mask matches mint under 022"
  else
    bad "umask $mask moved the artifact"
  fi
done

# Working tree and tag both move to v2, but only alpha's bytes change.
printf 'alpha-v2\n' >"$REPO/apps/alpha/payload.txt"
git -C "$REPO" add apps/alpha/payload.txt
git -C "$REPO" commit -q -m v2
git -C "$REPO" tag -f release/v1 >/dev/null
sha2="$(git -C "$REPO" rev-parse HEAD)"

rebuild apps/alpha "$TMP/alpha.lock.json" "$TMP/alpha-rebuild"
rebuild apps/beta "$TMP/beta.lock.json" "$TMP/beta-rebuild"

if [[ "$(digest "$TMP/alpha-rebuild")" == "$alpha_v1" ]]; then
  ok "alpha lock rebuild is byte-identical after tag retarget"
else
  bad "alpha lock rebuild moved after tag retarget"
fi
if [[ "$(digest "$TMP/beta-rebuild")" == "$beta_v1" ]]; then
  ok "beta lock rebuild unchanged after alpha+tag moved"
else
  bad "beta artifact moved after alpha source and tag changed"
fi
if [[ "$(digest "$REPO/apps/alpha")" != "$alpha_v1" ]]; then
  ok "working tree / retargeted tag now differs from the lock"
else
  bad "expected working tree to differ from the v1 lock"
fi

# Rollback is rebuild of the predecessor lock; it must not move beta.
mint alpha "$sha2" "$TMP/alpha-v2" "$TMP/alpha-v2.lock.json"
rebuild apps/alpha "$TMP/alpha.lock.json" "$TMP/alpha-rollback"
if [[ "$(digest "$TMP/alpha-rollback")" == "$alpha_v1" ]]; then
  ok "rollback rebuilds the predecessor lock"
else
  bad "rollback did not restore the predecessor artifact"
fi
if [[ "$(digest "$TMP/beta-rebuild")" == "$beta_v1" ]]; then
  ok "rolling back alpha does not move beta"
else
  bad "beta moved when alpha rolled back"
fi

# Working tree is not an input.
if python3 "$BUILDER" --source "$REPO/apps/alpha" --repo "$REPO" \
     --source-path apps/alpha --lock "$TMP/alpha.lock.json" \
     --out "$TMP/alpha-from-tree" >/dev/null 2>"$TMP/from-tree.err"; then
  bad "builder accepted --source"
else
  ok "builder refuses a working tree"
fi

python3 - "$TMP/alpha.lock.json" "$TMP/alpha-badsha.lock.json" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1], encoding="utf-8"))
lock["source_sha"] = "0" * 40
json.dump(lock, open(sys.argv[2], "w", encoding="utf-8"), indent=2, sort_keys=True)
PY
if rebuild apps/alpha "$TMP/alpha-badsha.lock.json" "$TMP/alpha-badsha" \
     2>"$TMP/badsha.err"; then
  bad "builder accepted a lock whose source_sha does not exist"
else
  ok "builder rejects a lock whose source_sha is not a commit"
fi

python3 - "$TMP/alpha.lock.json" "$sha2" "$TMP/alpha-inconsistent.lock.json" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1], encoding="utf-8"))
lock["source_sha"] = sys.argv[2]
json.dump(lock, open(sys.argv[3], "w", encoding="utf-8"), indent=2, sort_keys=True)
PY
if rebuild apps/alpha "$TMP/alpha-inconsistent.lock.json" "$TMP/alpha-inconsistent" \
     2>"$TMP/inconsistent.err"; then
  bad "builder accepted a lock whose source_sha tree != tree_digest"
else
  ok "builder rejects source_sha that does not match tree_digest"
fi

# Individual lock-field guards. Each must fail on its own.
python3 - "$TMP/beta.lock.json" "$TMP/guards" <<'PY'
import json, sys
from pathlib import Path
src = json.load(open(sys.argv[1], encoding="utf-8"))
out = Path(sys.argv[2])
out.mkdir()
cases = {
    "unknown-key": {**src, "tag": "release/v1"},
    "missing-artifact": {k: src[k] for k in src if k != "artifact_digest"},
    "missing-tree": {k: src[k] for k in src if k != "tree_digest"},
    "bad-abi": {**src, "abi": "public-app-split/v0"},
    "short-sha": {**src, "source_sha": src["source_sha"][:7]},
    "bad-artifact": {**src, "artifact_digest": "a" * 64},
}
for name, lock in cases.items():
    (out / f"{name}.lock.json").write_text(json.dumps(lock) + "\n", encoding="utf-8")
PY
for case in unknown-key missing-artifact missing-tree bad-abi short-sha bad-artifact; do
  if rebuild apps/beta "$TMP/guards/$case.lock.json" "$TMP/guards-$case" \
       2>"$TMP/guards-$case.err"; then
    bad "builder accepted $case lock"
  else
    ok "builder rejects $case lock"
  fi
done

rebuild apps/beta "$TMP/beta.lock.json" "$TMP/beta-clean-a"
rebuild apps/beta "$TMP/beta.lock.json" "$TMP/beta-clean-b"
if [[ "$(digest "$TMP/beta-clean-a")" == "$(digest "$TMP/beta-clean-b")" ]]; then
  ok "clean-room rebuild is byte-identical"
else
  bad "clean-room rebuilds differed"
fi

finish
