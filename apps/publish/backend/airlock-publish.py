#!/usr/bin/env python3
"""airlock-publish — static-share manager + optional pluggable external publish.

Runs on loopback (127.0.0.1:<backend_port>); the hub nginx proxies /publish/api/
here. It manages a local static-share directory (default ~/public_html): list,
unpublish (unlink symlinks, keeping the original), delete direct files (2-step
confirm), batch, repair broken symlinks, and accept clipboard/file uploads into
~/uploads (the notepad drop). It never parses airlock.toml itself — the installer
passes everything via the environment.

Optional external publish is a PLUGGABLE target: if AIRLOCK_PUBLISH_INGEST_URL +
a token are configured, a published HTML page can be snapshotted (assets inlined
into one self-contained file) and POSTed to that ingest endpoint, returning a
public URL. Unconfigured => local-only (the external endpoints report disabled).

Ingest protocol (what a target must implement) — JSON over HTTPS, the token in
the `X-Airlock-Publish-Token` header:
  POST <ingest>/ingest      {slug, owner, src, title, ttl_hours, html_b64} -> {ok, result:{expiry, ttl_hours}}
  GET  <ingest>/list?owner= -> {ok, items:[{slug, owner, src, title, expiry, expired}]}
  POST <ingest>/revoke      {slug, owner} -> {ok}
  POST <ingest>/set-expiry  {slug, owner, ttl_hours} -> {ok}
The public URL shown to the user is `<base_url>/<slug>/`.
"""
import base64
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.expanduser(os.environ.get('AIRLOCK_PUBLISH_SHARE_DIR', '~/public_html'))
PORT = int(os.environ.get('AIRLOCK_PUBLISH_BACKEND_PORT', '18803'))
UPLOADS = os.path.expanduser(os.environ.get('AIRLOCK_PUBLISH_UPLOADS_DIR', '~/uploads'))
HOME = os.path.expanduser('~')
IDENTITY_HEADER = os.environ.get('AIRLOCK_IDENTITY_HEADER', 'Tailscale-User-Login')

# ---- pluggable external publish target (all optional) ----
INGEST_URL = os.environ.get('AIRLOCK_PUBLISH_INGEST_URL', '').rstrip('/')
BASE_URL = os.environ.get('AIRLOCK_PUBLISH_BASE_URL', '').rstrip('/')
# The token lives in an env var whose NAME is configured (secret stays out of the
# config file); default AIRLOCK_PUBLISH_TOKEN. The installer wires an EnvironmentFile.
_TOKEN_ENV = os.environ.get('AIRLOCK_PUBLISH_TOKEN_ENV', 'AIRLOCK_PUBLISH_TOKEN')
TOKEN = os.environ.get(_TOKEN_ENV, '')
PUBLIC_ENABLED = bool(INGEST_URL and BASE_URL and TOKEN)


