#!/usr/bin/env bash
# Verify a vendored Orca web client against every field in its provenance pin.
set -euo pipefail

QUIET=0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="$(cd "$HERE/.." && pwd)/web-bundle"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --quiet) QUIET=1; shift ;;
    --bundle) [ "$#" -ge 2 ] || { echo "--bundle requires a path" >&2; exit 2; }; BUNDLE="$2"; shift 2 ;;
    *) echo "usage: $0 [--quiet] [--bundle DIR]" >&2; exit 2 ;;
  esac
done

say() { [ "$QUIET" = 1 ] || printf '[orca-bundle] %s\n' "$*" >&2; }
fail() { printf '[orca-bundle] MISMATCH: %s\n' "$*" >&2; exit 1; }
pin() {
  local key="$1" matches
  matches="$(sed -n "s/^${key}: *//p" "$PIN")"
  [ "$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l)" = 1 ] \
    || fail "VERSION must contain exactly one ${key} field"
  printf '%s' "$matches"
}

DIST="$BUNDLE/dist"
PIN="$BUNDLE/VERSION"
[ -f "$PIN" ] || fail "no VERSION pin at $PIN"
[ -d "$DIST" ] || fail "no dist/ at $DIST"
[ ! -L "$DIST" ] || fail "dist may not be a symlink"
if find "$DIST" -type l -print -quit | grep -q .; then fail "dist contains a symlink"; fi

want_ver="$(pin orca-appimage-version)"
want_source="$(pin web-source-commit)"
want_idx="$(pin web-index-asset)"
want_n="$(pin dist-file-count)"
want_sha="$(pin dist-tree-sha256)"
[[ "$want_ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "invalid orca-appimage-version"
[[ "$want_source" =~ ^[0-9a-f]{40}$ ]] || fail "invalid web-source-commit"
[[ "$want_idx" =~ ^assets/web-index-[A-Za-z0-9_-]+\.js$ ]] || fail "invalid web-index-asset"
[[ "$want_n" =~ ^[1-9][0-9]*$ ]] || fail "invalid dist-file-count"
[[ "$want_sha" =~ ^[0-9a-f]{64}$ ]] || fail "invalid dist-tree-sha256"

[ -f "$DIST/web-index.html" ] || fail "dist/web-index.html absent"
python3 - "$DIST/web-index.html" <<'PY' || fail "web-index.html lacks a complete body/html ending"
import pathlib, re, sys
body = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
raise SystemExit(0 if re.search(r"</body>\s*</html>\s*$", body, re.I) else 1)
PY
mapfile -t entry_assets < <(grep -oE 'assets/web-index-[A-Za-z0-9_-]+\.js' "$DIST/web-index.html" | sort -u)
[ "${#entry_assets[@]}" = 1 ] || fail "web-index.html must reference exactly one hashed web-index asset"
[ "${entry_assets[0]}" = "$want_idx" ] || fail "entry asset ${entry_assets[0]} != $want_idx (pinned)"
[ -f "$DIST/$want_idx" ] || fail "entry asset $want_idx absent"

got_n="$(find "$DIST" -type f | wc -l | tr -d ' ')"
[ "$got_n" = "$want_n" ] || fail "file count $got_n != $want_n (pinned)"
got_sha="$(cd "$DIST" && find . -type f | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)"
[ "$got_sha" = "$want_sha" ] || fail "tree sha256 $got_sha != $want_sha (pinned)"

if LC_ALL=C grep -RInaE --binary-files=without-match \
  'spacewalk|sparrow-spectrum|josh-dev|cho@|swk-|TeamSPWK|install-canary-gate\.sh|orca-web\.' \
  "$DIST" >/dev/null; then
  fail "dist contains a denied internal/operator identifier"
fi

say "dist matches VERSION ($want_n files, source $want_source, entry $want_idx)"
