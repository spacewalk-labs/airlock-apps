#!/usr/bin/env python3
"""Tests for the publish app's LOCAL public target (and remote non-regression).

Runs the backend module in-process against temp directories — no install, no
network, no nginx. Every check here exists because the design review named a
concrete way this could go wrong; see docs/design/publish-local-target.md §9.

    python3 apps/publish/test-local-target.py

Exit 0 = all pass. Any failure prints the check name and exits 1.
"""
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, 'backend', 'airlock-publish.py')

_fails = []
_passes = 0


def check(name, cond, detail=''):
    global _passes
    if cond:
        _passes += 1
        print(f'  ok   {name}')
    else:
        _fails.append(f'{name}{" — " + detail if detail else ""}')
        print(f'  FAIL {name}{" — " + detail if detail else ""}')


def load(env):
    """(Re)import the backend with a given environment. Module-level config is
    read at import time, which is exactly what we want to exercise."""
    for k in list(os.environ):
        if k.startswith('AIRLOCK_'):
            del os.environ[k]
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location('airlock_publish', BACKEND)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_dirs(tmp, **extra):
    share = os.path.join(tmp, 'share')
    pub = os.path.join(tmp, 'share-public')
    state = os.path.join(tmp, 'state')
    os.makedirs(share, exist_ok=True)
    env = {'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_PUBLIC_DIR': pub,
           'AIRLOCK_PUBLISH_STATE_DIR': state, 'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local',
           'AIRLOCK_PUBLISH_BASE_URL': 'https://doc.example.com',
           'AIRLOCK_PUBLISH_UPLOADS_DIR': os.path.join(tmp, 'uploads')}
    env.update(extra)
    return share, pub, state, env


def page(share, name, body='<h1>hi</h1>'):
    p = os.path.join(share, name)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(f'<html><head><title>{name}</title></head><body>{body}</body></html>')
    return p


OWNER = 'me@example.com'


# ---------------------------------------------------------------- 1, 9, 11
def t_happy_path(tmp):
    print('\n[1] publish -> list -> set-expiry -> revoke  (+ perms, + real expiry)')
    share, pub, _state, env = make_dirs(tmp)
    m = load(env)
    check('local mode enabled', m.PUBLIC_ENABLED and m.PUBLIC_MODE == 'local', m.PUBLIC_DISABLED_REASON)
    page(share, 'my-doc.html')

    ok, res = m.publish_public('my-doc.html', 720, OWNER)
    check('publish ok', ok, str(res))
    slug = res['slug']
    idx = os.path.join(pub, slug, 'index.html')
    check('snapshot written', os.path.isfile(idx))
    check('url is base_url/<slug>/', res['url'] == f'https://doc.example.com/{slug}/', res['url'])
    check('ttl honoured (720h)', res['ttl_hours'] == 720, str(res['ttl_hours']))

    # [9] permissions — nginx (another user) must be able to traverse and read
    check('slug dir 0755', oct(os.stat(os.path.dirname(idx)).st_mode)[-3:] == '755')
    check('index.html 0644', oct(os.stat(idx).st_mode)[-3:] == '644')
    check('no temp file left behind', not any(n.startswith('.tmp-') for n in os.listdir(os.path.dirname(idx))))

    d = m.public_list(OWNER)
    check('list returns it', d['ok'] and [i['slug'] for i in d['items']] == [slug], json.dumps(d)[:200])
    check('list not expired', d['items'][0]['expired'] is False)

    # re-publish keeps the slug (the promise the whole feature rests on)
    ok2, res2 = m.publish_public('my-doc.html', 24, OWNER)
    check('re-publish keeps the slug', ok2 and res2['slug'] == slug, str(res2))

    r = m.public_set_expiry(slug, OWNER, 720)
    check('set-expiry ok', r.get('ok'), json.dumps(r))

    # [11] expiry actually removes content — backdate, then run the real timer
    st = json.load(open(os.path.join(_state, 'publish-public.json')))
    st['items'][slug]['expiry'] = int(time.time()) - 10
    json.dump(st, open(os.path.join(_state, 'publish-public.json'), 'w'))
    out = subprocess.run([sys.executable, BACKEND, '--cleanup'], env={**os.environ},
                         capture_output=True, text=True)
    check('--cleanup reports the expired snapshot', 'expired public snapshot' in out.stdout, out.stdout + out.stderr)
    check('expired page is GONE from disk', not os.path.exists(os.path.join(pub, slug)))
    check('expired entry dropped from state', slug not in json.load(
        open(os.path.join(_state, 'publish-public.json')))['items'])

    # revoke removes immediately
    ok3, res3 = m.publish_public('my-doc.html', 24, OWNER)
    slug3 = res3['slug']
    m.public_revoke(slug3, OWNER)
    check('revoke removes the directory', not os.path.exists(os.path.join(pub, slug3)))


