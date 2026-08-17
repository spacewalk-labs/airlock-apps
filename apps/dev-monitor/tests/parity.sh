#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$APP/../.." && pwd)"

python3 "$APP/backend/test_devmon.py" >/dev/null 2>&1

APP="$APP" python3 - <<'PY'
import importlib.util
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import types
from unittest import mock

app = pathlib.Path(os.environ['APP'])
backend_dir = app / 'backend'
import sys
sys.path.insert(0, str(backend_dir))

spec = importlib.util.spec_from_file_location('airlock_dev_monitor', backend_dir / 'airlock-dev-monitor.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
import devmon_messages
import devmon_owner
import devmon_spool

restart_keys = devmon_owner._RESTART_REQUIRED
saved_restart = {key: os.environ.get(key) for key in restart_keys}
try:
    for key in restart_keys:
        os.environ.pop(key, None)
    assert devmon_owner.load_restart_config() is None
    os.environ['DEV_MONITOR_RESTART_OWNER'] = 'owner@example.test'
    try:
        devmon_owner.load_restart_config()
        raise AssertionError('partial restart gate was accepted')
    except devmon_owner.ConfigError:
        pass
    os.environ.update({'DEV_MONITOR_RESTART_PROXY_SECRET': 'secret',
                       'DEV_MONITOR_RESTART_ALLOW': 'airlock-publish'})
    assert devmon_owner.load_restart_config()['allowed'] == frozenset({'airlock-publish'})
finally:
    for key in restart_keys:
        if saved_restart[key] is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved_restart[key]

# DM-R2/DM-U2: the allow-list is necessary but not sufficient; the unit must also
# be a currently discovered airlock user unit. System/non-allow-listed names never run.
backend.RESTART_CONFIG = {'owner': 'owner@example.test', 'secret': 'secret',
                          'allowed': frozenset({'airlock-publish'})}
with mock.patch.object(backend, '_airlock_user_units', return_value=['airlock-publish']), \
        mock.patch.object(backend.subprocess, 'check_call') as call:
    assert backend.restart_svc('airlock-publish')[0]
    call.assert_called_once_with(['systemctl', '--user', 'restart', 'airlock-publish'], timeout=10,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert not backend.restart_svc('airlock-dev-monitor')[0]
    assert not backend.restart_svc('nginx')[0]
    assert call.call_count == 1

# The HTTP mutation route authenticates and checks CSRF before reading the body.
def fake_handler(headers):
    handler = object.__new__(backend.Handler)
    handler.path = '/monitor/api/service/restart'
    handler.headers = headers
    handler.responses = []
    handler._json = lambda status, payload: handler.responses.append((status, payload))
    handler._read_body = mock.Mock(return_value={'name': 'airlock-publish'})
    return handler

common = {'Origin': 'https://box.example.test', 'Host': 'box.example.test',
          'Content-Type': 'application/json', 'Content-Length': '26'}
unauthenticated = fake_handler(common)
with mock.patch.object(backend, 'restart_svc') as restart:
    backend.Handler.do_POST(unauthenticated)
    assert unauthenticated.responses[-1][0] == 403
    unauthenticated._read_body.assert_not_called()
    restart.assert_not_called()
authenticated = fake_handler(dict(common, **{'X-Devmon-Owner': 'owner@example.test',
                                              'X-Devmon-Proxy-Secret': 'secret'}))
with mock.patch.object(backend, 'restart_svc', return_value=(True, 'restarted')) as restart:
    backend.Handler.do_POST(authenticated)
    authenticated._read_body.assert_called_once()
    restart.assert_called_once_with('airlock-publish')
    assert authenticated.responses[-1][0] == 200

# DM-C2: an unset membership list preserves syntax validation; a configured list
# accepts only a named skill.
with tempfile.TemporaryDirectory() as cwd:
    row = {'kind': 'action', 'dismissed_at': None,
           'action_json': json.dumps({'cwd': cwd, 'skill': 'deploy'})}
    base = {'cwd_root': None}
    assert devmon_messages.canonical_plan(row, dict(base, skill_allow=None)) is not None
    assert devmon_messages.canonical_plan(row, dict(base, skill_allow={'deploy'})) is not None
    assert devmon_messages.canonical_plan(row, dict(base, skill_allow={'review'})) is None

# DM-S5: import is copy-only, does not follow a source symlink, and never replaces
# canonical state. Legacy sources remain byte-identical after both passes.
with tempfile.TemporaryDirectory() as tmp:
    legacy = pathlib.Path(tmp) / 'legacy'
    canonical = pathlib.Path(tmp) / 'canonical'
    (legacy / 'spool' / 'new').mkdir(parents=True)
    (legacy / 'spool' / 'new' / 'one.json').write_bytes(b'one')
    (legacy / 'spool' / 'new' / 'link.json').symlink_to(legacy / 'messages.db')
    os.mkfifo(legacy / 'spool' / 'new' / 'transient.fifo')
    external_queue = pathlib.Path(tmp) / 'external-queue'
    external_queue.mkdir()
    (external_queue / 'outside.json').write_bytes(b'outside')
    (legacy / 'spool' / 'processing').symlink_to(external_queue)
    source_db = sqlite3.connect(legacy / 'messages.db')
    source_db.execute('PRAGMA journal_mode=WAL')
    source_db.execute('CREATE TABLE events(value TEXT)')
    source_db.execute('INSERT INTO events VALUES (?)', ('in-wal',))
    source_db.commit()
    migrate = app / 'migrate-legacy-state.py'
    subprocess.run([sys.executable, str(migrate), str(legacy), str(canonical)], check=True,
                   stdout=subprocess.DEVNULL)
    with sqlite3.connect(canonical / 'messages.db') as copied_db:
        assert copied_db.execute('SELECT value FROM events').fetchall() == [('in-wal',)]
    assert (canonical / 'spool' / 'new' / 'one.json').read_bytes() == b'one'
    assert not (canonical / 'spool' / 'new' / 'link.json').exists()
    assert not (canonical / 'spool' / 'new' / 'transient.fifo').exists()
    assert not (canonical / 'spool' / 'new' / 'outside.json').exists()
    with sqlite3.connect(canonical / 'messages.db') as copied_db:
        copied_db.execute('INSERT INTO events VALUES (?)', ('canonical',))
    subprocess.run([sys.executable, str(migrate), str(legacy), str(canonical)], check=True,
                   stdout=subprocess.DEVNULL)
    with sqlite3.connect(canonical / 'messages.db') as copied_db:
        assert copied_db.execute('SELECT value FROM events ORDER BY rowid').fetchall() == [
            ('in-wal',), ('canonical',)]
    assert source_db.execute('SELECT value FROM events').fetchall() == [('in-wal',)]
    source_db.close()
    assert (legacy / 'spool' / 'new' / 'one.json').read_bytes() == b'one'
    # The migrator itself enforces the ABI's operator-only canonical boundary.
    for directory in (canonical, canonical / 'spool', canonical / 'spool' / 'new'):
        os.chmod(directory, 0o755)
    subprocess.run([sys.executable, str(migrate), str(legacy), str(canonical)], check=True,
                   stdout=subprocess.DEVNULL)
    for directory in (canonical, canonical / 'spool', canonical / 'spool' / 'new'):
        assert (directory.stat().st_mode & 0o777) == 0o700
    escaped = pathlib.Path(tmp) / 'escaped'
    escaped.mkdir()
    unsafe = pathlib.Path(tmp) / 'unsafe-canonical'
    unsafe.mkdir()
    (unsafe / 'spool').symlink_to(escaped)
    failed = subprocess.run([sys.executable, str(migrate), str(legacy), str(unsafe)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert failed.returncode != 0
    assert list(escaped.iterdir()) == []
    unsafe_db = pathlib.Path(tmp) / 'unsafe-db-canonical'
    unsafe_db.mkdir()
    escaped_db = escaped / 'messages.db'
    (unsafe_db / 'messages.db').symlink_to(escaped_db)
    failed = subprocess.run([sys.executable, str(migrate), str(legacy), str(unsafe_db)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert failed.returncode != 0
    assert not escaped_db.exists()

# DM-N3: positive control starts with an over-broad spool and protected child;
# runtime initialization must restore the operator boundary and protected lanes.
with tempfile.TemporaryDirectory() as tmp:
    spool = pathlib.Path(tmp) / 'spool'
    (spool / 'processing').mkdir(parents=True)
    (spool / 'bad').mkdir()
    os.chmod(spool, 0o755)
    os.chmod(spool / 'processing', 0o755)
    os.chmod(spool / 'bad', 0o755)
    devmon_spool.ensure_dirs(str(spool))
    assert (spool.stat().st_mode & 0o777) == 0o700
    assert ((spool / 'processing').stat().st_mode & 0o777) == 0o700
    assert ((spool / 'bad').stat().st_mode & 0o777) == 0o700

# The UI retains dynamic log discovery and fixes bulk selection to filtered/visible cards.
ui = (app / 'frontend' / 'dev-monitor.html').read_text()
for marker in ('populateLogUnits', "services.filter(function (s) { return s.scope === 'user'; })",
               'data-restart', 'selectedVisible', 'filteredMessages()',
               "succeeded.length + ' succeeded, ' + failed.length + ' failed'", 'showUndo',
               'function runPool', 'var msgSeq = 0'):
    assert marker in ui, marker
assert "error.authDenied = true;" in ui
selector = ui[ui.index('  function populateLogUnits'):ui.index('  function loadServices')]
assert hashlib.sha256(selector.encode()).hexdigest() == '7a3e3ac741ffc64006a20f23b824210bcd15686ba0d11a5f5b1b38c0221d9892'

# DM-N3 positive invariant: the package still declares no capabilities and keeps the
# operator-owned 0700 spool. No root firewall unit is introduced.
manifest = (app / 'airlock-app.toml').read_text()
abi = (app.parent.parent / 'abi' / 'apps' / 'dev-monitor.toml').read_text()
install = (app / 'install.sh').read_text()
assert 'capabilities = []' in abi
assert 'install -d -m 700 "$DEVMON_STATE"' in install
assert 'devmon-spool-fw' not in manifest + install
restart_call = 'restart_location="$(render_dev_monitor_restart_location "$BACKEND_PORT" "$hdr_var" "$RESTART_SECRET")"'
assert restart_call in install
assert 'render_dev_monitor_restart_location "$BACKEND_PORT" "$hdr_var" "$DEVMON_SECRET"' not in install

print('ok: dev-monitor parity contracts')
PY

# A 403 may leave the requests already inside the concurrency window in flight, but it
# must not schedule the remaining cards or reload/reveal stale console state.
UI="$APP/frontend/dev-monitor.html" node <<'JS'
const fs = require('fs');
const ui = fs.readFileSync(process.env.UI, 'utf8');
const body = ui.slice(ui.indexOf('  function runPool'), ui.indexOf('  function dismissMessageCard'));
if (!body.includes('function runPool') || !body.includes('function bulkAction')) throw new Error('bulk functions missing');
const targets = Array.from({length: 10}, (_, i) => ({card_id: String(i)}));
let calls = 0, disabled = 0, loads = 0;
var msgState = {bulkBusy: false, selected: Object.fromEntries(targets.map(x => [x.card_id, true]))};
var window = {confirm: () => true};
function selectedVisible() { return targets; }
function bulkStatus() {}
function renderBulkBar() {}
function showUndo() {}
function loadMessages() { loads++; return Promise.resolve(); }
function disableMessages() {
  disabled++;
  msgState.selected = {};
  msgState.bulkBusy = false;
}
function cardAction() {
  calls++;
  if (calls === 1) {
    disableMessages();
    const error = new Error('denied');
    error.authDenied = true;
    return Promise.reject(error);
  }
  return new Promise(resolve => setTimeout(() => resolve({ok: true}), 10));
}
eval(body);
bulkAction('dismiss');
setTimeout(() => {
  if (calls !== 4) throw new Error(`403 scheduled ${calls} requests; expected concurrency window 4`);
  if (disabled !== 1) throw new Error(`403 disabled console ${disabled} times; expected 1`);
  if (loads !== 0) throw new Error(`403 reloaded stale console ${loads} times`);
  if (msgState.bulkBusy || Object.keys(msgState.selected).length) throw new Error('403 left stale bulk state');
}, 40);
JS

rendered="$(ROOT="$ROOT" bash -c 'source "$1/render.sh"; render_dev_monitor_restart_location 18804 tailscale_user_login test-secret' _ "$APP")"
grep -Fq 'location = /monitor/api/service/restart' <<<"$rendered"
grep -Fq 'proxy_set_header X-Devmon-Owner $http_tailscale_user_login;' <<<"$rendered"
grep -Fq 'proxy_set_header X-Devmon-Proxy-Secret "test-secret";' <<<"$rendered"

echo "ok: dev-monitor parity"
