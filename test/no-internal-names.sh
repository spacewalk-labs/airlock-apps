#!/usr/bin/env bash
# test/no-internal-names.sh — nothing in this repository may name an internal
# host, tailnet, or checkout path.
#
# Why it exists: on 2026-08-25 a scan found internal identifiers on `main`, in
# eight files, present since the repository's first content commit. Nothing here
# was looking. The sibling private repository has had this gate since
# 2026-08-07; this is the same idea, written for a tree that is public from the
# start.
#
# 🔴 SHAPES, NOT NAMES. The rules describe the FORM of an internal identifier
# and never spell one. That is not stylistic: a denylist of names in a public
# file publishes exactly what it exists to stop, and it only catches the names
# somebody already thought of. A name that no shape can express does not belong
# here — it belongs in the private publish-sync scan, which is never mirrored.
#
# What is deliberately NOT here: operator email addresses. The shape of an
# address is the shape of a systemd template unit (`airlock-code-server@1.service`,
# `user@1001.service`) and of every vendored copyright line, so the rule was
# noise on this tree. Addresses are caught by the private scan.
#
# `grep -P` for lookarounds: each rule has to say "this shape, except ours".
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SELF="test/$(basename "$0")"

# apps/orca/web-bundle/ is a VENDORED upstream build. Orca ships Tailscale as a
# feature, so its i18n bundles carry tailnet placeholders, and its minified
# assets contain box-shaped and home-path-shaped tokens by accident. Shapes
# cannot separate ours from theirs there, so that tree is scanned by
# apps/orca/bin/verify-web-bundle.sh with anchors instead.
EXCLUDES=(':(exclude)apps/orca/web-bundle/*' ":(exclude)$SELF")

#  a box hostname          — `<word>-dev` / `<word>-mgmt`, but not our own
#                            `airlock-dev-monitor`, and not the bare `dev-...`
#  a tailnet address       — `<host>.<tailnet>.ts.net`, but not the reserved
#                            `example.` used by this repository's own tests
#  somebody's checkout     — `/home/<user>/workspace/`
PATTERN='(?<![a-z0-9-])(?!airlock-)[a-z0-9]+-(?:dev|mgmt)(?![a-z0-9-])'
PATTERN="$PATTERN"'|[a-z0-9-]+\.(?!example\.)[a-z0-9-]+\.ts\.net'
PATTERN="$PATTERN"'|/home/[a-z][a-z0-9_-]*/workspace/'

if [ "${1:-}" = "--print-pattern" ]; then printf '%s\n' "$PATTERN"; exit 0; fi

# --self-test runs in CI alongside the scan. A denylist that quietly stops
# matching reports "clean" forever, which is the failure mode this whole file
# exists to prevent — so the rules are exercised on both sides every run.
if [ "${1:-}" = "--self-test" ]; then
  fails=0
  # Split so this file holds no literal that the rules deny.
  d=de; d=${d}v
  m=mg; m=${m}mt
  # Assembled, not written out: a probe has to MATCH the shape it proves, and a
  # literal match here is a hit for any other scanner reading this file. Each
  # half is harmless on its own.
  must_hit=("quokka-${d}" "somebox.our-tailnet.ts.net" "/home/someone/workspace/x" "a-${m}")
  must_miss=('airlock-dev-monitor.service' 'box.example.ts.net' 'dev-monitor'
             'airlock-code-server@1.service' 'user@1001.service' 'apps/orca/web-bundle')
  for probe in "${must_hit[@]}"; do
    printf '%s' "$probe" | grep -qP "$PATTERN" || { echo "self-test: rule never fires on $probe"; fails=1; }
  done
  for probe in "${must_miss[@]}"; do
    printf '%s' "$probe" | grep -qP "$PATTERN" && { echo "self-test: false positive on $probe"; fails=1; }
  done
  [ "$fails" = 0 ] || exit 1
  echo "no-internal-names: self-test ok (${#must_hit[@]} deny / ${#must_miss[@]} allow)"
  exit 0
fi

hits="$(git -C "$ROOT" grep --untracked -nPI "$PATTERN" -- . "${EXCLUDES[@]}" 2>/dev/null || true)"
if [ -n "$hits" ]; then
  printf '%s\n' "$hits"
  echo "::error::Internal/site-specific string found — scrub before commit."
  exit 1
fi
echo "no-internal-names: clean"
