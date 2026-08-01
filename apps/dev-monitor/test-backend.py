#!/usr/bin/env python3
"""Offline checks for the dev-monitor BACKEND — the half test_devmon.py does not reach.

test_devmon.py covers the ported store/spool/owner/slack modules. This covers what the
backend itself adds on top of them: which origins may read a response, what the health
endpoint admits to, and the reaper paths that exist to stop a failed launch from locking
a card forever. Those are exactly the places a bug is invisible until someone is stuck.

    python3 apps/dev-monitor/test-backend.py

No install, no network, no tmux required.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, 'backend')
sys.path.insert(0, BACKEND)


def _load_backend():
    """The backend's filename has a hyphen, so it cannot be imported by name."""
    spec = importlib.util.spec_from_file_location(
        'airlock_dev_monitor', os.path.join(BACKEND, 'airlock-dev-monitor.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DM = _load_backend()
MSG = DM.MSG


class _FakeHandler(DM.Handler):
    """A Handler with just enough of one to answer _cors_origin, and no socket."""

    def __init__(self, origin=None):
        self.headers = {} if origin is None else {'Origin': origin}


class CorsTest(unittest.TestCase):
    """Identity here is injected by the ingress, so an echoed origin can read owner data
    with the owner's authority. The comparison must be against a whole hostname."""

    def setUp(self):
        self._saved = DM.CORS_HOSTS
        DM.CORS_HOSTS = frozenset({'box', 'box.tailnet.example'})

    def tearDown(self):
        DM.CORS_HOSTS = self._saved

    def _origin(self, value):
        return _FakeHandler(value)._cors_origin()

    def test_same_box_any_port_is_echoed(self):
        self.assertEqual(self._origin('https://box.tailnet.example:8443'),
                         'https://box.tailnet.example:8443')
        self.assertEqual(self._origin('http://box:9900'), 'http://box:9900')

    def test_case_is_not_a_boundary(self):
        self.assertEqual(self._origin('https://BOX.Tailnet.Example'), 'https://BOX.Tailnet.Example')

    def test_no_origin_is_not_echoed(self):
        self.assertIsNone(self._origin(None))

    def test_prefix_lookalike_is_refused(self):
        # The bug this test exists for: comparing only the first label let any domain whose
        # first label happened to match the box read the owner's messages.
        self.assertIsNone(self._origin('https://box.attacker.example'))
        self.assertIsNone(self._origin('https://box.tailnet.example.attacker.example'))

    def test_other_node_on_the_same_tailnet_is_refused(self):
        # Tailnet domains are public suffixes, so "same site" is not a boundary here.
        self.assertIsNone(self._origin('https://other.tailnet.example'))

    def test_suffix_lookalike_is_refused(self):
        self.assertIsNone(self._origin('https://notbox.tailnet.example'))
        self.assertIsNone(self._origin('https://evil-box'))

    def test_garbage_origin_is_refused(self):
        for bad in ('', 'null', 'https://', '://x', 'https://[', 'file:///etc/passwd'):
            self.assertIsNone(self._origin(bad), bad)


class MessagesStateTest(unittest.TestCase):
    """The banner and /api/health must report what started, never what was requested."""

    def setUp(self):
        self._saved = DM.OWNER_CONFIG

    def tearDown(self):
        DM.OWNER_CONFIG = self._saved

    def test_off_without_a_loaded_config(self):
        DM.OWNER_CONFIG = None
        self.assertEqual(DM._messages_state(), 'off')

    def test_on_once_the_config_is_loaded(self):
        DM.OWNER_CONFIG = {'owner': 'me@example.test', 'secret': 's', 'spool': '/x', 'db': '/y'}
        self.assertEqual(DM._messages_state(), 'on')


class TmuxProbeTest(unittest.TestCase):
    """A box with no tmux must be distinguishable from a session that is simply absent."""

    def test_missing_binary_is_unknown_not_absent(self):
        saved = DM.subprocess.call
        try:
            DM.subprocess.call = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError('tmux'))
            self.assertIsNone(DM._tmux_has_session('anything'))
        finally:
            DM.subprocess.call = saved

    def test_exit_one_means_definitely_absent(self):
        saved = DM.subprocess.call
        try:
            DM.subprocess.call = lambda *a, **k: 1
            self.assertEqual(DM._tmux_has_session('anything'), 1)
        finally:
            DM.subprocess.call = saved

    def test_alive_keys_are_unknown_when_tmux_is_unreachable(self):
        # None here means "do not reap"; an empty set would mean "reap everything".
        saved_tmux, saved_call = DM._tmux, DM.subprocess.call
        try:
            DM._tmux = lambda *a, **k: None
            DM.subprocess.call = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError('tmux'))
            self.assertIsNone(DM._exec_alive_keys('devmon-exec'))
        finally:
            DM._tmux, DM.subprocess.call = saved_tmux, saved_call


