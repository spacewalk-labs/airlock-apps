#!/usr/bin/env python3
"""airlock-feedback — a suggestion-box relay to a PLUGGABLE external intake.

Runs on loopback (127.0.0.1:<backend_port>); the hub nginx proxies /feedback/api/
here. The hub's suggestion box POSTs {text}; this backend attaches the owner
SERVER-SIDE from the gate-verified identity header (never a client field) and
forwards {owner, text} to a configured external intake endpoint, which creates a
tracking item (e.g. a GitHub issue) and returns its URL. It never parses
airlock.toml itself — the installer passes everything via the environment.

The intake is a PLUGGABLE target: if AIRLOCK_FEEDBACK_INTAKE_URL + a token are
configured, submissions are forwarded; otherwise the box degrades cleanly (submit
reports "not configured"). The token is delivered via an EnvironmentFile whose var
NAME is configured (the secret stays out of airlock.toml).

Intake protocol (what a target must implement) — JSON over HTTPS, the token in
the `X-Airlock-Feedback-Token` header:
  POST <intake>/submit   {owner, text}  ->  {ok, issue_url}
`owner` is the gate-verified login of the submitter; the target decides how it
records the suggestion (this backend just relays and returns `issue_url`).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get('AIRLOCK_FEEDBACK_BACKEND_PORT', '18805'))
IDENTITY_HEADER = os.environ.get('AIRLOCK_IDENTITY_HEADER', 'Tailscale-User-Login')

# ---- pluggable external intake target (all optional) ----
INTAKE_URL = os.environ.get('AIRLOCK_FEEDBACK_INTAKE_URL', '').rstrip('/')
# The token lives in an env var whose NAME is configured (secret stays out of the
# config file); default AIRLOCK_FEEDBACK_TOKEN. The installer wires an EnvironmentFile.
_TOKEN_ENV = os.environ.get('AIRLOCK_FEEDBACK_TOKEN_ENV', 'AIRLOCK_FEEDBACK_TOKEN')
TOKEN = os.environ.get(_TOKEN_ENV, '')
FEEDBACK_ENABLED = bool(INTAKE_URL and TOKEN)

TEXT_MAX = 8000   # generous cap; the intake may clamp further


def submit_feedback(text, owner):
    """Forward {owner, text} to the external intake, returning (ok, result)."""
    if not FEEDBACK_ENABLED:
        return False, 'feedback intake not configured ([apps.feedback])'
    text = (text or '').strip()
    if not text:
        return False, 'empty message'
    if len(text) > TEXT_MAX:
        return False, f'message too long (>{TEXT_MAX} chars)'
    body = json.dumps({'owner': owner or 'unknown', 'text': text}).encode('utf-8')
    req = urllib.request.Request(
        INTAKE_URL + '/submit', data=body, method='POST',
        headers={'Content-Type': 'application/json',
                 'X-Airlock-Feedback-Token': TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return False, f'intake unreachable: {e}'
    if not res.get('ok'):
        return False, res.get('error', 'intake error')
    return True, {'issue_url': res.get('issue_url')}


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
        for prefix in ('/feedback/', '/feedback'):
            if path.startswith(prefix):
                path = path[len(prefix):]
                return path if path.startswith('/') else '/' + path
        return path

    def _owner(self):
        # The gate-verified identity, injected by the hub nginx (tailscale serve
        # strips any client-supplied copy). NEVER trust a client-sent owner field.
        return self.headers.get(IDENTITY_HEADER, '')

    def do_GET(self):
        path = self._strip(urllib.parse.urlparse(self.path).path)
        if path in ('/api/health', '/health', '/'):
            self._json(200, {'ok': True, 'service': 'airlock-feedback',
                             'port': PORT, 'enabled': FEEDBACK_ENABLED})
            return
        self._json(404, {'ok': False, 'error': f'unknown path: {path}'})

    def do_POST(self):
        path = self._strip(urllib.parse.urlparse(self.path).path)
        body = self._read_body()
        if path in ('/api/submit', '/submit'):
            ok, res = submit_feedback(body.get('text', ''), self._owner())
            self._json(200 if ok else 400,
                       {'ok': ok, **res} if ok else {'ok': ok, 'error': res})
            return
        self._json(404, {'ok': False, 'error': f'unknown path: {path}'})

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[airlock-feedback] {self.address_string()} - {fmt % args}\n')


def main():
    print(f'[airlock-feedback] listen=127.0.0.1:{PORT} enabled={FEEDBACK_ENABLED}', flush=True)
    with ThreadingHTTPServer(('127.0.0.1', PORT), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
