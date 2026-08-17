#!/usr/bin/env python3
"""Tests for the publish app's LOCAL public target (and remote non-regression).

Runs the backend module in-process against temp directories — no install, no
network, no nginx. Every check here exists because the design review named a
concrete way this could go wrong; see docs/design/publish-local-target.md §9.

    python3 apps/publish/test-local-target.py

Exit 0 = all pass. Any failure prints the check name and exits 1.
"""
import contextlib
import base64
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

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
    gated = os.path.join(tmp, 'share-gated')
    auth = os.path.join(tmp, 'publish-gated-auth')
    state = os.path.join(tmp, 'state')
    os.makedirs(share, exist_ok=True)
    fake_htpasswd = os.path.join(tmp, 'htpasswd')
    with open(fake_htpasswd, 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\nread password\nprintf "%s:fake-%s\\n" "$2" "$password"\n')
    os.chmod(fake_htpasswd, 0o755)
    env = {'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_PUBLIC_DIR': pub,
           'AIRLOCK_PUBLISH_GATED_DIR': gated,
           'AIRLOCK_PUBLISH_HTPASSWD_DIR': auth,
           'AIRLOCK_PUBLISH_STATE_DIR': state, 'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local',
           'AIRLOCK_PUBLISH_BASE_URL': 'https://doc.example.com',
           'AIRLOCK_PUBLISH_HTPASSWD_BIN': fake_htpasswd,
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
    # 'ok-slug\n' is here because Python's `$` also matches before a trailing newline. While
    # _RE_SLUG ended at `$` this slug was accepted, and _htpasswd_hash would then have written
    # a two-line credential record whose second line is a valid bcrypt hash under an empty
    # user name — the startswith(slug + ':') guard passes, because that is what htpasswd emits.
    for bad in ('../x', '.', '..', 'a/b', 'x' * 200, '', '-lead', 'UPPER', 'ok/../../etc',
                'ok-slug\n', 'a' * 64 + '\n'):
        check(f'_slug_dir refuses {bad!r}', m._slug_dir(bad) is None)
        check(f'_htpasswd_path refuses {bad!r}', m._htpasswd_path(bad) is None)
    # _RE_TRANSACTION is only ever used with fullmatch, and _RE_UPLOAD only filters names
    # that came from listdir — where a newline-terminated filename is perfectly possible but
    # nothing downstream distinguishes it. Either way a behavioural case would pass with or
    # without the anchor, so assert the pattern property directly and keep every anchored
    # pattern in this file covered by something that can actually fail.
    check('_RE_TRANSACTION is anchored at end-of-string',
          m._RE_TRANSACTION.match('doc-a1b2c3.old-deadbe\n') is None)
    check('_RE_UPLOAD is anchored at end-of-string',
          m._RE_UPLOAD.match('image001-20260801-120000.jpg\n') is None)

    # The worktree path parsers are behavioural, not a gate, so the anchor check cannot
    # speak for them: replacing `\Z` with nothing would still pass it. A symlink target may
    # legally end in a newline, and with `$` the capture silently dropped it — the repair
    # candidate then named a different file from the broken link that was measured.
    check('worktree target maps to the main repo',
          m._wt_to_main_candidates('/home/u/proj-wt/branch/docs/a.html')
          == ['/home/u/proj/docs/a.html'])
    check('worktree target maps from the /wt/ layout too',
          m._wt_to_main_candidates('/home/u/proj/wt/branch/docs/a.html')
          == ['/home/u/proj/docs/a.html'])
    # One newline case per pattern: the '-wt/' form is matched by the first regex and the
    # '/wt/' form by the second, so a single case leaves the other free to regress.
    check('a -wt/ target ending in a newline proposes nothing rather than a truncated path',
          m._wt_to_main_candidates('/home/u/proj-wt/branch/docs/a.html\n') == [])
    check('a /wt/ target ending in a newline proposes nothing rather than a truncated path',
          m._wt_to_main_candidates('/home/u/proj/wt/branch/docs/a.html\n') == [])
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
    print('\n[3] PB-A4 keeps external-symlink HTML publication compatibility')
    share, pub, _s, env = make_dirs(tmp)
    m = load(env)
    real = os.path.join(tmp, 'elsewhere')
    os.makedirs(real, exist_ok=True)
    src = os.path.join(real, 'repo-doc.html')
    with open(src, 'w') as fh:
        fh.write('<html><title>repo doc</title><body>x</body></html>')
    os.symlink(src, os.path.join(share, 'repo-doc.html'))
    ok, res = m.publish_public('repo-doc.html', 24, OWNER)
    check('PB-A4 selected external-symlink doc publishes', ok, str(res))
    check('content came from the link target', ok and 'repo doc' in
          open(os.path.join(pub, res['slug'], 'index.html')).read())


# ---------------------------------------------------------------------- 4
def t_empty_owner(tmp):
    print('\n[4] local mode refuses an empty owner on every operation')
    share, pub, _s, env = make_dirs(tmp)
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
    res = m._local_ingest(a['slug'], 'b@example.com', 'shared.html', 't', 24,
                          {'index.html': b'<b>owner B</b>'})
    check('B got a DIFFERENT slug', res['ok'] and res['result']['slug'] != a['slug'], json.dumps(res)[:200])
    check("A's page untouched", 'owner A' in open(os.path.join(pub, a['slug'], 'index.html')).read())
    check('B cannot list A', [i['slug'] for i in m.public_list('b@example.com')['items']] != [a['slug']])
    check('B cannot revoke A', m.public_revoke(a['slug'], 'b@example.com').get('ok') is False)
    check("A's page still there after B's revoke attempt", os.path.exists(os.path.join(pub, a['slug'])))


# ---------------------------------------------------------------------- 6
def t_crash_between(tmp):
    print('\n[6] crash during directory replacement restores the last live snapshot')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'y.html')
    ok, res = m.publish_public('y.html', 24, OWNER)
    slug = res['slug']
    live = os.path.join(pub, slug)
    backup = f'{live}.old-deadbeef'
    os.replace(live, backup)                        # simulate SIGTERM between the two renames
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        d = m.public_list(OWNER)
    check('reconcile restores the missing live directory', slug in [i['slug'] for i in d['items']] and
          os.path.isfile(os.path.join(live, 'index.html')), str(d))
    check('recovered snapshot has the old content', 'y.html' in open(os.path.join(live, 'index.html')).read())
    check('backup is removed after recovery', not os.path.exists(backup))
    check('recovery is logged', 'recovered' in stderr.getvalue(), stderr.getvalue())

    for kind in ('old', 'stage', 'failed'):
        stale = os.path.join(pub, f'{slug}.{kind}-cafebabe')
        os.mkdir(stale)
        open(os.path.join(stale, 'index.html'), 'w').close()
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        m.public_list(OWNER)
    check('live sibling makes old/stage/failed remnants garbage', not any(
        os.path.exists(os.path.join(pub, f'{slug}.{kind}-cafebabe'))
        for kind in ('old', 'stage', 'failed')))
    check('remnant deletion is logged', 'removed transaction' in stderr.getvalue(), stderr.getvalue())


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

    page(share, 'same.html', 'same source')
    start = threading.Barrier(2)
    same_results = []

    def publish_same():
        start.wait()
        same_results.append(m.publish_public('same.html', 24, OWNER))

    same_threads = [threading.Thread(target=publish_same) for _ in range(2)]
    for thread in same_threads:
        thread.start()
    for thread in same_threads:
        thread.join()
    same_slugs = [result['slug'] for ok, result in same_results if ok]
    check('concurrent same-source publishes reuse one slug', len(same_slugs) == 2 and
          len(set(same_slugs)) == 1, str(same_results))
    st3 = json.load(open(os.path.join(state, 'publish-public.json')))
    check('concurrent same-source publishes create one state item', sum(
        item.get('src') == 'same.html' for item in st3['items'].values()) == 1, str(st3))


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
    share, pub, _s, env = make_dirs(tmp)
    for label, pd in (('same dir', share), ('inside share', os.path.join(share, 'pub')),
                      ('parent of share', os.path.dirname(share))):
        m = load({**env, 'AIRLOCK_PUBLISH_PUBLIC_DIR': pd})
        check(f'refused: {label}', not m.PUBLIC_ENABLED and 'overlap' in m.PUBLIC_DISABLED_REASON,
              m.PUBLIC_DISABLED_REASON)
    m = load({**env, 'AIRLOCK_PUBLISH_GATED_DIR': pub})
    check('gated overlap disables only gated publishing', m.PUBLIC_ENABLED and not m.GATED_ENABLED and
          'overlaps' in m.GATED_DISABLED_REASON, m.GATED_DISABLED_REASON)


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
        _StubIngest.seen.append((self.path,
            self.headers.get('X-Airlock-Publish-Token'),
            self.headers.get('X-Docpub-Token'), body))
        self._reply({'ok': True, 'result': {'expiry': 1790000000, 'ttl_hours': body.get('ttl_hours')}})

    def do_GET(self):
        _StubIngest.seen.append((self.path,
            self.headers.get('X-Airlock-Publish-Token'),
            self.headers.get('X-Docpub-Token'), None))
        self._reply({'ok': True, 'items': []})

    def log_message(self, *_a):
        pass


def t_remote_regression(tmp):
    print('\n[remote] negotiated v0/v1 protocol, preflight, validation, and rollback')
    share, _p, state, _env = make_dirs(tmp)
    m = load({'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_STATE_DIR': state,
              'AIRLOCK_PUBLISH_INGEST_URL': 'https://ingest.example',
              'AIRLOCK_PUBLISH_BASE_URL': 'https://docs.example',
              'AIRLOCK_PUBLISH_TOKEN': 'sekret'})
    seen = []
    def fake_ingest(method, ep, body=None, timeout=20, version='0'):
        seen.append((method, ep, body, timeout, version))
        if ep == '/health':
            raise OSError('legacy runtime has no health')
        if ep.startswith('/list'):
            return {'ok': True, 'items': []}
        return {'ok': True, 'result': {'expiry': 1790000000, 'ttl_hours': body.get('ttl_hours')}}
    native_ingest = m._ingest
    m._ingest = fake_ingest
    check('remote enabled', m.PUBLIC_ENABLED and m.PUBLIC_MODE == 'remote')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _StubIngest)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_url = m.INGEST_URL
    m.INGEST_URL = f'http://127.0.0.1:{server.server_address[1]}'
    m._ingest = native_ingest
    _StubIngest.seen = []
    m._ingest('GET', '/list', version='0')
    m._ingest('GET', '/list', version='1')
    server.shutdown(); server.server_close(); thread.join()
    m.INGEST_URL, m._ingest = real_url, fake_ingest
    check('each protocol request sends exactly its matching token header',
          _StubIngest.seen[0][1:3] == ('sekret', None)
          and _StubIngest.seen[1][1:3] == (None, 'sekret'), str(_StubIngest.seen))
    page(share, 'r.html')
    ok, res = m.publish_public('r.html', 336, OWNER)
    check('remote publish ok', ok, str(res))
    method, pathq, body, _timeout, version = seen[-1]
    check('POST /ingest', method == 'POST' and pathq == '/ingest', f'{method} {pathq}')
    check('legacy operations use only the v0 transport', version == '0', str(seen))
    check('remote token remains configured', m.TOKEN == 'sekret')
    check('payload keys unchanged',
          set(body) == {'slug', 'owner', 'src', 'title', 'ttl_hours', 'html_b64'}, str(sorted(body)))
    check('remote URL shape', res['url'].startswith('https://docs.example/'), res['url'])

    # [14] the 25MB cap is LOCAL-ONLY — a big snapshot must still go out remotely
    page(share, 'big.html', 'x' * (26 * 1024 * 1024))
    ok_big, res_big = m.publish_public('big.html', 24, OWNER)
    check('remote accepts a >25MB snapshot (no new cap)', ok_big, str(res_big)[:120])

    # New remote publications require an identity; an existing v0 link remains refreshable.
    ok_e, _ = m.publish_public('r.html', 24, '')
    check('new remote publication without owner is refused', not ok_e)

    ok_plan, plan_err = m.plan_bundle('r.html', owner=OWNER)
    check('remote bundle planning is available', ok_plan, str(plan_err))
    ok_docs, docs_err = m.publish_public('r.html', 24, OWNER,
                                         docs=['r.html'], plan_id=plan_err['plan_id'])
    check('legacy remote bundle is refused', not ok_docs and 'v1' in str(docs_err), str(docs_err))
    ok_gate, gate_res = m.publish_public('r.html', 24, OWNER, mode='gated', password='remote-password')
    check('legacy remote gated publish is refused', not ok_gate and 'v1' in str(gate_res), str(gate_res))

    # A v1 runtime uses the v1 transport for health/list/ingest/revoke and validates
    # the exact mode, URL, version, expiry, and TTL result fields.
    def v1_ingest(method, ep, body=None, timeout=20, version='0'):
        seen.append((method, ep, body, timeout, version))
        if ep == '/health':
            return {'ok': True, 'public_contract': {
                'supported_versions': ['0', '1'], 'modes': ['open', 'gated']}}
        if ep.startswith('/list'):
            return {'ok': True, 'items': []}
        if ep == '/revoke':
            return {'ok': True}
        slug = body['slug']
        mode = body.get('mode', 'open')
        prefix = '/g' if mode == 'gated' else ''
        return {'ok': True, 'result': {'contract_version': '1', 'mode': mode,
                'slug': slug, 'url': f'https://docs.example{prefix}/{slug}/',
                'expiry': int(time.time()) + int(body['ttl_hours']) * 3600,
                'ttl_hours': int(body['ttl_hours'])}}
    m._ingest = v1_ingest
    ok_v1, v1 = m.publish_public('r.html', 24, OWNER, mode='gated', password='secret')
    check('v1 gated publish succeeds', ok_v1 and v1.get('contract_version') == '1', str(v1))
    check('v1 flow uses the v1 transport on every successful request',
          all(call[4] == '1' for call in seen[-3:]), str(seen[-3:]))

    for mismatch in ('slug', 'ttl', 'expiry'):
        rollback_calls, created_slug = [], []
        def mismatch_ingest(method, ep, body=None, timeout=20, version='0'):
            if ep == '/health':
                return v1_ingest(method, ep, body, timeout, version)
            if ep.startswith('/list'):
                return {'ok': True, 'items': []}
            if ep == '/revoke':
                rollback_calls.append((body['slug'], body['owner'], version))
                return {'ok': True}
            created_slug.append(body['slug'])
            result = {'contract_version': '1', 'mode': body['mode'],
                      'slug': body['slug'],
                      'url': f"https://docs.example/{body['slug']}/",
                      'expiry': int(time.time()) + int(body['ttl_hours']) * 3600,
                      'ttl_hours': int(body['ttl_hours'])}
            if mismatch == 'slug':
                result.update({'slug': 'wrong-result-slug',
                               'url': 'https://docs.example/wrong-result-slug/'})
            elif mismatch == 'ttl':
                result['ttl_hours'] += 1
            else:
                result['expiry'] += 3600
            return {'ok': True, 'result': result}
        m._ingest = mismatch_ingest
        bad, bad_error = m.publish_public('r.html', 24, OWNER)
        expected_slugs = ([created_slug[0], 'wrong-result-slug'] if mismatch == 'slug'
                          else [created_slug[0]])
        expected = [(target, OWNER, '1') for target in expected_slugs]
        check(f'mismatched v1 {mismatch} fails closed and revokes every possible creation',
              not bad and 'mismatched' in str(bad_error)
              and rollback_calls == expected, f'{bad_error}; revoked={rollback_calls}')

    def duplicate_ingest(method, ep, body=None, timeout=20, version='0'):
        if ep == '/health':
            return v1_ingest(method, ep, body, timeout, version)
        if ep.startswith('/list'):
            return {'ok': True, 'items': [
                {'slug': 'one', 'src': 'r.html'}, {'slug': 'two', 'src': 'r.html'}]}
        raise AssertionError('ingest must not run after duplicate preflight')
    m._ingest = duplicate_ingest
    dup_ok, dup_error = m.publish_public('r.html', 24, OWNER)
    check('duplicate source preflight aborts with conflicting slugs',
          not dup_ok and 'one' in str(dup_error) and 'two' in str(dup_error), str(dup_error))

    def failed_list(method, ep, body=None, timeout=20, version='0'):
        if ep == '/health':
            return v1_ingest(method, ep, body, timeout, version)
        if ep.startswith('/list'):
            return {'ok': False, 'error': 'list offline'}
        raise AssertionError('ingest must not run after list failure')
    m._ingest = failed_list
    list_ok, list_error = m.publish_public('r.html', 24, OWNER)
    check('list failure aborts before ingest',
          not list_ok and 'list offline' in str(list_error), str(list_error))

    m2 = load({'AIRLOCK_PUBLISH_SHARE_DIR': share, 'AIRLOCK_PUBLISH_STATE_DIR': state,
               'AIRLOCK_PUBLISH_PUBLIC_MODE': 'local', 'AIRLOCK_PUBLISH_BASE_URL': 'https://x',
               'AIRLOCK_PUBLISH_PUBLIC_DIR': os.path.join(tmp, 'pub2')})
    ok_l, err_l = m2.publish_public('big.html', 24, OWNER)
    check('local REFUSES a >25MB snapshot', not ok_l and 'too large' in str(err_l), str(err_l)[:120])


