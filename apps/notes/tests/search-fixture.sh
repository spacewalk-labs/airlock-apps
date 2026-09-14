#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="sec77/perlite@sha256:e4912b9a014b5f68b0f29386244e5600e935de09e66906fb13e849f54d2b300c"
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

mkdir -p "$FIXTURE/프로젝트" "$FIXTURE/회의록"
cat > "$FIXTURE/프로젝트/Roadmap.md" <<'EOF'
# Roadmap

가을 출시 순서를 정리한다.
EOF
cat > "$FIXTURE/회의록/검색 점검.md" <<'EOF'
# 검색 점검

참석자는 독자가 기억하는 표현을 모았다.

blue umbrella 문장을 본문 검색 고정 질의로 쓴다.
결제 승인 흐름은 두 번째 고정 질의다.
EOF
cat > "$FIXTURE/오래된 문서.md" <<'EOF'
# 오래된 문서

과거 기록이다.
EOF
touch -d '2026-09-10T00:00:00Z' "$FIXTURE/오래된 문서.md"
touch -d '2026-09-13T00:00:00Z' "$FIXTURE/프로젝트/Roadmap.md"
touch -d '2026-09-14T00:00:00Z' "$FIXTURE/회의록/검색 점검.md"

docker image inspect "$IMAGE" >/dev/null

run_search() {
  docker run --rm --network none --read-only \
    --entrypoint php \
    --mount "type=bind,src=$HERE/reader/search.php,dst=/search.php,readonly" \
    --mount "type=bind,src=$FIXTURE,dst=/notes,readonly" \
    "$IMAGE" /search.php /notes "$1"
}

title_json="$(run_search 'roadmap')"
body_json="$(run_search 'blue umbrella')"
korean_json="$(run_search '결제 승인')"
recent_json="$(run_search '')"

python3 - "$title_json" "$body_json" "$korean_json" "$recent_json" <<'PY'
import json
import sys

title, body, korean, recent = map(json.loads, sys.argv[1:])
assert title["results"][0]["page"] == "프로젝트/Roadmap"
assert title["results"][0]["match"] == "title"
assert body["results"][0]["page"] == "회의록/검색 점검"
assert body["results"][0]["line"] == 5
assert "blue umbrella" in body["results"][0]["snippet"]
assert korean["results"][0]["page"] == "회의록/검색 점검"
assert korean["results"][0]["line"] == 6
assert recent["results"][0]["page"] == "회의록/검색 점검"
assert recent["results"][1]["page"] == "프로젝트/Roadmap"
for payload in (title, body, korean, recent):
    assert payload["files_scanned"] == 3
    assert isinstance(payload["elapsed_ms"], (int, float))
print("FOLIO_SEARCH_QUERIES_OK title=1 body=1 korean=1 recent_order=1")
PY

samples="$(for _ in $(seq 1 20); do run_search 'blue umbrella'; done)"
python3 - "$samples" <<'PY'
import json
import statistics
import sys

values = sorted(json.loads(line)["elapsed_ms"] for line in sys.argv[1].splitlines())
p95 = values[max(0, int(len(values) * 0.95) - 1)]
print(
    "FOLIO_SEARCH_BASELINE "
    f"runs={len(values)} files=3 p50_ms={statistics.median(values):.2f} "
    f"p95_ms={p95:.2f} max_ms={max(values):.2f} threshold=unset"
)
PY
