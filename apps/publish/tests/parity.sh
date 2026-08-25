#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/deactivate.sh" "$APP/smoke.sh"
python3 -m py_compile "$APP/backend/airlock-publish.py" "$APP/test-local-target.py"

rendered="$(bash -c 'source "$1/render.sh"; render_publish_nginx_main 18803 /opt/airlock/share' _ "$APP")"
grep -Fq 'location = /publish-manager.html {' <<<"$rendered"
grep -Fq 'return 302 /publish/;' <<<"$rendered"
if grep -Fq ':8000' <<<"$rendered"; then
  echo 'FAIL: Publish compatibility alias must not recreate the legacy :8000 listener' >&2
  exit 1
fi

APP="$APP" python3 - <<'PY'
import pathlib
import os

app = pathlib.Path(os.environ['APP'])
backend = (app / 'backend' / 'airlock-publish.py').read_text()
frontend = (app / 'frontend' / 'publish.html').read_text()
manifest = (app / 'airlock-app.toml').read_text()

for marker in (
    "'supported_versions': ['0', '1']",
    "'X-Docpub-Token' if str(version) == '1' else 'X-Airlock-Publish-Token'",
    'MAX_BUNDLE_ATTACHMENTS = 100',
    'MAX_BUNDLE_MEMBER_BYTES = 64 * 1024 * 1024',
    'MAX_BUNDLE_TOTAL_BYTES = 160 * 1024 * 1024',
    "unicodedata.normalize(\n        'NFC'",
    "(?:image|이미지)",
):
    assert marker in backend, marker

for marker in (
    'airlock-publish-theme',
    'refreshWhenVisible(document.hidden, load)',
    'setInterval(function ()',
    'Attachments ',
    'Entry source:',
):
    assert marker in frontend, marker
assert 'fileview-theme' not in frontend
assert 'path = "/publish/"' in manifest
print('ok: Publish static parity contracts')
PY

python3 "$APP/test-local-target.py"
node "$APP/test-bundle-plan-state.mjs"

echo 'ok: Publish executable parity contracts'
