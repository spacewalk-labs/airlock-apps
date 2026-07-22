#!/usr/bin/env bash
# devterm smoke — run against a live install (after the orchestrator rendered +
# reloaded nginx). Verifies the gate is owner-only and not a hole.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load devterm
TTYD="$AIRLOCK_DEVTERM_TTYD_PORT"
GATE="$AIRLOCK_DEVTERM_GATE_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@"; }
c_ttyd=$(code "http://127.0.0.1:${TTYD}/")
c_own=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${GATE}/")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${GATE}/")
c_no=$(code                                    "http://127.0.0.1:${GATE}/")

echo "[devterm smoke] ttyd=${c_ttyd}/200 owner=${c_own}/200 deny=${c_deny}/403 no-header=${c_no}/403"
fail=0
[ "$c_ttyd" = 200 ] || { echo "FAIL ttyd direct"; fail=1; }
[ "$c_own"  = 200 ] || { echo "FAIL owner not allowed"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$fail" = 0 ]
