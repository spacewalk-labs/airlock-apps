#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$APP/../.." && pwd)"

bash -n "$APP/install.sh" "$APP/render.sh" "$APP/deactivate.sh" "$APP/smoke.sh"

unit="$(ROOT="$ROOT" bash -c '
  source "$1/render.sh"
  render_feedback_unit 18805 Tailscale-User-Login https://intake.example \
    INTAKE_SECRET feedback@example.test "Airlock Feedback <sender@example.test>" \
    https://mail.example MAIL_SECRET
' _ "$APP")"
grep -Fq 'After=network.target' <<<"$unit"
grep -Fq 'EnvironmentFile=-%h/.config/airlock-feedback.env' <<<"$unit"
grep -Fq 'Environment=AIRLOCK_FEEDBACK_TOKEN_ENV=INTAKE_SECRET' <<<"$unit"
grep -Fq 'Environment=AIRLOCK_FEEDBACK_MAIL_KEY_ENV=MAIL_SECRET' <<<"$unit"
grep -Fq 'Restart=on-failure' <<<"$unit"
[[ "$unit" != *'intake-secret-value'* ]]
[[ "$unit" != *'mail-secret-value'* ]]

nginx="$(bash -c 'source "$1/render.sh"; render_feedback_nginx 18805' _ "$APP")"
grep -Fq 'location /feedback/api/' <<<"$nginx"
grep -Fq 'proxy_pass http://127.0.0.1:18805;' <<<"$nginx"
grep -Fq 'proxy_set_header Host $host;' <<<"$nginx"

APP="$APP" \
AIRLOCK_FEEDBACK_INTAKE_URL=https://intake.example \
AIRLOCK_FEEDBACK_TOKEN_ENV=INTAKE_SECRET \
INTAKE_SECRET=intake-secret-value \
AIRLOCK_FEEDBACK_MAIL_TO=feedback@example.test \
AIRLOCK_FEEDBACK_MAIL_FROM='Airlock Feedback <sender@example.test>' \
AIRLOCK_FEEDBACK_MAIL_API=https://mail.example \
AIRLOCK_FEEDBACK_MAIL_KEY_ENV=MAIL_SECRET \
MAIL_SECRET=mail-secret-value \
python3 - <<'PY'
import importlib.util
import io
import json
import os
import pathlib
import tomllib
from unittest import mock

app = pathlib.Path(os.environ['APP'])
spec = importlib.util.spec_from_file_location(
    'airlock_feedback', app / 'backend' / 'airlock-feedback.py')
feedback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedback)

assert feedback.INTAKE_ENABLED
assert feedback.MAIL_ENABLED
assert feedback.FEEDBACK_ENABLED

# FB-A2: every malformed or invalid submit remains a JSON-shaped 400 result;
# no Python type error may escape the public request boundary.
def handler(body, owner='verified@example.test'):
    instance = object.__new__(feedback.Handler)
    instance.path = '/feedback/api/submit'
    instance.headers = {feedback.IDENTITY_HEADER: owner}
    instance._read_body = lambda: body
    instance.responses = []
    instance._json = lambda status, payload: instance.responses.append((status, payload))
    return instance

for body, error in (
        ([], 'request body must be a JSON object'),
        ({'text': 1}, 'text must be a string'),
        ({'text': {'nested': True}}, 'text must be a string'),
        ({'text': '   '}, 'empty message'),
        ({'text': 'x' * (feedback.TEXT_MAX + 1)},
         f'message too long (>{feedback.TEXT_MAX} chars)')):
    request = handler(body)
    feedback.Handler.do_POST(request)
    assert request.responses == [(400, {'ok': False, 'error': error})]

malformed_length = object.__new__(feedback.Handler)
malformed_length.headers = {'Content-Length': 'not-an-integer'}
malformed_length.rfile = io.BytesIO(b'{}')
assert feedback.Handler._read_body(malformed_length) is None