# -------------------------------------------------------------- bundle + gate
def t_bundle_plan_contract(tmp):
    print('\n[bundle] plan is clamped, owner-bound, expiring, single-use, and drift-safe')
    share, pub, _state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'hub.html', '<a href="child.html">child</a><a href="/outside.html">outside</a>')
    page(share, 'child.html', '<a href="hub&#46;html#top">quoted</a><a href=hub&#46;html#top>unquoted</a>')
    page(share, 'outside.html', 'outside')

    ok, plan = m.plan_bundle('hub.html', 1000, OWNER)
    check('plan clamps max_docs server-side', ok and plan['max_docs'] == m.MAX_BUNDLE_DOCS, str(plan))
    check('plan discovers BFS candidate', [d['name'] for d in plan['docs']] == ['hub.html', 'child.html', 'outside.html'])
    bad, err = m._consume_bundle_plan(plan['plan_id'], 'other@example.com', 'hub.html', ['hub.html'])
    check('plan rejects mismatched owner without consuming', not bad and 'owner mismatch' in err and plan['plan_id'] in m._BUNDLE_PLANS, err)
    m._BUNDLE_PLANS[plan['plan_id']]['expires_at'] = 0
    expired, err = m._consume_bundle_plan(plan['plan_id'], OWNER, 'hub.html', ['hub.html'])
    check('plan rejects expiry', not expired and 'expired' in err, err)

    ok, plan = m.plan_bundle('hub.html', owner=OWNER)
    once, _record = m._consume_bundle_plan(plan['plan_id'], OWNER, 'hub.html', ['hub.html'])
    twice, err = m._consume_bundle_plan(plan['plan_id'], OWNER, 'hub.html', ['hub.html'])
    check('plan is single-use', once and not twice and 'already used' in err, err)

    ok, plan = m.plan_bundle('hub.html', owner=OWNER)
    page(share, 'child.html', 'changed after approval')
    published, err = m.publish_public('hub.html', 24, OWNER, docs=['hub.html', 'child.html'], plan_id=plan['plan_id'])
    check('source changes after plan are rejected', not published and 'changed after bundle plan' in str(err), str(err))

    page(share, 'child.html', '<a href="hub&#46;html#top">quoted</a><a href=hub&#46;html#top>unquoted</a>')
    _title, files, warnings = m.build_bundle_files('hub.html', ['hub.html', 'child.html', 'outside.html'])
    check('bundle rewrites quoted, unquoted, and entity internal links',
          b'href="./#top"' in files['child.html'] and b'href=./#top' in files['child.html'], files['child.html'].decode())
    check('bundle rewrites root-relative internal links', b'href="outside.html"' in files['index.html'],
          files['index.html'].decode())
    _title, _selected, unselected_warnings = m.build_bundle_files('hub.html', ['hub.html', 'child.html'])
    check('bundle warns for link outside selection', any('outside.html' in w for w in unselected_warnings),
          str(unselected_warnings))
    page(share, 'child.html', '<a href=hub.html href=outside.html>back</a>')
    _title, duplicate, _warnings = m.build_bundle_files('hub.html', ['hub.html', 'child.html'])
    check('bundle rewrites browser-first duplicate href only',
          b'href=./ href=outside.html' in duplicate['child.html'], duplicate['child.html'].decode())
    page(share, 'child.html', '<a href=hub&#46;html#top>back</a>')

    real_bundle_single_file = m.bundle_single_file
    bundle_reads = 0

    def count_bundle_reads(*args, **kwargs):
        nonlocal bundle_reads
        bundle_reads += 1
        return real_bundle_single_file(*args, **kwargs)

    m.bundle_single_file = count_bundle_reads
    try:
        m.build_bundle_files('hub.html', ['hub.html'])
    finally:
        m.bundle_single_file = real_bundle_single_file
    check('digest build reads each document once', bundle_reads == 1, str(bundle_reads))

    page(share, 'overview.html', '<a href="index.html">member</a>')
    page(share, 'index.html', 'ordinary member')
    check('bundle rejects a member named index.html', _raises(lambda: m.build_bundle_files(
        'overview.html', ['overview.html', 'index.html'])))

    page(share, 'self-close.html', '<template/><a href="child.html">after</a><a href="sub/child.html">nested</a>')
    ok, self_plan = m.plan_bundle('self-close.html', owner=OWNER)
    check('planner treats self-closing template as inert', ok and
          [d['name'] for d in self_plan['docs']] == ['self-close.html'], str(self_plan))
    check('links inside self-closing template are ignored', ok and self_plan['unsupported'] == [], str(self_plan))
    _title, self_files, self_warnings = m.build_bundle_files('self-close.html', ['self-close.html', 'child.html'])
    check('inert links do not reach build warnings', not any('sub/child.html' in w for w in self_warnings), str(self_warnings))

    page(share, 'self-close-anchor.html', '<a href="child.html"/><a href=child.html/>')
    ok, anchor_plan = m.plan_bundle('self-close-anchor.html', owner=OWNER)
    check('self-closing anchor is collected', ok and 'child.html' in
          [d['name'] for d in anchor_plan['docs']], str(anchor_plan))

    ok, two_plan = m.plan_bundle('hub.html', owner=OWNER)
    ok, two = m.publish_public('hub.html', 24, OWNER, docs=['hub.html', 'child.html'], plan_id=two_plan['plan_id'])
    check('two-member bundle publishes', ok, str(two))
    ok, one_plan = m.plan_bundle('hub.html', owner=OWNER)
    ok, one = m.publish_public('hub.html', 24, OWNER, docs=['hub.html'], plan_id=one_plan['plan_id'])
    check('smaller re-publish keeps the bundle slug', ok and one['slug'] == two['slug'], str(one))
    check('smaller re-publish removes stale bundle members', not os.path.exists(os.path.join(pub, one['slug'], 'child.html')))

    old_docs = m.MAX_BUNDLE_DOCS
    old_bytes = m.MAX_BUNDLE_TOTAL_BYTES
    old_local_bytes = m.LOCAL_MAX_BYTES
    try:
        m.MAX_BUNDLE_DOCS = 2
        check('build enforces document cap again', _raises(lambda: m.build_bundle_files(
            'hub.html', ['hub.html', 'child.html', 'outside.html'])))
        m.LOCAL_MAX_BYTES = 10
        check('build enforces total-byte cap again', _raises(lambda: m.build_bundle_files('hub.html', ['hub.html'])))
    finally:
        m.MAX_BUNDLE_DOCS = old_docs
        m.MAX_BUNDLE_TOTAL_BYTES = old_bytes
        m.LOCAL_MAX_BYTES = old_local_bytes

    # The same capability racing in two requests may reach ingest at most once.
    ok, plan = m.plan_bundle('hub.html', owner=OWNER)
    start = threading.Barrier(2)
    results, ingest_calls = [], []
    real_ingest = m._local_ingest
    def counted_ingest(*args, **kwargs):
        ingest_calls.append(args[0])
        return real_ingest(*args, **kwargs)
    m._local_ingest = counted_ingest
    def publish_once():
        start.wait()
        results.append(m.publish_public('hub.html', 24, OWNER,
                                        docs=['hub.html'], plan_id=plan['plan_id']))
    threads = [threading.Thread(target=publish_once) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check('concurrent use of one plan succeeds at most once', sum(1 for ok, _ in results if ok) == 1, str(results))
    check('bundle output writer ran once', len(ingest_calls) == 1, str(ingest_calls))


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def t_parity_migrations(tmp):
    print('\n[parity] attachments, context-aware assets, Unicode names, and image namespace')
    share, _pub, _state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'bundle.html', '<title>Bundle</title><a href="guide.pdf">guide</a>'
         '<a href="photo.png">photo</a><script>"<img src=\'fake.png\'>"</script>'
         '<!-- <img src="secret.png"> -->')
    with open(os.path.join(share, 'guide.pdf'), 'wb') as fh:
        fh.write(b'pdf')
    with open(os.path.join(share, 'photo.png'), 'wb') as fh:
        fh.write(b'png')
    ok, plan = m.plan_bundle('bundle.html', owner=OWNER)
    check('plan reports attachment names, bytes, and sources',
          ok and [a['name'] for a in plan['attachments']] == ['guide.pdf', 'photo.png']
          and plan['attachment_bytes'] == 6
          and all(a['source'].endswith(a['name']) for a in plan['attachments']), str(plan))
    _title, files, _warnings = m.build_bundle_files('bundle.html', ['bundle.html'])
    check('attachment-bearing build carries approved linked files',
          files['guide.pdf'] == b'pdf' and files['photo.png'] == b'png')
    check('inactive comment and script references are not treated as assets',
          b'fake.png' in files['index.html'] and b'secret.png' in files['index.html'])

    page(share, 'missing-attachment.html', '<a href="absent.pdf">missing</a>')
    check('unresolved active local attachment fails publication',
          _raises(lambda: m.build_bundle_files(
              'missing-attachment.html', ['missing-attachment.html'])))
    outside = os.path.join(tmp, 'outside.pdf')
    with open(outside, 'wb') as fh:
        fh.write(b'outside')
    os.symlink(outside, os.path.join(share, 'outside.pdf'))
    page(share, 'symlink-attachment.html', '<a href="outside.pdf">outside</a>')
    ok_symlink, symlink_error = m.plan_bundle('symlink-attachment.html', owner=OWNER)
    check('PB-A4 keep does not widen attachment symlink provenance',
          not ok_symlink and 'symlink provenance' in str(symlink_error), str(symlink_error))
    check('attachment reader independently refuses a symlink',
          _raises(lambda: m._read_attachment('outside.pdf')))

    page(share, 'missing.html', '<img src="missing.png">')
    check('unresolved active local assets fail publication',
          _raises(lambda: m.bundle_single_file('missing.html')))
    page(share, 'styles.html', '<style>.x{background:url(missing.png)}</style>')
    check('unresolved local CSS url fails publication',
          _raises(lambda: m.bundle_single_file('styles.html')))

    old_attachments, old_member, old_total = (
        m.MAX_BUNDLE_ATTACHMENTS, m.MAX_BUNDLE_MEMBER_BYTES, m.MAX_BUNDLE_TOTAL_BYTES)
    try:
        m.MAX_BUNDLE_ATTACHMENTS = 1
        check('attachment count bound is enforced',
              _raises(lambda: m.build_bundle_files('bundle.html', ['bundle.html'])))
        m.MAX_BUNDLE_ATTACHMENTS = old_attachments
        m.MAX_BUNDLE_MEMBER_BYTES = 2
        check('attachment member-size bound is enforced before ingest',
              _raises(lambda: m.build_bundle_files('bundle.html', ['bundle.html'])))
        m.MAX_BUNDLE_MEMBER_BYTES = old_member
        m.MAX_BUNDLE_TOTAL_BYTES = 5
        check('attachment bundle total-size bound is enforced before ingest',
              _raises(lambda: m.build_bundle_files('bundle.html', ['bundle.html'])))
    finally:
        m.MAX_BUNDLE_ATTACHMENTS, m.MAX_BUNDLE_MEMBER_BYTES, m.MAX_BUNDLE_TOTAL_BYTES = (
            old_attachments, old_member, old_total)

    decomposed = '한글 보고서\u0000.pdf'
    safe = m._safe_upload_name(decomposed)
    check('upload names are NFC-normalized and controls removed',
          unicodedata.is_normalized('NFC', safe) and safe == '한글 보고서_.pdf', safe)
    check('upload names have an explicit 120-character bound',
          0 < len(m._safe_upload_name('가' * 200 + '.pdf')) <= m.UPLOAD_NAME_MAX_CHARS)
    bounded = m._safe_upload_name('가' * 200 + '.pdf')
    check('multibyte upload names fit the filesystem byte boundary',
          len(bounded.encode('utf-8')) <= m.UPLOAD_NAME_MAX_BYTES, bounded)
    upload_data = base64.b64encode(b'payload').decode()
    ok_one, saved_one = m.save_uploaded_file('가' * 200 + '.pdf', upload_data)
    ok_two, saved_two = m.save_uploaded_file('가' * 200 + '.pdf', upload_data)
    check('multibyte collision names remain distinct and byte-bounded',
          ok_one and ok_two and saved_one['name'] != saved_two['name']
          and all(len(item['name'].encode('utf-8')) <= m.UPLOAD_NAME_MAX_BYTES
                  for item in (saved_one, saved_two)), f'{saved_one}; {saved_two}')
    os.makedirs(m.UPLOADS, exist_ok=True)
    with open(os.path.join(m.UPLOADS, '이미지005-20260816-010203.jpg'), 'wb') as fh:
        fh.write(b'old')
    check('existing Korean image sequence advances canonical image writes', m._next_upload_seq() == 6)


