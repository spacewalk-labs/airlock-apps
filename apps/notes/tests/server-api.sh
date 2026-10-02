#!/usr/bin/env bash
# Run only against a disposable vault and the pinned release binary; never
# use a production server. The argument is an already verified binary path.
set -euo pipefail
if [ "$#" != 1 ]; then echo "usage: $0 <pinned-silverbullet-binary>" >&2; exit 2; fi
python3 - "$1" "$(dirname "$0")" <<'PY'
import os, pathlib, socket, subprocess, sys, tempfile, time, urllib.request, re
binary = pathlib.Path(sys.argv[1]).resolve()
version = subprocess.check_output([str(binary), 'version'], text=True).strip()
install = (pathlib.Path(sys.argv[2]) / '../install.sh').read_text()
pinned = re.search(r'^SB_VER="([^"]+)"', install, re.M).group(1)
assert version.startswith(pinned + '-'), version
with tempfile.TemporaryDirectory(prefix='folio-server-api-') as tmp:
    root = pathlib.Path(tmp)
    (root / 'Meeting.md').write_text('# Existing meeting\n')
    (root / 'Inbox.md').write_text('# Inbox\n- existing note\n')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith('SB_')}
    env.update(SB_URL_PREFIX='/notes/editor/main', SB_RUNTIME_API='0', SB_SHELL_BACKEND='off')
    with (root / 'server.log').open('w') as log:
        proc = subprocess.Popen([str(binary), '--single', '-L', '127.0.0.1', '-p', str(port), str(root)], env=env, stdout=log, stderr=log)
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urllib.request.urlopen(base + '/notes/editor/main/.fs', timeout=.2).read()
                    break
                except OSError:
                    time.sleep(.05)
            else: raise RuntimeError('temporary server did not become ready')
            subprocess.run(['node', str(pathlib.Path(sys.argv[2]) / 'server-api.test.mjs')], env={**os.environ, 'FOLIO_TEST_BASE_URL': base}, check=True)
        finally:
            proc.terminate(); proc.wait(timeout=5)
PY