def list_items():
    """One level of the share dir (no recursion)."""
    items = []
    if not os.path.isdir(ROOT):
        return items
    for name in sorted(os.listdir(ROOT)):
        if name.startswith('.'):
            continue
        full = os.path.join(ROOT, name)
        try:
            lstat = os.lstat(full)
        except OSError:
            continue
        is_link = os.path.islink(full)
        is_dir = os.path.isdir(full)
        target = None
        if is_link:
            try:
                raw = os.readlink(full)
                target = raw.replace(HOME, '~') if raw.startswith(HOME) else raw
            except OSError:
                target = '(broken link)'
        if name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp')):
            ftype = 'image'
        elif name.endswith('.html'):
            ftype = 'html'
        elif is_dir:
            ftype = 'dir'
        else:
            ftype = 'file'
        target_dir = ''
        if target:
            target_dir = os.path.dirname(target) or '/'
        elif not is_link:
            target_dir = '(direct file)'
        items.append({
            'name': name,
            'type': ftype,
            'target': target,
            'target_dir': target_dir,
            'isLink': is_link,
            'isDir': is_dir,
            'size': format_size(lstat.st_size, is_dir),
            'mtime': datetime.fromtimestamp(lstat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            'mtime_epoch': int(lstat.st_mtime),
        })
    return items


def format_size(size, is_dir):
    if is_dir:
        return 'dir'
    if size < 1024:
        return f'{size} B'
    if size < 1024 * 1024:
        return f'{size // 1024} KB'
    return f'{size / (1024*1024):.1f} MB'


def safe_resolve(name):
    """name -> absolute path inside ROOT. Blocks path traversal. Lexical (does
    not follow the symlink itself)."""
    if not name or '/' in name or name.startswith('.'):
        return None
    real_root = os.path.realpath(ROOT)
    lexical = os.path.normpath(os.path.join(ROOT, name))
    if not lexical.startswith(real_root + os.sep) and lexical != real_root:
        return None
    return lexical


def unpublish(name):
    """Unlink a symlink (original preserved). Refuses direct files."""
    path = safe_resolve(name)
    if not path or not os.path.lexists(path):
        return False, f'not found: {name}'
    if not os.path.islink(path):
        return False, 'not a symlink — use unpublish-direct with confirm_name'
    try:
        os.unlink(path)
        return True, f'unlinked: {name}'
    except OSError as e:
        return False, str(e)


def unpublish_direct(name, confirm_name):
    """Delete a direct (non-symlink) file — only when the name is retyped."""
    if name != confirm_name:
        return False, 'confirm_name mismatch'
    path = safe_resolve(name)
    if not path or not os.path.lexists(path):
        return False, f'not found: {name}'
    if os.path.islink(path):
        return False, 'is symlink — use plain unpublish'
    if os.path.isdir(path):
        return False, 'is directory — refusing rm -rf'
    try:
        os.unlink(path)
        return True, f'deleted (direct): {name}'
    except OSError as e:
        return False, str(e)


def unpublish_batch(names, include_direct=False):
    """symlink -> unlink; direct file -> delete only if include_direct; real
    directory -> refused (no rm -rf). Returns a per-item result list."""
    results = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        path = safe_resolve(name)
        if not path or not os.path.lexists(path):
            results.append({'name': name, 'ok': False, 'kind': 'missing', 'message': f'not found: {name}'})
            continue
        if os.path.islink(path):
            ok, msg = unpublish(name)
            results.append({'name': name, 'ok': ok, 'kind': 'symlink', 'message': msg})
        elif os.path.isdir(path):
            results.append({'name': name, 'ok': False, 'kind': 'dir', 'message': 'directory — refused'})
        elif include_direct:
            ok, msg = unpublish_direct(name, name)
            results.append({'name': name, 'ok': ok, 'kind': 'direct', 'message': msg})
        else:
            results.append({'name': name, 'ok': False, 'kind': 'direct-skipped', 'message': 'direct file skipped (include_direct=false)'})
    return results


# ---- broken-symlink repair / cleanup ----
def _wt_to_main_candidates(target):
    """If a broken target points inside a git worktree, propose the main-repo path."""
    candidates = []
    m = re.match(r'^(.*?)-wt/[^/]+/(.+)$', target)      # ~/x/repo-wt/<slug>/rest -> ~/x/repo/rest
    if m:
        candidates.append(f'{m.group(1)}/{m.group(2)}')
    m = re.match(r'^(.+?)/wt/[^/]+/(.+)$', target)       # ~/x/repo/wt/<slug>/rest -> ~/x/repo/rest
    if m:
        candidates.append(f'{m.group(1)}/{m.group(2)}')
    seen = set()
    return [c for c in candidates if c not in seen and not seen.add(c)]


def analyze_broken(name):
    path = safe_resolve(name)
    if not path or not os.path.islink(path):
        return None
    try:
        target = os.readlink(path)
    except OSError:
        return {'name': name, 'action': 'unlink', 'reason': 'broken readlink', 'old_target': None, 'new_target': None}
    if os.path.exists(target):
        return None
    expanded = target if target.startswith('/') else os.path.realpath(os.path.join(os.path.dirname(path), target))
    new_target = next((c for c in _wt_to_main_candidates(expanded) if os.path.exists(c)), None)
    return {
        'name': name,
        'action': 'repair' if new_target else 'unlink',
        'reason': 'worktree->main repair' if new_target else 'target not found in any repair candidate',
        'old_target': target,
        'new_target': new_target,
    }


def repair_or_cleanup_all():
    if not os.path.isdir(ROOT):
        return []
    results = []
    for name in sorted(os.listdir(ROOT)):
        if name.startswith('.'):
            continue
        full = os.path.join(ROOT, name)
        if not os.path.islink(full) or os.path.exists(full):
            continue
        info = analyze_broken(name)
        if not info:
            continue
        try:
            os.unlink(full)
            if info['action'] == 'repair' and info['new_target']:
                os.symlink(info['new_target'], full)
            results.append({**info, 'ok': True})
        except OSError as e:
            results.append({**info, 'ok': False, 'error': str(e)})
    return results


# ==== external publish: self-contained snapshot + ingest push (pluggable) ====

_RE_CSS = re.compile(r'<link\b[^>]*\brel=["\']?stylesheet["\']?[^>]*>', re.I)
_RE_HREF = re.compile(r'\bhref=["\']([^"\']+)["\']', re.I)
_RE_JS = re.compile(r'<script\b([^>]*)\bsrc=["\']([^"\']+)["\']([^>]*)>\s*</script>', re.I)
_RE_IMG = re.compile(r'(<img\b[^>]*\bsrc=)["\']([^"\']+)["\']', re.I)
_RE_TITLE = re.compile(r'<title>([^<]*)</title>', re.I)
_RE_SCHEME = re.compile(r'^[a-z]+:', re.I)


def _read_share_file(ref, base_dir):
    """Resolve a local asset ref to a real file UNDER ROOT and read its bytes.
    Root-relative (/x) is relative to the share dir; otherwise to the page's dir.
    Returns (bytes, None) or (None, reason). Refuses anything outside ROOT."""
    ref = ref.split('#', 1)[0].split('?', 1)[0]
    if not ref or _RE_SCHEME.match(ref) or ref.startswith('//'):
        return None, 'external'
    cand = os.path.join(ROOT, ref.lstrip('/')) if ref.startswith('/') else os.path.join(base_dir, ref)
    real = os.path.realpath(cand)
    if not (real == os.path.realpath(ROOT) or real.startswith(os.path.realpath(ROOT) + os.sep)):
        return None, 'outside share dir'
    try:
        with open(real, 'rb') as fh:
            return fh.read(), None
    except OSError as e:
        return None, str(e)


def _guess_ctype(path):
    ext = os.path.splitext(path)[1].lower()
    return {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp'}.get(ext, 'image/png')


def bundle_single_file(name):
    """Inline a published HTML page's local css/js/img into ONE self-contained
    file (read from disk — gate-safe, no HTTP self-fetch). External refs stay.
    Returns (title, html_bytes)."""
    path = safe_resolve(name)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(name)
    base_dir = os.path.dirname(path)
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        html = fh.read()

    def _css(m):
        hm = _RE_HREF.search(m.group(0))
        if not hm:
            return m.group(0)
        data, _err = _read_share_file(hm.group(1), base_dir)
        if data is None:
            return m.group(0)
        css = data.decode('utf-8', 'replace').replace('</style', '<\\/style')
        return '<style>\n' + css + '\n</style>'

    def _js(m):
        pre, ref, post = m.group(1), m.group(2), m.group(3)
        data, _err = _read_share_file(ref, base_dir)
        if data is None:
            return m.group(0)
        typ = ' type="module"' if 'module' in (pre + post) else ''
        js = data.decode('utf-8', 'replace').replace('</script', '<\\/script')
        return '<script' + typ + '>\n' + js + '\n</script>'

    def _img(m):
        pre, ref = m.group(1), m.group(2)
        data, _err = _read_share_file(ref, base_dir)
        if data is None:
            return m.group(0)
        b = os.path.join(base_dir, ref) if not ref.startswith('/') else os.path.join(ROOT, ref.lstrip('/'))
        return pre + '"data:' + _guess_ctype(b) + ';base64,' + base64.b64encode(data).decode('ascii') + '"'

    html = _RE_CSS.sub(_css, html)
    html = _RE_JS.sub(_js, html)
    html = _RE_IMG.sub(_img, html)
    tm = _RE_TITLE.search(html)
    return (tm.group(1).strip() if tm else name), html.encode('utf-8')


def _slugify(title, name):
    def s(x):
        return re.sub(r'[^a-z0-9]+', '-', (x or '').lower()).strip('-')[:32].strip('-')
    fbase = s(re.sub(r'\.html?$', '', name.lower()))
    tbase = s(title)
    base = fbase if len(fbase) >= 4 else (tbase if len(tbase) >= 4 else (fbase or tbase or 'doc'))
    return f'{base}-{secrets.token_hex(3)}'


def _ingest(method, ep, body=None, timeout=20):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(
        INGEST_URL + ep, data=data, method=method,
        headers={'Content-Type': 'application/json', 'X-Airlock-Publish-Token': TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def publish_public(name, ttl_hours, owner):
    if not PUBLIC_ENABLED:
        return False, 'external publish not configured ([apps.publish.public_target])'
    path = safe_resolve(name)
    if not path or not os.path.lexists(path):
        return False, f'not found: {name}'
    if not name.lower().endswith(('.html', '.htm')):
        return False, 'only HTML pages can be published externally'
    try:
        title, html_bytes = bundle_single_file(name)
    except Exception as e:
        return False, f'bundle failed: {e}'
    # Reuse an existing slug for the same (owner, src) so re-publish keeps the URL.
    slug = None
    existing = public_list(owner)
    if existing.get('ok'):
        items = existing.get('items', [])
        slug = next((it['slug'] for it in items if it.get('src') == name and not it.get('expired')), None)
        if not slug:
            slug = next((it['slug'] for it in items if it.get('src') == name), None)
    if not slug:
        slug = _slugify(title, name)
    try:
        res = _ingest('POST', '/ingest', {
            'slug': slug, 'owner': owner or 'unknown', 'src': name, 'title': title,
            'ttl_hours': ttl_hours, 'html_b64': base64.b64encode(html_bytes).decode('ascii'),
        })
    except Exception as e:
        return False, f'ingest failed: {e}'
    if not res.get('ok'):
        return False, res.get('error', 'ingest error')
    r = res.get('result', {})
    return True, {'url': f'{BASE_URL}/{slug}/', 'slug': slug, 'expiry': r.get('expiry'), 'ttl_hours': r.get('ttl_hours')}


def public_list(owner):
    if not PUBLIC_ENABLED:
        return {'ok': False, 'error': 'external publish not configured'}
    ep = '/list' + (('?owner=' + urllib.parse.quote(owner)) if owner else '')
    try:
        d = _ingest('GET', ep, timeout=12)
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    for it in d.get('items', []):
        it['url'] = f'{BASE_URL}/{it["slug"]}/'
    return d


def public_revoke(slug, owner):
    if not PUBLIC_ENABLED:
        return {'ok': False, 'error': 'external publish not configured'}
    try:
        return _ingest('POST', '/revoke', {'slug': slug, 'owner': owner}, timeout=12)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def public_set_expiry(slug, owner, ttl_hours):
    if not PUBLIC_ENABLED:
        return {'ok': False, 'error': 'external publish not configured'}
    try:
        return _ingest('POST', '/set-expiry', {'slug': slug, 'owner': owner, 'ttl_hours': ttl_hours}, timeout=12)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ==== uploads — clipboard image / arbitrary file drop into ~/uploads ====
_RE_UPLOAD = re.compile(r'^image(\d{3,})-\d{8}-\d{6}\.jpg$')   # only auto-named files (protect manual ones)
UPLOAD_TTL_SEC = 24 * 3600
UPLOAD_MAX_BYTES = 12 * 1024 * 1024
FILE_MAX_BYTES = 50 * 1024 * 1024
_RE_FILE_SAFE = re.compile(r'[^0-9A-Za-z._ \-()]+')            # filename allowlist (blocks traversal/control chars)
_upload_lock = threading.Lock()


def cleanup_old_uploads():
    if not os.path.isdir(UPLOADS):
        return 0
    cutoff = time.time() - UPLOAD_TTL_SEC
    removed = 0
    for name in os.listdir(UPLOADS):
        full = os.path.join(UPLOADS, name)
        try:
            if os.path.isfile(full) and not os.path.islink(full) and os.path.getmtime(full) < cutoff:
                os.unlink(full)
                removed += 1
        except OSError:
            pass
    return removed


def _next_upload_seq():
    mx = 0
    if os.path.isdir(UPLOADS):
        for name in os.listdir(UPLOADS):
            m = _RE_UPLOAD.match(name)
            if m and os.path.isfile(os.path.join(UPLOADS, name)):
                mx = max(mx, int(m.group(1)))
    return mx + 1


def save_uploaded_image(image_b64):
    """base64 JPEG -> ~/uploads/imageNNN-<ts>.jpg. Server-generated name (no traversal)."""
    if not image_b64 or not isinstance(image_b64, str):
        return False, 'no image'
    if image_b64.startswith('data:'):
        comma = image_b64.find(',')
        if comma != -1:
            image_b64 = image_b64[comma + 1:]
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return False, 'invalid base64'
    if not raw:
        return False, 'empty image'
    if len(raw) > UPLOAD_MAX_BYTES:
        return False, f'image too large (>{UPLOAD_MAX_BYTES // (1024 * 1024)}MB)'
    if raw[:3] != b'\xff\xd8\xff':
        return False, 'not a jpeg'
    with _upload_lock:
        cleanup_old_uploads()
        os.makedirs(UPLOADS, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        n = _next_upload_seq()
        for _ in range(100):
            fname = f'image{n:03d}-{ts}.jpg'
            fpath = os.path.join(UPLOADS, fname)
            try:
                fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                n += 1
                continue
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            return True, {'name': fname, 'path': f'~/uploads/{fname}', 'n': n, 'bytes': len(raw)}
    return False, 'sequence exhausted'


def _safe_upload_name(name):
    base = os.path.basename(str(name or '').replace('\\', '/')).strip()
    base = _RE_FILE_SAFE.sub('_', base).lstrip('.').strip() or 'file'
    return base[:120]


def save_uploaded_file(filename, data_b64):
    """base64 arbitrary file -> ~/uploads/<name>. Kept (not auto-deleted by the
    imageNNN rule) but still swept by the 24h TTL cleanup."""
    if not data_b64 or not isinstance(data_b64, str):
        return False, 'no data'
    if data_b64.startswith('data:'):
        comma = data_b64.find(',')
        if comma != -1:
            data_b64 = data_b64[comma + 1:]
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        return False, 'invalid base64'
    if not raw:
        return False, 'empty file'
    if len(raw) > FILE_MAX_BYTES:
        return False, f'file too large (>{FILE_MAX_BYTES // (1024 * 1024)}MB)'
    safe = _safe_upload_name(filename)
    with _upload_lock:
        cleanup_old_uploads()
        os.makedirs(UPLOADS, exist_ok=True)
        stem, ext = os.path.splitext(safe)
        for i in range(1000):
            cand = safe if i == 0 else f'{stem}-{i + 1}{ext}'
            fpath = os.path.join(UPLOADS, cand)
            try:
                fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
            return True, {'name': cand, 'path': f'~/uploads/{cand}', 'bytes': len(raw)}
    return False, 'name collision exhausted'


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get('Content-Length', '0'))
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return {}

    def _strip(self, path):
        for prefix in ('/publish/', '/publish'):
            if path.startswith(prefix):
                path = path[len(prefix):]
                return path if path.startswith('/') else '/' + path
        return path

    def _owner(self):
        return self.headers.get(IDENTITY_HEADER, '')

    def do_GET(self):
        path = self._strip(urllib.parse.urlparse(self.path).path)
        if path in ('/api/list', '/list'):
            self._json(200, {'ok': True, 'items': list_items(), 'root': ROOT, 'public_enabled': PUBLIC_ENABLED})
            return
        if path in ('/api/health', '/health', '/'):
            self._json(200, {'ok': True, 'service': 'airlock-publish', 'port': PORT, 'public_enabled': PUBLIC_ENABLED})
            return
        if path in ('/api/public-list', '/public-list'):
            self._json(200, public_list(self._owner()))
            return
        if path in ('/api/uploads-cleanup', '/uploads-cleanup'):
            self._json(200, {'ok': True, 'removed': cleanup_old_uploads()})
            return
        self._json(404, {'ok': False, 'error': f'unknown path: {path}'})

    def do_POST(self):
        path = self._strip(urllib.parse.urlparse(self.path).path)
        body = self._read_body()
        if path in ('/api/unpublish', '/unpublish'):
            ok, msg = unpublish(body.get('name', ''))
            self._json(200 if ok else 400, {'ok': ok, 'name': body.get('name', ''), 'message': msg})
            return
        if path in ('/api/unpublish-direct', '/unpublish-direct'):
            ok, msg = unpublish_direct(body.get('name', ''), body.get('confirm_name', ''))
            self._json(200 if ok else 400, {'ok': ok, 'name': body.get('name', ''), 'message': msg})
            return
        if path in ('/api/unpublish-batch', '/unpublish-batch'):
            names = body.get('names', [])
            results = unpublish_batch(names if isinstance(names, list) else [], bool(body.get('include_direct', False)))
            self._json(200, {'ok': True, 'count': len(results), 'ok_count': sum(1 for r in results if r.get('ok')), 'results': results})
            return
        if path in ('/api/repair-broken', '/repair-broken'):
            results = repair_or_cleanup_all()
            self._json(200, {'ok': True, 'count': len(results), 'results': results})
            return
        if path in ('/api/publish-public', '/publish-public'):
            ok, res = publish_public(body.get('name', ''), body.get('ttl_hours'), self._owner())
            self._json(200 if ok else 400, {'ok': ok, 'result': res} if ok else {'ok': ok, 'error': res})
            return
        if path in ('/api/public-revoke', '/public-revoke'):
            self._json(200, public_revoke(body.get('slug', ''), self._owner()))
            return
        if path in ('/api/public-set-expiry', '/public-set-expiry'):
            self._json(200, public_set_expiry(body.get('slug', ''), self._owner(), body.get('ttl_hours')))
            return
        if path in ('/api/upload-image', '/upload-image'):
            ok, res = save_uploaded_image(body.get('image', ''))
            self._json(200 if ok else 400, {'ok': ok, **res} if ok else {'ok': ok, 'error': res})
            return
        if path in ('/api/upload-file', '/upload-file'):
            ok, res = save_uploaded_file(body.get('name', ''), body.get('data', ''))
            self._json(200 if ok else 400, {'ok': ok, **res} if ok else {'ok': ok, 'error': res})
            return
        self._json(404, {'ok': False, 'error': f'unknown path: {path}'})

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[airlock-publish] {self.address_string()} - {fmt % args}\n')


def main():
    if '--cleanup' in sys.argv:                    # systemd timer entry — TTL sweep without a page visit
        print(f'[airlock-publish] cleanup removed {cleanup_old_uploads()}', flush=True)
        return
    print(f'[airlock-publish] root={ROOT} uploads={UPLOADS} listen=127.0.0.1:{PORT} public={PUBLIC_ENABLED}', flush=True)
    with ThreadingHTTPServer(('127.0.0.1', PORT), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
