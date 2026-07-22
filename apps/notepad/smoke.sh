#!/usr/bin/env bash
# notepad smoke — against a live install (after orchestrator render + reload).
# Static page behind the hub; upload API is covered by the publish smoke.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_ui=$(code   -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/notepad/")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/notepad/")
c_no=$(code                                    "http://127.0.0.1:${HUB}/notepad/")

echo "[notepad smoke] ui=${c_ui}/200 deny=${c_deny}/403 no-header=${c_no}/403"
fail=0
[ "$c_ui"   = 200 ] || { echo "FAIL notepad UI"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$fail" = 0 ]
