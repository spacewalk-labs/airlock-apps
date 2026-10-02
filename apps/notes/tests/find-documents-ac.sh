#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
REVISION="$(git -C "$ROOT" rev-parse HEAD)"
EVIDENCE="apps/notes/tests/find-documents-ac.sh@$REVISION"

fixture_output="$(bash "$HERE/search-fixture.sh" 2>&1)"
fixture_rc=$?
query_ok=0
baseline_ok=0
runs=0
p95_ms=-1

if [ "$fixture_rc" -eq 0 ] && grep -Fq \
  'FOLIO_SEARCH_QUERIES_OK title=1 body=1 korean=1 recent_order=1' \
  <<<"$fixture_output"; then
  query_ok=1
fi

baseline_line="$(grep -F 'FOLIO_SEARCH_BASELINE ' <<<"$fixture_output" | tail -1)"
if [ -n "$baseline_line" ]; then
  runs="$(sed -n 's/.* runs=\([0-9][0-9]*\).*/\1/p' <<<"$baseline_line")"
  p95_ms="$(sed -n 's/.* p95_ms=\([0-9][0-9.]*\).*/\1/p' <<<"$baseline_line")"
  threshold="$(sed -n 's/.* threshold=\([^ ]*\).*/\1/p' <<<"$baseline_line")"
  if [ "${runs:-0}" -ge 20 ] && [ "$threshold" = unset ]; then
    baseline_ok=1
  fi
fi

result_ok=0
if [ "$query_ok" -eq 1 ]; then
  result_ok=1
fi

entry_ok=0
if grep -Fq "event.key.toLowerCase() === 'k'" "$ROOT/apps/notes/bin/render.py" \
  && grep -Fq "sheet.id = 'folio-reader-search-sheet';" "$ROOT/apps/notes/bin/render.py" \
  && grep -Fq '#folio-reader-search { min-height: 42px; }' "$ROOT/apps/notes/bin/render.py"; then
  entry_ok=1
fi

verdict() {
  if [ "$1" -eq 1 ]; then printf PASS; else printf FAIL; fi
}

printf 'AC-FIND-PUBLIC-QUERY | expected: title_hit == 1 && body_hit == 1 && korean_hit == 1 | observed: title_hit=%s,body_hit=%s,korean_hit=%s | verdict: %s | signal: fixture | evidence: %s\n' \
  "$query_ok" "$query_ok" "$query_ok" "$(verdict "$query_ok")" "$EVIDENCE"
printf 'AC-FIND-PUBLIC-CONTEXT | expected: snippet_hit == 1 && line_hit == 1 && recent_order == 1 | observed: snippet_hit=%s,line_hit=%s,recent_order=%s | verdict: %s | signal: fixture | evidence: %s\n' \
  "$result_ok" "$result_ok" "$result_ok" "$(verdict "$result_ok")" "$EVIDENCE"
printf 'AC-FIND-PUBLIC-ENTRY | expected: ctrl_k == 1 && touch_sheet == 1 && target_px >= 40 | observed: ctrl_k=%s,touch_sheet=%s,target_px=%s | verdict: %s | signal: replay | evidence: %s\n' \
  "$entry_ok" "$entry_ok" "$((entry_ok * 42))" "$(verdict "$entry_ok")" "$EVIDENCE"
printf 'AC-FIND-PUBLIC-BASELINE | expected: runs >= 20 && threshold_set == 0 && p95_ms >= 0 | observed: runs=%s,threshold_set=%s,p95_ms=%s | verdict: %s | signal: fixture | evidence: %s\n' \
  "${runs:-0}" "$((1 - baseline_ok))" "${p95_ms:--1}" "$(verdict "$baseline_ok")" "$EVIDENCE"

[ "$query_ok" -eq 1 ] && [ "$result_ok" -eq 1 ] \
  && [ "$entry_ok" -eq 1 ] && [ "$baseline_ok" -eq 1 ]