def t_gated_contract(tmp):
    print('\n[gated] password validation, safe mode transition, credential cleanup')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'gate.html', 'private')
    before = list(os.listdir(pub)) if os.path.exists(pub) else []
    ok, err = m.publish_public('gate.html', 24, OWNER, mode='gated', password='')
    check('gated rejects a missing password before writing', not ok and 'requires a password' in str(err), str(err))
    check('missing password leaves open target untouched', (list(os.listdir(pub)) if os.path.exists(pub) else []) == before)

    page(share, 'stuck.html', 'stuck')
    ok, stuck = m.publish_public('stuck.html', 24, OWNER)
    os.makedirs(os.path.join(pub, stuck['slug'], 'unexpected'), exist_ok=True)
    ok, err = m.publish_public('stuck.html', 24, OWNER, mode='gated', password='nope')
    check('mode transition fails closed when old tree cannot be removed', not ok and 'refusing mode transition' in str(err), str(err))
    check('failed transition leaves no gated duplicate', not os.path.exists(
        os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], stuck['slug'])))
    check('failed transition preserves the old open snapshot', os.path.isfile(
        os.path.join(pub, stuck['slug'], 'index.html')))

    ok, opened = m.publish_public('gate.html', 24, OWNER)
    check('open publish before transition works', ok, str(opened))
    open_dir = os.path.join(pub, opened['slug'])
    ok, gated = m.publish_public('gate.html', 24, OWNER, mode='gated', password='first')
    gated_dir = os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], gated.get('slug', ''))
    check('open-to-gated keeps the slug', ok and gated['slug'] == opened['slug'], str(gated))
    check('open-to-gated removes unauthenticated copy', not os.path.exists(open_dir))
    check('gated copy is in separate tree', os.path.isfile(os.path.join(gated_dir, 'index.html')))
    listed = m.public_list(OWNER)
    check('gated list returns the gated URL', listed['items'][0]['url'] == gated['url'], str(listed))
    passwd = os.path.join(env['AIRLOCK_PUBLISH_HTPASSWD_DIR'], gated['slug'] + '.htpasswd')
    check('gated publish writes a slug credential', os.path.isfile(passwd) and 'fake-first' in open(passwd).read())
    check('credential file is nginx-readable (0644)', oct(os.stat(passwd).st_mode)[-3:] == '644')
    events = []
    real_update = m._update_htpasswd
    real_replace = m.os.replace

    def observe_update(slug, password=None):
        result = real_update(slug, password)
        events.append(('credential', password, os.path.exists(passwd)))
        return result

    def observe_replace(source, target):
        if target == gated_dir and '.stage-' in str(source):
            events.append(('content', os.path.exists(passwd)))
        return real_replace(source, target)

    m._update_htpasswd = observe_update
    m.os.replace = observe_replace
    try:
        ok, rotated = m.publish_public('gate.html', 24, OWNER, mode='gated', password='second')
    finally:
        m._update_htpasswd = real_update
        m.os.replace = real_replace
    check('gated re-publish rotates the credential', ok and 'fake-second' in open(passwd).read() and 'fake-first' not in open(passwd).read())
    check('gated credential closes before content replacement', events == [
        ('credential', None, False), ('content', False), ('credential', 'second', True)], str(events))
    revoked = m.public_revoke(rotated['slug'], OWNER)
    check('revoke removes gated credential', revoked.get('ok') and not os.path.exists(passwd))
    check('revoke removes gated content', not os.path.exists(gated_dir))

    page(share, 'expiry.html', 'expiry')
    ok, expiry = m.publish_public('expiry.html', 24, OWNER, mode='gated', password='expiry-pass')
    expiry_dir = os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], expiry['slug'])
    os.makedirs(os.path.join(expiry_dir, 'unexpected'), exist_ok=True)
    state_doc = json.load(open(os.path.join(state, 'publish-public.json')))
    state_doc['items'][expiry['slug']]['expiry'] = 0
    json.dump(state_doc, open(os.path.join(state, 'publish-public.json'), 'w'))
    m._local_sweep_only()
    expiry_passwd = os.path.join(env['AIRLOCK_PUBLISH_HTPASSWD_DIR'], expiry['slug'] + '.htpasswd')
    check('expiry removes credential even when safe deletion fails', not os.path.exists(expiry_passwd))
    check('failed expiry deletion retains state for retry', expiry['slug'] in json.load(
        open(os.path.join(state, 'publish-public.json')))['items'])

    # htpasswd reads ONE line from stdin and bcrypt ignores everything past 72 bytes, so
    # either input would store a credential shorter than the one the owner believes they set.
    ok, err = m.publish_public('gate.html', 24, OWNER, mode='gated', password='abc\ndef')
    check('newline in a password is refused', not ok and 'control characters' in str(err), str(err))
    ok, err = m.publish_public('gate.html', 24, OWNER, mode='gated', password='x' * 73)
    check('password past the bcrypt limit is refused', not ok and '72 bytes' in str(err), str(err))

    m_no_tool = load({**env, 'AIRLOCK_PUBLISH_HTPASSWD_BIN': os.path.join(tmp, 'missing-htpasswd')})
    ok, err = m_no_tool.publish_public('gate.html', 24, OWNER, mode='gated', password='x')
    check('missing password tool fails closed', not ok and 'unavailable' in str(err), str(err))


