#!/usr/bin/env bash
# publish smoke — against a live install (after orchestrator render + reload).
# Same-origin subpath, so the gate under test is the HUB nginx server.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load publish
BACKEND="$AIRLOCK_PUBLISH_BACKEND_PORT"
airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_be=$(code   "http://127.0.0.1:${BACKEND}/api/health")
c_ui=$(code   -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/publish/")
c_list=$(code -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/publish/api/list")
c_files=$(code -H "${HDR}: ${OWNER}"          "http://127.0.0.1:${HUB}/publish/files/")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/publish/api/list")
c_no=$(code                                    "http://127.0.0.1:${HUB}/publish/api/list")
# the list endpoint must return valid JSON with ok:true for the owner
okjson=no; curl -s --max-time 6 -H "${HDR}: ${OWNER}" "http://127.0.0.1:${HUB}/publish/api/list" | grep -q '"ok": *true' && okjson=yes

echo "[publish smoke] backend=${c_be}/200 ui=${c_ui}/200 list=${c_list}/200 files=${c_files}/200 deny=${c_deny}/403 no-header=${c_no}/403 list-json=${okjson}/yes"
fail=0
[ "$c_be"   = 200 ] || { echo "FAIL backend health"; fail=1; }
[ "$c_ui"   = 200 ] || { echo "FAIL manager UI"; fail=1; }
[ "$c_list" = 200 ] || { echo "FAIL list endpoint"; fail=1; }
{ [ "$c_files" = 200 ] || [ "$c_files" = 403 ] || [ "$c_files" = 404 ]; } || { echo "FAIL files location broken ($c_files)"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$okjson" = yes ] || { echo "FAIL list did not return ok:true json"; fail=1; }
[ "$fail" = 0 ]
