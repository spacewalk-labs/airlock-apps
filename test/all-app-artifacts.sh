#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

parity=false
fixture_contract=false
data_roundtrip=false
rpo_zero=false
selected=()

usage() {
  echo "usage: $0 [--parity] [--fixture-contract] [--data-roundtrip --rpo-zero] [--app APP ...]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --parity) parity=true; shift ;;
    --fixture-contract) fixture_contract=true; shift ;;
    --data-roundtrip) data_roundtrip=true; shift ;;
    --rpo-zero) rpo_zero=true; shift ;;
    --app)
      [[ $# -ge 2 ]] || usage
      selected+=("$2")
      shift 2
      ;;
    *) usage ;;
  esac
done

[[ "$fixture_contract" == false || "$parity" == true ]] || usage
[[ "$rpo_zero" == false || "$data_roundtrip" == true ]] || usage

if [[ ${#selected[@]} -eq 0 ]]; then
  selected=("${PUBLIC_APPS[@]}")
fi

declare -A known=()
for app in "${PUBLIC_APPS[@]}"; do known["$app"]=1; done
for app in "${selected[@]}"; do
  [[ -n "${known[$app]:-}" ]] || { echo "FAIL unknown app: $app" >&2; exit 2; }
done

for app in "${selected[@]}"; do
  for path in \
    "$ROOT/apps/$app/airlock-app.toml" \
    "$ROOT/apps/$app/install.sh" \
    "$ROOT/apps/$app/smoke.sh" \
    "$ROOT/apps/$app/deactivate.sh" \
    "$ROOT/abi/apps/$app.toml"; do
    [[ -f "$path" ]] || { echo "FAIL missing artifact: ${path#"$ROOT/"}" >&2; exit 1; }
  done
  for script in install.sh smoke.sh deactivate.sh; do
    [[ -x "$ROOT/apps/$app/$script" ]] \
      || { echo "FAIL non-executable artifact: apps/$app/$script" >&2; exit 1; }
    bash -n "$ROOT/apps/$app/$script"
  done
  echo "ok   artifacts $app"
done

python3 "$HERE/validate-app-artifacts.py" "$ROOT"
python3 "$HERE/validate_lifecycle.py" "$ROOT" "$ROOT/apps"

release_tmp="$(mktemp -d)"
trap 'rm -rf "$release_tmp"' EXIT
release_repo="$release_tmp/repo"
mkdir -p "$release_repo/apps"
cp -a "$ROOT/apps/." "$release_repo/apps/"
git -C "$release_repo" init -q -b fixture
git -C "$release_repo" config user.name parity-fixture
git -C "$release_repo" config user.email parity-fixture@example.test
git -C "$release_repo" add apps
git -C "$release_repo" -c core.hooksPath=/dev/null commit -q -m fixture
release_sha="$(git -C "$release_repo" rev-parse HEAD)"
for app in "${selected[@]}"; do
  release="$release_tmp/release-$app"
  python3 "$ROOT/builder/build-release.py" \
    --repo "$release_repo" --source-path "apps/$app" --id "$app" \
    --source-sha "$release_sha" --out "$release" \
    --write-lock "$release_tmp/$app.lock.json" >/dev/null
  for path in airlock-app.toml install.sh smoke.sh deactivate.sh; do
    [[ -f "$release/$path" ]] \
      || { echo "FAIL release missing $app/$path" >&2; exit 1; }
  done
  for script in install.sh smoke.sh deactivate.sh; do
    [[ -x "$release/$script" ]] \
      || { echo "FAIL release non-executable $app/$script" >&2; exit 1; }
  done
  echo "ok   release $app"
done

if [[ "$parity" == true ]]; then
  python3 "$HERE/parity-dispositions.py"
  if [[ "$fixture_contract" == true ]]; then
    python3 "$HERE/parity-fixture-contract.py"
  else
    for app in "${selected[@]}"; do
      test_script="$ROOT/apps/$app/tests/parity.sh"
      [[ -x "$test_script" ]] \
        || { echo "FAIL missing parity regression: apps/$app/tests/parity.sh" >&2; exit 1; }
      "$test_script"
    done
  fi
fi

if [[ "$data_roundtrip" == true ]]; then
  for app in "${selected[@]}"; do
    test_script="$ROOT/apps/$app/tests/lifecycle.sh"
    [[ -x "$test_script" ]] \
      || { echo "FAIL missing lifecycle regression: apps/$app/tests/lifecycle.sh" >&2; exit 1; }
    args=(--data-roundtrip)
    [[ "$rpo_zero" == true ]] && args+=(--rpo-zero)
    "$test_script" "${args[@]}"
  done
fi

echo "ok: ${#selected[@]} app artifacts; parity=$parity fixture_contract=$fixture_contract data_roundtrip=$data_roundtrip rpo_zero=$rpo_zero"
