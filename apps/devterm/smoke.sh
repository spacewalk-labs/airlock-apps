#!/usr/bin/env bash
# devterm smoke — run against a live install (after the orchestrator rendered +
# reloaded nginx). Verifies the layered gate: ttyd (PTY) -> devterm-gate (client+API)
# -> nginx owner-gate, and that identity is owner-only at every gated layer.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=/dev/null
. "$ROOT/install/lib.sh"

airlock_load devterm
TTYD="$AIRLOCK_DEVTERM_TTYD_PORT"
BACKEND="$AIRLOCK_DEVTERM_BACKEND_PORT"
GATE="$AIRLOCK_DEVTERM_GATE_PORT"
REDIRECT="$AIRLOCK_DEVTERM_REDIRECT_PORT"
HDR="$AIRLOCK_IDENTITY_HEADER"
OWNER="${AIRLOCK_OWNER%%,*}"

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@"; }
c_ttyd=$(code "http://127.0.0.1:${TTYD}/")
# devterm-gate (loopback) re-checks identity as defense-in-depth
c_bown=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${BACKEND}/")
c_bdeny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${BACKEND}/")
c_bno=$(code                                    "http://127.0.0.1:${BACKEND}/")
# devterm-gate serves the custom client (/sessions is one of its API endpoints)
c_sess=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${BACKEND}/sessions")
# nginx owner-gate (the primary access control)
c_gown=$(code  -H "${HDR}: ${OWNER}"           "http://127.0.0.1:${GATE}/")
c_gdeny=$(code -H "${HDR}: nobody@example.com" "http://127.0.0.1:${GATE}/")
c_gno=$(code                                    "http://127.0.0.1:${GATE}/")
# plaintext port: must 301 to https and serve no content (not even to the owner)
c_redir=$(code -H "${HDR}: ${OWNER}"            "http://127.0.0.1:${REDIRECT}/")
loc_redir=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 5 "http://127.0.0.1:${REDIRECT}/")

echo "[devterm smoke] ttyd=${c_ttyd}/200 | backend owner=${c_bown}/200 deny=${c_bdeny}/403 no=${c_bno}/403 sessions=${c_sess}/200 | gate owner=${c_gown}/200 deny=${c_gdeny}/403 no=${c_gno}/403 | redirect=${c_redir}/301 -> ${loc_redir}"
fail=0
[ "$c_ttyd"  = 200 ] || { echo "FAIL ttyd direct"; fail=1; }
[ "$c_bown"  = 200 ] || { echo "FAIL backend owner not allowed"; fail=1; }
[ "$c_bdeny" = 403 ] || { echo "FAIL backend other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_bno"   = 403 ] || { echo "FAIL backend missing header not denied (GATE HOLE)"; fail=1; }
[ "$c_sess"  = 200 ] || { echo "FAIL backend /sessions API"; fail=1; }
[ "$c_gown"  = 200 ] || { echo "FAIL nginx gate owner not allowed"; fail=1; }
[ "$c_gdeny" = 403 ] || { echo "FAIL nginx gate other identity not denied (GATE HOLE)"; fail=1; }
[ "$c_gno"   = 403 ] || { echo "FAIL nginx gate missing header not denied (GATE HOLE)"; fail=1; }
[ "$c_redir" = 301 ] || { echo "FAIL plaintext port did not 301 (got ${c_redir}) — it must serve NO content"; fail=1; }
case "$loc_redir" in
  https://*) ;;
  *) echo "FAIL plaintext port redirects to '${loc_redir}' — must be an https URL"; fail=1 ;;
esac
[ "$fail" = 0 ]
