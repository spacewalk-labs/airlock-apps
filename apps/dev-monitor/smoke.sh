#!/usr/bin/env bash
# dev-monitor smoke — against a live install (after orchestrator render + reload).
# Same-origin subpath, so the gate under test is the HUB nginx server.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load dev-monitor
BACKEND="$AIRLOCK_DEV_MONITOR_BACKEND_PORT"
airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_be=$(code                                    "http://127.0.0.1:${BACKEND}/api/overview")
c_ui=$(code   -H "${HDR}: ${OWNER}"            "http://127.0.0.1:${HUB}/monitor/")
c_api=$(code  -H "${HDR}: ${OWNER}"            "http://127.0.0.1:${HUB}/monitor/api/overview")
c_deny=$(code -H "${HDR}: nobody@example.com"  "http://127.0.0.1:${HUB}/monitor/api/overview")
c_no=$(code                                     "http://127.0.0.1:${HUB}/monitor/api/overview")

echo "[dev-monitor smoke] backend=${c_be}/200 ui=${c_ui}/200 api=${c_api}/200 deny=${c_deny}/403 no-header=${c_no}/403"
fail=0
[ "$c_be"   = 200 ] || { echo "FAIL backend overview"; fail=1; }
[ "$c_ui"   = 200 ] || { echo "FAIL dashboard UI"; fail=1; }
[ "$c_api"  = 200 ] || { echo "FAIL hub api overview"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$fail" = 0 ]