# ---------------------------------------------------------------------- 2
def t_slug_abuse(tmp):
    print('\n[2] slug abuse cannot escape or delete outside public_dir')
    share, pub, _s, env = make_dirs(tmp)
    m = load(env)
    os.makedirs(pub, exist_ok=True)
    for bad in ('../x', '.', '..', 'a/b', 'x' * 200, '', '-lead', 'UPPER', 'ok/../../etc'):
        check(f'_slug_dir refuses {bad!r}', m._slug_dir(bad) is None)
    # a symlinked slug dir must not be followed when deleting
    victim = os.path.join(tmp, 'victim')
    os.makedirs(victim, exist_ok=True)
    open(os.path.join(victim, 'keep.txt'), 'w').close()
    os.symlink(victim, os.path.join(pub, 'evil-aaa111'))
    check('_slug_dir refuses a symlinked slug dir', m._slug_dir('evil-aaa111') is None)
    check('_remove_slug_dir refuses it', m._remove_slug_dir('evil-aaa111') is False)
    check('victim untouched', os.path.isfile(os.path.join(victim, 'keep.txt')))
    os.unlink(os.path.join(pub, 'evil-aaa111'))


# ---------------------------------------------------------------------- 3
def t_symlinked_source(tmp):
    print('\n[3] a symlinked source still publishes (the documented workflow)')
    share, pub, _s, env = make_dirs(tmp)
    m = load(env)
    real = os.path.join(tmp, 'elsewhere')
    os.makedirs(real, exist_ok=True)
    src = os.path.join(real, 'repo-doc.html')
    with open(src, 'w') as fh:
        fh.write('<html><title>repo doc</title><body>x</body></html>')
    os.symlink(src, os.path.join(share, 'repo-doc.html'))
    ok, res = m.publish_public('repo-doc.html', 24, OWNER)
    check('symlinked doc publishes', ok, str(res))
    check('content came from the link target', ok and 'repo doc' in
          open(os.path.join(pub, res['slug'], 'index.html')).read())


# ---------------------------------------------------------------------- 4
def t_empty_owner(tmp):
    print('\n[4] local mode refuses an empty owner on every operation')
    share, _p, _s, env = make_dirs(tmp)
    m = load(env)
    page(share, 'x.html')
    ok, err = m.publish_public('x.html', 24, '')
    check('publish refused', not ok and 'identity' in str(err), str(err))
    check('list refused', m.public_list('').get('ok') is False)
    check('revoke refused', m.public_revoke('some-slug', '').get('ok') is False)
    check('set-expiry refused', m.public_set_expiry('some-slug', '', 24).get('ok') is False)


# ---------------------------------------------------------------------- 5
def t_owner_collision(tmp):
    print("\n[5] ingest never overwrites another owner's slug")
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'shared.html', '<b>owner A</b>')
    ok, a = m.publish_public('shared.html', 24, 'a@example.com')
    check('A published', ok)
    # force B onto A's slug — the same code path a slug collision would take
    res = m._local_ingest(a['slug'], 'b@example.com', 'shared.html', 't', 24, b'<b>owner B</b>')
    check('B got a DIFFERENT slug', res['ok'] and res['result']['slug'] != a['slug'], json.dumps(res)[:200])
    check("A's page untouched", 'owner A' in open(os.path.join(pub, a['slug'], 'index.html')).read())
    check('B cannot list A', [i['slug'] for i in m.public_list('b@example.com')['items']] != [a['slug']])
    check('B cannot revoke A', m.public_revoke(a['slug'], 'b@example.com').get('ok') is False)
    check("A's page still there after B's revoke attempt", os.path.exists(os.path.join(pub, a['slug'])))


# ---------------------------------------------------------------------- 6
def t_crash_between(tmp):
    print('\n[6] crash between state-write and content-write leaves nothing public')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'y.html')
    ok, res = m.publish_public('y.html', 24, OWNER)
    slug = res['slug']
    shutil.rmtree(os.path.join(pub, slug))          # content lost, state intact
    d = m.public_list(OWNER)
    check('entry is reconciled away (no phantom link)', slug not in [i['slug'] for i in d['items']])
    check('nothing public remains', not os.path.exists(os.path.join(pub, slug)))


