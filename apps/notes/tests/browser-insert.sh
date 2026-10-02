#!/usr/bin/env bash
# Real-browser regression for the CM6 insert repair (desktop + 390px,
# console error free). Needs python Playwright + Chromium and network access
# to the pinned esm.sh CodeMirror bundle; skips quietly otherwise so
# hermetic environments (and CI jobs without browsers) stay green.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if ! python3 -c 'import playwright' >/dev/null 2>&1; then
  echo "browser-insert: SKIP (python playwright not installed)"
  exit 0
fi
python3 "$HERE/cm6-insert-browser.py"