# Client-supplied owner is ignored. The identity-header owner and trimmed text
# are the only values handed to the delivery layer.
request = handler({'text': '  ship this  ', 'owner': 'attacker@example.test'})
with mock.patch.object(feedback, '_relay_intake',
                       return_value=(True, {'issue_url': 'https://issues.example/1'})) as intake, \
        mock.patch.object(feedback, '_send_mail', return_value=(True, None)) as mail:
    feedback.Handler.do_POST(request)
assert request.responses == [(200, {'ok': True, 'issue_url': 'https://issues.example/1'})]
intake.assert_called_once_with('ship this', 'verified@example.test')
mail.assert_called_once_with('ship this', 'verified@example.test')

# FB-A3: all configured targets must succeed. A partial delivery is an error,
# and the response contains neither configured secret value.
with mock.patch.object(feedback, '_relay_intake',
                       return_value=(True, {'issue_url': 'https://issues.example/2'})), \
        mock.patch.object(feedback, '_send_mail',
                          return_value=(False, 'send failed: RuntimeError')):
    ok, result = feedback.submit_feedback('partial', 'verified@example.test')
assert not ok and result == 'mail: send failed: RuntimeError'
assert feedback.TOKEN not in result and feedback.MAIL_KEY not in result

# The intake target receives only server-derived owner/text and its dedicated
# token header. The client response exposes only the target's issue URL.
response = mock.MagicMock()
response.__enter__.return_value = response
response.read.return_value = json.dumps(
    {'ok': True, 'issue_url': 'https://issues.example/3'}).encode()
with mock.patch.object(feedback.urllib.request, 'urlopen', return_value=response) as urlopen:
    ok, result = feedback._relay_intake('hello', 'verified@example.test')
assert ok and result == {'issue_url': 'https://issues.example/3'}
sent = urlopen.call_args.args[0]
assert json.loads(sent.data) == {'owner': 'verified@example.test', 'text': 'hello'}
assert sent.get_header('X-airlock-feedback-token') == feedback.TOKEN

# A target returning valid JSON of the wrong shape is a delivery failure, not
# an AttributeError escaping the public request handler.
for payload in ([], True, 123, None):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(payload).encode()
    with mock.patch.object(feedback.urllib.request, 'urlopen', return_value=response):
        ok, error = feedback._relay_intake('hello', 'verified@example.test')
    assert not ok and error == 'invalid intake response'

# Mail provider failures are reduced to their exception class: neither the
# provider body nor the API key can cross back into the public response.
with mock.patch.object(feedback.urllib.request, 'urlopen',
                       side_effect=RuntimeError(
                           f'provider echoed key={feedback.MAIL_KEY} and request body')):
    ok, error = feedback._send_mail('hello', 'verified@example.test')
assert not ok and error == 'send failed: RuntimeError'
assert feedback.MAIL_KEY not in error and 'request body' not in error

# FB-C1/C2: package config stores env-var names, not values. The optional
# EnvironmentFile is the only secret-value boundary rendered into the unit.
manifest = tomllib.loads((app / 'airlock-app.toml').read_text())
defaults = manifest['config']['defaults']
assert defaults == {
    'backend_port': 18805,
    'intake_url': 'https://your-intake.example',
    'token_env': 'AIRLOCK_FEEDBACK_TOKEN',
    'mail_to': '',
    'mail_from': '',
    'mail_api': '',
    'mail_key_env': 'RESEND_API_KEY',
}
assert manifest['config']['runtime_env'] == ['AIRLOCK_FEEDBACK_TOKEN']
assert manifest['artifacts'] == {
    'units': ['airlock-feedback.service'],
    'fragments': ['hub-locations.d/feedback.conf'],
}
source = (app / 'airlock-app.toml').read_text()
assert feedback.TOKEN not in source and feedback.MAIL_KEY not in source

print('ok: feedback API, delivery, identity, unit, route, and secret-boundary contracts')
PY

echo 'ok: feedback parity (FB-R1/A1/A2/A3/N1/C1/C2)'
