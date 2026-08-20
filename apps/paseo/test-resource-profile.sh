#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
. "$HERE/resource-profile.sh"

gib=$((1024 * 1024 * 1024))
expect_profile() {
  local cap="$1" want="$2" got
  got="$(paseo_resource_profile "$cap")"
  [ "$got" = "$want" ] || { printf 'FAIL cap=%s: got %s; want %s\n' "$cap" "$got" "$want" >&2; exit 1; }
}
expect_refusal() {
  if paseo_resource_profile "$1" >/dev/null; then
    printf 'FAIL cap=%s: expected refusal\n' "$1" >&2
    exit 1
  fi
}

expect_refusal "$((7 * gib - 1))"
expect_profile "$((7 * gib))" '6.5G 6G 24576'
expect_profile "$((8 * gib))" '6.5G 6G 24576'
expect_profile "$((16 * gib - 1))" '6.5G 6G 24576'
expect_profile "$((16 * gib))" '14G 12G 24576'
expect_profile "$((16 * gib + 1))" '14G 12G 24576'
got="$(paseo_resource_profile "$((16 * gib))" 30000)"
[ "$got" = '14G 12G 30000' ] || { printf 'FAIL custom TasksMax: got %s\n' "$got" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/a/b"
printf 'max\n' >"$tmp/memory.max"
printf '%s\n' "$((16 * gib))" >"$tmp/a/memory.max"
printf '%s\n' "$((8 * gib))" >"$tmp/a/b/memory.max"
printf '0::/a/b\n' >"$tmp/cgroup"
cap="$(paseo_effective_memory_cap_bytes "$tmp" "$tmp/cgroup")"
[ "$cap" = "$((8 * gib))" ] || { printf 'FAIL nested cap: got %s\n' "$cap" >&2; exit 1; }

printf 'ok paseo resource profiles\n'