class _ExecBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.cwd = os.path.join(root, 'project')
        os.makedirs(self.cwd)
        MSG.init_db(os.path.join(root, 'messages.db'))
        self._saved_exec, self._saved_owner = DM.EXEC_CONFIG, DM.OWNER_CONFIG
        DM.EXEC_CONFIG = {
            'cwd_root': root,
            'skill_allow': None,
            'session': 'devmon-test',
            'runner': os.path.join(BACKEND, 'action_runner.py'),
            'plan_dir': os.path.join(root, 'plans'),
            'sentinel_dir': os.path.join(root, 'sentinels'),
        }
        for key in ('plan_dir', 'sentinel_dir'):
            os.makedirs(DM.EXEC_CONFIG[key], exist_ok=True)
        DM.OWNER_CONFIG = {'owner': 'me@example.test', 'secret': 's',
                           'spool': root, 'db': os.path.join(root, 'messages.db')}

    def tearDown(self):
        DM.EXEC_CONFIG, DM.OWNER_CONFIG = self._saved_exec, self._saved_owner
        MSG._local.__dict__.clear()
        MSG._DB_PATH = None
        self.tmp.cleanup()

    def _approved_run(self, age_seconds=0):
        """An action card taken all the way to a run row in 'starting' with no window."""
        MSG.ingest({
            'schema_version': 1, 'event_id': 'e%d' % age_seconds, 'group_key': 'g%d' % age_seconds,
            'source': 'test', 'kind': 'action', 'urgency': 'normal', 'title': 'Do the thing',
            'created_at': MSG.iso(MSG.now_utc()),
            'recommended_action': {'cwd': self.cwd, 'prompt': 'do it', 'explain': 'because'},
        })
        card_id = MSG.feed('active')['messages'][0]['card_id']
        appr = MSG.issue_approval(card_id, DM.EXEC_CONFIG)
        run_id = MSG.redeem_approval(card_id, appr['nonce'], DM.EXEC_CONFIG)['run_id']
        if age_seconds:
            old = MSG.iso(datetime.now(timezone.utc) - timedelta(seconds=age_seconds))
            conn = MSG._conn()
            conn.execute('UPDATE runs SET created_at=? WHERE run_id=?', (old, run_id))
            conn.commit()
        return card_id, run_id


