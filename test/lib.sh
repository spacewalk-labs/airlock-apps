# shared by foundation-boundary.sh and app-release-isolation.sh
# shellcheck shell=bash

PUBLIC_APPS=(code-server dev-monitor devterm feedback markwand notepad notes orca paseo publish)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FOUNDATION="$(cd "$HERE/.." && pwd)"
BUILDER="$FOUNDATION/builder/build-release.py"

if [[ -d "$FOUNDATION/../../apps/notepad" ]]; then
  APP_ROOT="$(cd "$FOUNDATION/../../apps" && pwd)"
elif [[ -d "$FOUNDATION/apps/notepad" ]]; then
  APP_ROOT="$FOUNDATION/apps"
else
  echo "FAIL cannot locate apps/ next to foundation tree $FOUNDATION" >&2
  exit 1
fi

CORE_ROOT=""
if [[ -f "$APP_ROOT/../bin/airlock-config" && -f "$APP_ROOT/../bin/airlock-ledger" ]]; then
  CORE_ROOT="$(cd "$APP_ROOT/.." && pwd)"
fi

pass=0
fail=0
ok()  { printf 'ok   %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf 'FAIL %s\n' "$1"; fail=$((fail + 1)); }

finish() {
  printf '%s passed, %s failed\n' "$pass" "$fail"
  if [[ "$fail" -ne 0 ]]; then
    exit 1
  fi
}
