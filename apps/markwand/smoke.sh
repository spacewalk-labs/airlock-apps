#!/usr/bin/env bash
# markwand smoke — against a live install (after orchestrator render + reload).
# markwand is a same-origin subpath, so the gate under test is the HUB nginx
# server (not a separate port): the /markwand/ locations re-assert $hub_ok.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load markwand
MS="$AIRLOCK_MARKWAND_MARKSERV_PORT"
FB="$AIRLOCK_MARKWAND_FILEBROWSER_PORT"
airlock_load hub
HUB="$AIRLOCK_HUB_NGINX_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$@"; }
c_ms=$(code   "http://127.0.0.1:${MS}/")
c_fb=$(code   "http://127.0.0.1:${FB}/markwand/edit/")
c_own=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/markwand/")
c_edit=$(code -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/markwand/edit/")
c_css=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/__mw/markwand-tokens.css")
c_deny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/markwand/")
c_no=$(code                                    "http://127.0.0.1:${HUB}/markwand/")

# End-to-end: the owner's rendered viewer must carry the sub_filter-injected asset
# link (proves prefix-strip + injection, not just that the gate opened). A denied
# identity must NOT receive markwand markup — it gets the wrong-owner page.
own_body=$(curl -s --max-time 6 -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${HUB}/markwand/")
deny_body=$(curl -s --max-time 6 -H "${HDR}: nobody@example.com" "http://127.0.0.1:${HUB}/markwand/")
inj=no; printf '%s' "$own_body" | grep -q '/__mw/markwand-tokens.css' && inj=yes
denied=no; printf '%s' "$deny_body" | grep -q "isn't your Airlock" && denied=yes

echo "[markwand smoke] markserv=${c_ms}/200 filebrowser=${c_fb}/200 owner=${c_own}/200 edit=${c_edit}/200 css=${c_css}/200 deny=${c_deny}/403 no-header=${c_no}/403 inject=${inj}/yes denied-page=${denied}/yes"
fail=0
[ "$c_ms"   = 200 ] || { echo "FAIL markserv backend"; fail=1; }
{ [ "$c_fb" = 200 ] || [ "$c_fb" = 302 ]; } || { echo "FAIL filebrowser backend"; fail=1; }
[ "$c_own"  = 200 ] || { echo "FAIL owner viewer"; fail=1; }
{ [ "$c_edit" = 200 ] || [ "$c_edit" = 302 ]; } || { echo "FAIL owner editor"; fail=1; }
[ "$c_css"  = 200 ] || { echo "FAIL static asset"; fail=1; }
[ "$c_deny" = 403 ] || { echo "FAIL other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_no"   = 403 ] || { echo "FAIL missing header not denied (GATE HOLE)"; fail=1; }
[ "$inj"    = yes ] || { echo "FAIL viewer asset injection (sub_filter) missing"; fail=1; }
[ "$denied" = yes ] || { echo "FAIL denied identity did not get wrong-owner page"; fail=1; }
[ "$fail" = 0 ]