# ---------------------------------------------------------------------- 7
def t_concurrent(tmp):
    print('\n[7] concurrent publishers + sweeps do not lose state updates')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    names = [f'c{i}.html' for i in range(12)]
    for n in names:
        page(share, n)

    errors = []

    def pub_one(n):
        try:
            ok, res = m.publish_public(n, 24, OWNER)
            if not ok:
                errors.append(f'{n}: {res}')
        except Exception as e:                      # noqa: BLE001 - test reporting
            errors.append(f'{n}: {e}')

    sweeper = threading.Thread(target=lambda: [m._local_sweep_only() for _ in range(20)])
    sweeper.start()
    ths = [threading.Thread(target=pub_one, args=(n,)) for n in names]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    sweeper.join()
    check('no publish errors', not errors, '; '.join(errors[:3]))
    st = json.load(open(os.path.join(state, 'publish-public.json')))
    check('every publish survived in state', len(st['items']) == len(names),
          f"{len(st['items'])}/{len(names)}")
    check('every page survived on disk',
          sum(os.path.isfile(os.path.join(pub, s, 'index.html')) for s in st['items']) == len(names))

    # cross-process: the timer runs as a separate PID and must take the same lock
    out = subprocess.run([sys.executable, BACKEND, '--cleanup'], env={**os.environ},
                         capture_output=True, text=True)
    st2 = json.load(open(os.path.join(state, 'publish-public.json')))
    check('cross-process sweep kept unexpired items', len(st2['items']) == len(names),
          out.stdout + out.stderr)


# ---------------------------------------------------------------------- 8
def t_corrupt_state(tmp):
    print('\n[8] corrupt state: moved aside, orphans adopted and swept (never orphaned forever)')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'z.html')
    ok, res = m.publish_public('z.html', 24, OWNER)
    slug = res['slug']
    with open(os.path.join(state, 'publish-public.json'), 'w') as fh:
        fh.write('{"items": {trunca')
    d = m.public_list(OWNER)
    check('backend survives corrupt state', d.get('ok') is True, json.dumps(d)[:200])
    check('corrupt file moved aside, not deleted',
          any(n.startswith('publish-public.json.corrupt-') for n in os.listdir(state)))
    st = json.load(open(os.path.join(state, 'publish-public.json')))
    check('orphaned public dir ADOPTED (so it can be swept)', slug in st['items'])
    check('adopted entry has no owner => listed to nobody', st['items'][slug]['owner'] is None)
    check('adopted entry is not visible to the original owner',
          slug not in [i['slug'] for i in d['items']])
    st['items'][slug]['expiry'] = int(time.time()) - 1
    json.dump(st, open(os.path.join(state, 'publish-public.json'), 'w'))
    m._local_sweep_only()
    check('adopted orphan is swept', not os.path.exists(os.path.join(pub, slug)))


# --------------------------------------------------------------------- 10
def t_overlap_refused(tmp):
    print('\n[10] public_dir overlapping share_dir is refused (the §6.2 leak)')
    share, _p, _s, env = make_dirs(tmp)
    for label, pd in (('same dir', share), ('inside share', os.path.join(share, 'pub')),
                      ('parent of share', os.path.dirname(share))):
        m = load({**env, 'AIRLOCK_PUBLISH_PUBLIC_DIR': pd})
        check(f'refused: {label}', not m.PUBLIC_ENABLED and 'overlap' in m.PUBLIC_DISABLED_REASON,
              m.PUBLIC_DISABLED_REASON)


