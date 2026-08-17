#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$APP/../.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/deactivate.sh" "$APP/smoke.sh"

rendered="$(bash -c 'source "$1/render.sh"; render_notepad_nginx' _ "$APP")"
grep -Fq 'location = /notepad.html' <<<"$rendered"
grep -Fq 'return 308 /notepad/;' <<<"$rendered"
# shellcheck source=/dev/null
. "$APP/render.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/core/install"
cat > "$tmp/core/install/lib.sh" <<'SH'
log() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }
airlock_config() { [ "$1" = apps ] && printf 'publish\n'; }
airlock_load() { AIRLOCK_OWNER=owner@example.test; }
SH

dry_confd="$tmp/dry-confd"
dry_webroot="$tmp/dry-webroot"
AIRLOCK_ROOT="$tmp/core" AIRLOCK_APP_DIR="$APP" AIRLOCK_DRY_RUN=1 \
  AIRLOCK_CONFD="$dry_confd" AIRLOCK_WEBROOT="$dry_webroot" \
  bash "$APP/install.sh" > "$tmp/dry.log"
[[ ! -e "$dry_confd" && ! -e "$dry_webroot" ]]
grep -Fq '[dry] write notepad compatibility redirect' "$tmp/dry.log"

render_root="$tmp/render"
AIRLOCK_ROOT="$tmp/core" AIRLOCK_APP_DIR="$APP" AIRLOCK_DRY_RUN=1 \
  AIRLOCK_RENDER_DIR="$render_root" AIRLOCK_WEBROOT="$tmp/render-webroot" \
  bash "$APP/install.sh" > "$tmp/render.log"
cmp -s <(render_notepad_nginx) "$render_root/confd/hub-locations.d/notepad.conf"
[[ ! -e "$tmp/render-webroot" ]]

UI="$APP/frontend/notepad.html" node <<'JS'
const fs = require('fs');
const ui = fs.readFileSync(process.env.UI, 'utf8');
const start = ui.indexOf('  function expandAttachmentTokens');
const end = ui.indexOf("  document.getElementById('copyBtn')", start);
if (start < 0 || end < 0) throw new Error('token expander missing');
const imgMap = new Map([['1', '~/uploads/image001.jpg']]);
const fileMap = new Map([['2', '~/uploads/report.pdf']]);
eval(ui.slice(start, end));
const actual = expandAttachmentTokens('A [image1] B [file2] C [이미지1] D [파일2] E [image9]');
const expected = 'A ~/uploads/image001.jpg B ~/uploads/report.pdf C [이미지1](~/uploads/image001.jpg) D [파일2](~/uploads/report.pdf) E [image9]';
if (actual !== expected) throw new Error(`token expansion drift: ${actual}`);
JS

python3 - "$APP" "$ROOT" <<'PY'
import pathlib, sys, tomllib
app, root = map(pathlib.Path, sys.argv[1:])
ui = (app / 'frontend/notepad.html').read_text()
manifest = tomllib.loads((app / 'airlock-app.toml').read_text())
assert manifest['dependencies']['apps'] == ['publish']
assert 'units' not in manifest['artifacts']
assert manifest['artifacts']['fragments'] == ['hub-locations.d/notepad.conf']
for marker in ('MAX_SIDE = 2400', 'QUALITY = 0.9', 'MAX_ENCODED = 12 * 1024 * 1024',
               "body: JSON.stringify({ image: b64 })", "data: stripPrefix(dataUrl)",
               "fileSeq = 0", "localStorage.setItem(STORE_KEY, editor.value)"):
    assert marker in ui, marker
assert not (app / 'airlock-app.toml').read_text().find('units =') >= 0
assert 'notepad/index.html' in manifest['artifacts']['webroot']
deactivate = (app / 'deactivate.sh').read_text()
assert 'ledger' in deactivate and 'compatibility nginx' in deactivate
assert 'rm -' not in deactivate
print('ok: notepad parity contracts')
PY

echo 'ok: notepad parity (9/9 matrix IDs)'