class StuckLaunchTest(_ExecBase):
    """devmon_messages deliberately leaves a targetless run alone, which is right — but it
    left no way out at all. These pin the escape: proof of no window, never a bare timeout."""

    def _reap(self, live_names, session_present=True):
        saved_tmux, saved_has = DM._tmux, DM._tmux_has_session
        try:
            DM._tmux = lambda *a, **k: ('\n'.join(live_names) if live_names is not None else None)
            DM._tmux_has_session = lambda name: (0 if session_present else 1)
            DM._reap_stuck_starting(DM.EXEC_CONFIG['session'])
        finally:
            DM._tmux, DM._tmux_has_session = saved_tmux, saved_has

    def test_stuck_run_is_released_once_its_window_is_provably_absent(self):
        card_id, run_id = self._approved_run(age_seconds=DM.STARTING_GRACE_S + 60)
        self._reap(live_names=[])
        self.assertNotEqual(MSG.get_run(run_id)['status'], 'starting')
        # The card lock is what the owner actually feels: it must be gone. Look the card up
        # BY ID — terminating a run ingests a result card that sorts first, and a brand new
        # card's run_id is always NULL, so asserting on messages[0] passes unconditionally.
        card = [m for m in MSG.feed('active')['messages'] if m['card_id'] == card_id]
        self.assertEqual(len(card), 1)
        self.assertIsNone(card[0]['run_id'])

    def test_a_young_run_is_left_alone(self):
        # Still inside the grace period: the launch may be mid-flight under the tmux lock.
        card_id, run_id = self._approved_run(age_seconds=0)
        self._reap(live_names=[])
        self.assertEqual(MSG.get_run(run_id)['status'], 'starting')

    def test_a_run_whose_window_exists_is_left_alone(self):
        card_id, run_id = self._approved_run(age_seconds=DM.STARTING_GRACE_S + 60)
        self._reap(live_names=[MSG.run_window_name(run_id)])
        self.assertEqual(MSG.get_run(run_id)['status'], 'starting')

    def test_unreachable_tmux_reaps_nothing(self):
        # Knowing nothing must never be read as "nothing is running" — that would end a
        # live run and unlock its card, permitting a second execution.
        card_id, run_id = self._approved_run(age_seconds=DM.STARTING_GRACE_S + 60)
        self._reap(live_names=None, session_present=True)
        self.assertEqual(MSG.get_run(run_id)['status'], 'starting')


class PlanFileTest(_ExecBase):
    """The plan file holds the approved cwd and prompt. devmon_messages drops the same
    content from `approvals` after a day; leaving a copy on disk forever undoes that."""

    def _plan_path(self, run_id):
        return os.path.join(DM.EXEC_CONFIG['plan_dir'], run_id + '.json')

    def test_plan_of_a_finished_run_is_deleted(self):
        card_id, run_id = self._approved_run()
        with open(self._plan_path(run_id), 'w') as fh:
            fh.write(json.dumps({'cwd': self.cwd}))
        MSG.run_mark_running(run_id, '1:@1')
        MSG.run_finish(run_id, 0)
        DM._reap_plan_files()
        self.assertFalse(os.path.exists(self._plan_path(run_id)))

    def test_plan_of_a_live_run_is_kept(self):
        card_id, run_id = self._approved_run()
        with open(self._plan_path(run_id), 'w') as fh:
            fh.write(json.dumps({'cwd': self.cwd}))
        MSG.run_mark_running(run_id, '1:@1')
        DM._reap_plan_files()
        self.assertTrue(os.path.exists(self._plan_path(run_id)))

    def test_foreign_files_are_left_alone(self):
        stray = os.path.join(DM.EXEC_CONFIG['plan_dir'], 'notes.txt')
        with open(stray, 'w') as fh:
            fh.write('not ours')
        DM._reap_plan_files()
        self.assertTrue(os.path.exists(stray))


class LaunchWithoutTmuxTest(_ExecBase):
    """No tmux is a definite answer, not an ambiguous one: nothing started, so the card
    must unlock. Reporting it as ambiguous is what left cards stuck forever."""

    def test_missing_tmux_reports_nowindow_and_writes_no_plan(self):
        saved = DM.shutil.which
        try:
            DM.shutil.which = lambda name: None
            outcome, target = DM._launch_run('run-x', {'cwd': self.cwd, 'prompt': 'p', 'explain': 'e'})
        finally:
            DM.shutil.which = saved
        self.assertEqual((outcome, target), ('nowindow', None))
        self.assertEqual(os.listdir(DM.EXEC_CONFIG['plan_dir']), [])