def t_gated_reconciliation_and_storage(tmp):
    print('\n[gated extras] per-slug isolation, storage preflight, orphan cleanup, and adoption')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'one.html', 'one'); page(share, 'two.html', 'two')
    ok1, one = m.publish_public('one.html', 24, OWNER, mode='gated', password='one')
    ok2, two = m.publish_public('two.html', 24, OWNER, mode='gated', password='two')
    one_auth = m._htpasswd_path(one['slug']); two_auth = m._htpasswd_path(two['slug'])
    check('gated credentials are isolated per slug', ok1 and ok2 and one_auth != two_auth and
          os.path.isfile(one_auth) and os.path.isfile(two_auth) and one['slug'] not in open(two_auth).read(),
          f'{one_auth}, {two_auth}')

    page(share, 'keep.html', 'open copy')
    ok, opened = m.publish_public('keep.html', 24, OWNER)
    old_check, m._gated_storage_check = m._gated_storage_check, lambda: 'gated_dir not writable'
    try:
        ok, err = m.publish_public('keep.html', 24, OWNER, mode='gated', password='blocked')
    finally:
        m._gated_storage_check = old_check
    check('unwritable gated target preserves open snapshot', not ok and 'not writable' in str(err) and
          os.path.isfile(os.path.join(pub, opened['slug'], 'index.html')), str(err))

    orphan = os.path.join(env['AIRLOCK_PUBLISH_HTPASSWD_DIR'], 'orphan-abc.htpasswd')
    with open(orphan, 'w', encoding='utf-8') as fh: fh.write('orphan-abc:hash\n')
    m._local_sweep_only()
    check('state loss cleanup removes orphan credential files', not os.path.exists(orphan))

    page(share, 'lost.html', 'lost state')
    ok, lost = m.publish_public('lost.html', 24, OWNER, mode='gated', password='lost')
    lost_auth = m._htpasswd_path(lost['slug'])
    state_doc = json.load(open(os.path.join(state, 'publish-public.json')))
    state_doc['items'].pop(lost['slug'])
    json.dump(state_doc, open(os.path.join(state, 'publish-public.json'), 'w'))
    m._local_sweep_only()
    check('state-loss adoption removes a retained gated credential', ok and not os.path.exists(lost_auth))

    slug = one['slug']
    os.makedirs(os.path.join(pub, slug), exist_ok=True)
    with open(os.path.join(pub, slug, 'index.html'), 'w') as fh: fh.write('open duplicate')
    os.makedirs(os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], slug), exist_ok=True)
    with open(os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], slug, 'index.html'), 'w') as fh: fh.write('duplicate')
    state_doc = json.load(open(os.path.join(state, 'publish-public.json')))
    state_doc['items'][slug]['mode'] = 'open'
    json.dump(state_doc, open(os.path.join(state, 'publish-public.json'), 'w'))
    reconciled = m._reconcile(m._state_load(), int(time.time()))
    check('adoption does not overwrite an existing state entry', reconciled['items'][slug]['owner'] == OWNER and
          reconciled['items'][slug]['mode'] == 'open', str(reconciled['items'][slug]))


