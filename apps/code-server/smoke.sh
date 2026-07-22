#!/usr/bin/env bash
# code-server smoke — against a live install (after orchestrator render + reload).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load code-server
GATE="$AIRLOCK_CODE_SERVER_GATE_PORT"
BACKEND="$AIRLOCK_CODE_SERVER_BACKEND_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_be=$(code   "http://127.0.0.1:${BACKEND}/")
c_own=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${GATE}/")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${GATE}/")
c_no=$(code                                    "http://127.0.0.1:${GATE}/")

echo "[code-server smoke] backend=${c_be}/200|302 owner=${c_own}/200|302 deny=${c_deny}/403 no-header=${c_no}/403"
fail=0
{ [ "$c_be" = 200 ] || [ "$c_be" = 302 ]; }   || { echo "FAIL backend"; fail=1; }
{ [ "$c_own" = 200 ] || [ "$c_own" = 302 ]; } || { echo "FAIL owner"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL deny (gate hole)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL no-header (gate hole)"; fail=1; }
[ "$fail" = 0 ]