class ManyRunsTest(_ExecBase):
    """Both reapers used list_runs(), which pages at 50. A stuck run is by definition an
    old one, so the escape hatch vanished as soon as the box had 50 newer runs — and the
    plan cleanup started deleting the plan files of runs that were still alive."""

    def _bulk_runs(self, n):
        """n finished runs, so the one run we care about is off the first page."""
        conn = MSG._conn()
        for i in range(n):
            conn.execute(
                'INSERT INTO runs(run_id, card_id, plan_sha256, plan_json, status, created_at, ended_at) '
                'VALUES(?,?,?,?,?,?,?)',
                ('run-filler-%03d' % i, 'c%d' % i, 'sha', '{}', 'done',
                 MSG.iso(MSG.now_utc()), MSG.iso(MSG.now_utc())))
        conn.commit()

    def test_stuck_run_is_still_found_behind_fifty_newer_runs(self):
        card_id, run_id = self._approved_run(age_seconds=DM.STARTING_GRACE_S + 60)
        self._bulk_runs(60)
        saved_tmux, saved_has = DM._tmux, DM._tmux_has_session
        try:
            DM._tmux = lambda *a, **k: ''
            DM._tmux_has_session = lambda name: 0
            DM._reap_stuck_starting(DM.EXEC_CONFIG['session'])
        finally:
            DM._tmux, DM._tmux_has_session = saved_tmux, saved_has
        self.assertNotEqual(MSG.get_run(run_id)['status'], 'starting')

    def test_plan_file_of_a_live_run_survives_behind_fifty_newer_runs(self):
        card_id, run_id = self._approved_run()
        MSG.run_mark_running(run_id, '1:@1')
        path = os.path.join(DM.EXEC_CONFIG['plan_dir'], run_id + '.json')
        with open(path, 'w') as fh:
            fh.write('{}')
        self._bulk_runs(60)
        DM._reap_plan_files()
        # Deleting this would make the runner fail to open its own plan: the approved
        # action reports failed having never run.
        self.assertTrue(os.path.exists(path))


class ExecRootTest(_ExecBase):
    """A systemd EnvironmentFile writes an empty value for an unset key, and canonical_plan
    reads a falsy root as 'no bound at all' — so DEV_MONITOR_CWD_ROOT= removed the boundary."""

    def _cwd_root(self, value):
        saved = os.environ.get('DEV_MONITOR_CWD_ROOT')
        try:
            if value is None:
                os.environ.pop('DEV_MONITOR_CWD_ROOT', None)
            else:
                os.environ['DEV_MONITOR_CWD_ROOT'] = value
            return DM._build_exec_config()['cwd_root']
        finally:
            if saved is None:
                os.environ.pop('DEV_MONITOR_CWD_ROOT', None)
            else:
                os.environ['DEV_MONITOR_CWD_ROOT'] = saved

    def test_empty_falls_back_to_home_rather_than_no_bound(self):
        self.assertEqual(self._cwd_root(''), DM.HOME)

    def test_unset_falls_back_to_home(self):
        self.assertEqual(self._cwd_root(None), DM.HOME)

    def test_a_real_value_is_honoured(self):
        self.assertEqual(self._cwd_root('/srv/projects'), '/srv/projects')


class ApprovalSiblingTest(_ExecBase):
    """One click approves ONE execution. A preview opened and cancelled must not leave a
    second capability alive, redeemable with no further click once the first run ends."""

    def test_redeeming_one_nonce_burns_the_card_s_other_approvals(self):
        MSG.ingest({
            'schema_version': 1, 'event_id': 'sib', 'group_key': 'sib', 'source': 'test',
            'kind': 'action', 'urgency': 'normal', 'title': 'Do it',
            'created_at': MSG.iso(MSG.now_utc()),
            'recommended_action': {'cwd': self.cwd, 'prompt': 'p', 'explain': 'e'},
        })
        card_id = MSG.feed('active')['messages'][0]['card_id']
        first = MSG.issue_approval(card_id, DM.EXEC_CONFIG)['nonce']
        second = MSG.issue_approval(card_id, DM.EXEC_CONFIG)['nonce']
        run_id = MSG.redeem_approval(card_id, second, DM.EXEC_CONFIG)['run_id']
        MSG.run_mark_running(run_id, '1:@1')
        MSG.run_finish(run_id, 0)
        self.assertEqual(MSG.redeem_approval(card_id, first, DM.EXEC_CONFIG),
                         {'ok': False, 'error': 'nonce_used'})