def t_local_bundle_limit(tmp):
    print('\n[bundle limit] local cap is enforced before plan approval')
    share, _pub, _state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'large.html', 'x' * (m.LOCAL_MAX_BYTES + 1))
    ok, result = m.plan_bundle('large.html', owner=OWNER)
    check('local 25MB cap rejects at bundle plan time', not ok and 'size exceeds limit' in str(result), str(result)[:160])


def t_open_sweep_without_gated(tmp):
    print('\n[sweep] open TTL cleanup survives a missing gated directory')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'open.html', 'open snapshot')
    ok, result = m.publish_public('open.html', 24, OWNER)
    slug = result['slug'] if ok else ''
    shutil.rmtree(env['AIRLOCK_PUBLISH_GATED_DIR'])
    state_doc = json.load(open(os.path.join(state, 'publish-public.json')))
    state_doc['items'][slug]['expiry'] = int(time.time()) - 1
    with open(os.path.join(state, 'publish-public.json'), 'w', encoding='utf-8') as fh:
        json.dump(state_doc, fh)
    gone = m._local_sweep_only()
    check('sweep runs without gated_dir', ok and slug in gone, str(gone))
    check('expired open snapshot is deleted', ok and not os.path.exists(os.path.join(pub, slug)))


def t_local_ingest_transaction(tmp):
    print('\n[transaction] failed writes never replace the previous snapshot')
    share, pub, _state, env = make_dirs(tmp)
    m = load(env)
    real_open = open

    page(share, 'content-fail.html', 'old content')
    ok, old = m.publish_public('content-fail.html', 24, OWNER)
    old_path = os.path.join(pub, old['slug'], 'index.html')
    page(share, 'content-fail.html', 'new content')
    writes = 0

    def fail_first_write(path, mode='r', *args, **kwargs):
        nonlocal writes
        if 'wb' in mode:
            writes += 1
            if writes == 1:
                raise OSError('injected content write failure')
        return real_open(path, mode, *args, **kwargs)

    m.open = fail_first_write
    try:
        failed, error = m.publish_public('content-fail.html', 24, OWNER)
    finally:
        m.open = real_open
    check('content write failure is returned', ok and not failed and 'stage' in str(error), str(error))
    check('content write failure preserves old snapshot', open(old_path).read().find('old content') >= 0,
          open(old_path).read())

    page(share, 'credential-fail.html', 'old gated content')
    ok, old_gate = m.publish_public('credential-fail.html', 24, OWNER,
                                    mode='gated', password='old-password')
    gate_path = m._htpasswd_path(old_gate['slug'])
    old_auth = open(gate_path, 'rb').read()
    gate_content = os.path.join(env['AIRLOCK_PUBLISH_GATED_DIR'], old_gate['slug'], 'index.html')
    page(share, 'credential-fail.html', 'new gated content')
    real_update = m._update_htpasswd
    def fail_update(*_args, **_kwargs):
        raise OSError('injected credential write failure')
    m._update_htpasswd = fail_update
    try:
        failed, error = m.publish_public('credential-fail.html', 24, OWNER,
                                         mode='gated', password='new-password')
    finally:
        m._update_htpasswd = real_update
    check('credential write failure is returned', ok and not failed and 'commit' in str(error), str(error))
    check('credential write failure preserves old content', open(gate_content).read().find('old gated content') >= 0,
          open(gate_content).read())
    check('credential write failure preserves old password', open(gate_path, 'rb').read() == old_auth)

    old_files = {'index.html': b'old index', 'child.html': b'old child'}
    initial = m._local_ingest('bundle-abc', OWNER, 'bundle.html', 'bundle', 24, old_files)
    ok = initial.get('ok')
    bundle_dir = os.path.join(pub, initial['result']['slug']) if ok else ''
    writes = 0

    def fail_second_write(path, mode='r', *args, **kwargs):
        nonlocal writes
        if 'wb' in mode:
            writes += 1
            if writes == 2:
                raise OSError('injected second member failure')
        return real_open(path, mode, *args, **kwargs)

    m.open = fail_second_write
    try:
        result = m._local_ingest(initial['result']['slug'], OWNER, 'bundle.html', 'bundle', 24,
                                 {'index.html': b'new index', 'child.html': b'new child'})
    finally:
        m.open = real_open
    check('bundle mid-write failure is returned', ok and not result.get('ok') and 'stage' in result.get('error', ''), str(result))
    check('bundle mid-write failure preserves every old member',
          open(os.path.join(bundle_dir, 'index.html'), 'rb').read() == b'old index' and
          open(os.path.join(bundle_dir, 'child.html'), 'rb').read() == b'old child')
    check('bundle mid-write failure leaves no transaction directory',
          not any(any(f'.{kind}-' in name for kind in ('stage', 'old', 'failed'))
                  for name in os.listdir(pub)))

    page(share, 'state-fail.html', 'old state-fail content')
    ok, state_old = m.publish_public('state-fail.html', 24, OWNER)
    state_path = os.path.join(pub, state_old['slug'], 'index.html')
    page(share, 'state-fail.html', 'new state-fail content')
    real_save = m._state_save
    real_replace = m.os.replace
    def fail_state_save(_state):
        raise OSError('injected state save failure')
    m._state_save = fail_state_save

    def fail_restore_replace(source, target):
        if '.old-' in str(source):
            raise OSError('injected restore rename failure')
        return real_replace(source, target)

    m.os.replace = fail_restore_replace
    try:
        result = m._local_ingest(state_old['slug'], OWNER, 'state-fail.html', 'state-fail', 24,
                                 {'index.html': b'new state-fail content'})
    finally:
        m._state_save = real_save
        m.os.replace = real_replace
    failed, error = not result.get('ok'), result.get('error', '')
    check('state save failure is returned', ok and failed and 'state save' in str(error), str(result))
    check('rename failure fallback restores old snapshot', open(state_path).read().find('old state-fail content') >= 0,
          open(state_path).read())