# --------------------------------------------------------------------- 12
def t_config_shapes(tmp):
    print('\n[12] every config shape resolves the way it does today')
    share, pub, state, env = make_dirs(tmp)
    base = {'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_STATE_DIR': state}
    cases = [
        ('nothing configured', {}, False, 'remote', False),
        ('base_url only (half-configured remote)',
         {'AIRLOCK_PUBLISH_BASE_URL': 'https://x'}, False, 'remote', True),
        ('ingest_url only (token missing)',
         {'AIRLOCK_PUBLISH_INGEST_URL': 'https://i'}, False, 'remote', True),
        ('full remote', {'AIRLOCK_PUBLISH_INGEST_URL': 'https://i',
                         'AIRLOCK_PUBLISH_BASE_URL': 'https://x',
                         'AIRLOCK_PUBLISH_TOKEN': 't'}, True, 'remote', False),
        ('local, complete', {'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local',
                             'AIRLOCK_PUBLISH_BASE_URL': 'https://x',
                             'AIRLOCK_PUBLISH_PUBLIC_DIR': pub}, True, 'local', False),
        ('local, base_url missing', {'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local',
                                     'AIRLOCK_PUBLISH_PUBLIC_DIR': pub}, False, 'local', True),
        ('local, public_dir missing', {'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local',
                                       'AIRLOCK_PUBLISH_BASE_URL': 'https://x'}, False, 'local', True),
    ]
    for label, extra, want_enabled, want_mode, want_reason in cases:
        m = load({**base, **extra})
        check(f'{label}: enabled={want_enabled}', m.PUBLIC_ENABLED is want_enabled,
              f'got {m.PUBLIC_ENABLED} ({m.PUBLIC_DISABLED_REASON})')
        check(f'{label}: mode={want_mode}', m.PUBLIC_MODE == want_mode, m.PUBLIC_MODE)
        check(f'{label}: {"warns" if want_reason else "silent"}',
              bool(m.PUBLIC_DISABLED_REASON) is want_reason, repr(m.PUBLIC_DISABLED_REASON))


# ----------------------------------------------------------------- 13, 14
class _StubIngest(http.server.BaseHTTPRequestHandler):
    seen = []

    def _reply(self, payload):
        b = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(n) or b'{}')
        _StubIngest.seen.append((self.path, self.headers.get('X-Airlock-Publish-Token'), body))
        self._reply({'ok': True, 'result': {'expiry': 1790000000, 'ttl_hours': body.get('ttl_hours')}})

    def do_GET(self):
        _StubIngest.seen.append((self.path, self.headers.get('X-Airlock-Publish-Token'), None))
        self._reply({'ok': True, 'items': []})

    def log_message(self, *_a):
        pass


def t_remote_regression(tmp):
    print('\n[13,14] remote mode unchanged (protocol, token header, no size cap)')
    share, _p, state, _env = make_dirs(tmp)
    srv = http.server.HTTPServer(('127.0.0.1', 0), _StubIngest)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    m = load({'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_STATE_DIR': state,
              'AIRLOCK_PUBLISH_INGEST_URL': f'http://127.0.0.1:{port}',
              'AIRLOCK_PUBLISH_BASE_URL': 'https://docs.example',
              'AIRLOCK_PUBLISH_TOKEN': 'sekret'})
    check('remote enabled', m.PUBLIC_ENABLED and m.PUBLIC_MODE == 'remote')
    page(share, 'r.html')
    ok, res = m.publish_public('r.html', 336, OWNER)
    check('remote publish ok', ok, str(res))
    pathq, token, body = _StubIngest.seen[-1]
    check('POST /ingest', pathq == '/ingest', pathq)
    check('token header sent', token == 'sekret')
    check('payload keys unchanged',
          set(body) == {'slug', 'owner', 'src', 'title', 'ttl_hours', 'html_b64'}, str(sorted(body)))
    check('remote URL shape', res['url'].startswith('https://docs.example/'), res['url'])

    # [14] the 25MB cap is LOCAL-ONLY — a big snapshot must still go out remotely
    page(share, 'big.html', 'x' * (26 * 1024 * 1024))
    ok_big, res_big = m.publish_public('big.html', 24, OWNER)
    check('remote accepts a >25MB snapshot (no new cap)', ok_big, str(res_big)[:120])

    # empty owner is a REMOTE-mode behaviour we must not change
    ok_e, _ = m.publish_public('r.html', 24, '')
    check('remote still allows an empty owner (unchanged)', ok_e)

    m2 = load({'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_STATE_DIR': state,
               'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local', 'AIRLOCK_PUBLISH_BASE_URL': 'https://x',
               'AIRLOCK_PUBLISH_PUBLIC_DIR': os.path.join(tmp, 'pub2')})
    ok_l, err_l = m2.publish_public('big.html', 24, OWNER)
    check('local REFUSES a >25MB snapshot', not ok_l and 'too large' in str(err_l), str(err_l)[:120])
    srv.shutdown()


def main():
    for fn in (t_happy_path, t_slug_abuse, t_symlinked_source, t_empty_owner, t_owner_collision,
               t_crash_between, t_concurrent, t_corrupt_state, t_overlap_refused,
               t_config_shapes, t_remote_regression):
        tmp = tempfile.mkdtemp(prefix='airlock-pub-test-')
        try:
            fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{_passes} passed, {len(_fails)} failed')
    for f in _fails:
        print('  FAIL ' + f)
    return 1 if _fails else 0


if __name__ == '__main__':
    sys.exit(main())