class OwnerRouteTest(unittest.TestCase):
    """Drives the real HTTP handler. This is the layer the module tests never reach — and
    it is where card ids arrive percent-encoded by the browser."""

    @classmethod
    def setUpClass(cls):
        import http.server, threading
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        cls.cwd = os.path.join(root, 'project')
        os.makedirs(cls.cwd)
        MSG.init_db(os.path.join(root, 'messages.db'))
        DM.OWNER_CONFIG = {'owner': 'me@example.test', 'secret': 's3cr3t',
                           'spool': root, 'db': os.path.join(root, 'messages.db')}
        DM.EXEC_CONFIG = {
            'cwd_root': root, 'skill_allow': None, 'session': 'devmon-test',
            'runner': os.path.join(BACKEND, 'action_runner.py'),
            'plan_dir': os.path.join(root, 'plans'), 'sentinel_dir': os.path.join(root, 'sentinels'),
        }
        for key in ('plan_dir', 'sentinel_dir'):
            os.makedirs(DM.EXEC_CONFIG[key], exist_ok=True)
        # An event_id shaped exactly like the one the shipped producer generates: it
        # contains colons, which encodeURIComponent turns into %3A.
        cls.card_id = 'disk-2026-08-01T01:20:37Z-299b'
        MSG.ingest({
            'schema_version': 1, 'event_id': cls.card_id, 'group_key': 'disk:cleanup',
            'source': 'disk', 'kind': 'action', 'urgency': 'normal', 'title': 'Clean up',
            'created_at': MSG.iso(MSG.now_utc()),
            'recommended_action': {'cwd': cls.cwd, 'prompt': 'clean', 'explain': 'disk is full'},
        })
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), DM.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        DM.OWNER_CONFIG = None
        DM.EXEC_CONFIG = None
        MSG._local.__dict__.clear()
        MSG._DB_PATH = None
        cls.tmp.cleanup()

    def _post(self, path, body=b'{}', headers=None, origin=True):
        import http.client
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'X-Devmon-Owner': 'me@example.test', 'X-Devmon-Proxy-Secret': 's3cr3t',
             'Content-Type': 'application/json'}
        if origin:
            h['Origin'] = 'http://127.0.0.1:%d' % self.port
        h.update(headers or {})
        conn.request('POST', path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, json.loads(data or b'{}')

    def test_percent_encoded_card_id_reaches_the_card(self):
        # What the browser actually sends. Before the fix this answered 404/card_not_found
        # for every card the shipped producer creates, so nothing could be read or run.
        import urllib.parse as up
        quoted = up.quote(self.card_id, safe='')
        self.assertIn('%3A', quoted)
        status, payload = self._post('/api/owner/messages/%s/plan' % quoted)
        self.assertEqual((status, payload.get('ok')), (200, True), payload)
        self.assertIn('nonce', payload)

    def test_percent_encoded_card_id_also_works_for_read(self):
        import urllib.parse as up
        status, payload = self._post('/api/owner/messages/%s/read' % up.quote(self.card_id, safe=''))
        self.assertEqual((status, payload.get('ok')), (200, True), payload)

    def test_a_wrong_secret_is_refused(self):
        status, _ = self._post('/api/owner/messages/x/read', headers={'X-Devmon-Proxy-Secret': 'nope'})
        self.assertEqual(status, 403)

    def test_a_non_ascii_header_is_refused_not_crashed(self):
        # http.server decodes headers as latin-1 and hmac.compare_digest refuses non-ASCII
        # str, so this used to raise pre-auth and reset the connection.
        status, _ = self._post('/api/owner/messages/x/read',
                               headers={'X-Devmon-Owner': 'caf\u00e9'.encode('utf-8').decode('latin-1')})
        self.assertEqual(status, 403)

    def test_a_cross_origin_post_is_refused(self):
        status, _ = self._post('/api/owner/messages/x/read',
                               headers={'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main(verbosity=1)