def t_state_first_transaction(tmp):
    print('\n[state-first] state is durable before content and rolls back on install failure')
    share, pub, state, env = make_dirs(tmp)
    m = load(env)
    page(share, 'ttl.html', 'old ttl content')
    ok, initial = m.publish_public('ttl.html', 24, OWNER)
    slug = initial['slug']
    live = os.path.join(pub, slug)
    state_path = os.path.join(state, 'publish-public.json')
    old_expiry = json.load(open(state_path))['items'][slug]['expiry']

    real_replace = m.os.replace
    observed = []

    def observe_install(source, target):
        if target == live and '.stage-' in str(source):
            with open(state_path, encoding='utf-8') as fh:
                observed.append(json.load(fh)['items'][slug]['expiry'])
        return real_replace(source, target)

    m.os.replace = observe_install
    try:
        updated = m._local_ingest(slug, OWNER, 'ttl.html', 'ttl', 1,
                                   {'index.html': b'new ttl content'})
    finally:
        m.os.replace = real_replace
    updated_expiry = json.load(open(state_path))['items'][slug]['expiry']
    check('shorter TTL is saved before content becomes live', updated.get('ok') and
          observed == [updated['result']['expiry']] and updated_expiry < old_expiry,
          f'observed={observed}, state={updated_expiry}, result={updated}')
    check('successful state-first publish installs new content', open(
        os.path.join(live, 'index.html')).read() == 'new ttl content')

    def fail_install(source, target):
        if target == live and '.stage-' in str(source):
            raise OSError('injected content install failure')
        return real_replace(source, target)

    m.os.replace = fail_install
    try:
        failed = m._local_ingest(slug, OWNER, 'ttl.html', 'ttl', 720,
                                 {'index.html': b'failed content'})
    finally:
        m.os.replace = real_replace
    restored = json.load(open(state_path))['items'][slug]['expiry']
    check('content failure is reported', not failed.get('ok') and 'commit' in failed.get('error', ''), str(failed))
    check('content failure restores the prior TTL and bytes', restored == updated_expiry and
          open(os.path.join(live, 'index.html')).read() == 'new ttl content',
          f'state={restored}, content={open(os.path.join(live, "index.html")).read()}')


def main():
    for fn in (t_happy_path, t_slug_abuse, t_symlinked_source, t_empty_owner, t_owner_collision,
               t_crash_between, t_concurrent, t_corrupt_state, t_overlap_refused,
               t_config_shapes, t_remote_regression, t_bundle_plan_contract, t_gated_contract,
               t_gated_reconciliation_and_storage, t_local_bundle_limit,
               t_open_sweep_without_gated, t_local_ingest_transaction,
               t_state_first_transaction, t_parity_migrations):
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
