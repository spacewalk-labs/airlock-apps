#!/usr/bin/env python3
"""devmon_messages — persistent state for the Dev Monitor message axis (SQLite).

The key split is occurrence (an immutable receipt ledger) versus card (a mutable projection),
so deduplication, crash recovery, coalescing and flood accounting all happen in one atomic
transaction. apps/dev-monitor/README.md explains why that split exists.

This module uses stdlib sqlite3 only. airlock-dev-monitor.py imports it in one process with
multiple threads.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# ---- constants / validation ----
ID_RE = re.compile(r'^[A-Za-z0-9._:-]{1,128}\Z')      # event_id/group_key/source
SKILL_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}\Z')  # skill name (installed-skill format)
MAX_PAYLOAD = 16 * 1024                                # 16KB
MAX_URL = 2048                                         # upper bound for link.url
APPROVAL_TTL = timedelta(minutes=5)                   # approval nonce lifetime
COALESCE_WINDOW = timedelta(hours=24)                 # one card per group_key in 24h (per day)
FLOOD_WINDOW = timedelta(minutes=10)
FLOOD_THRESHOLD = 20
FLOOD_COOLDOWN = timedelta(minutes=30)
ARCHIVE_IDLE = timedelta(hours=48)
ARCHIVE_ACTIVE_MIN = 20
RETENTION = timedelta(days=180)
FUTURE_SKEW = timedelta(minutes=5)

_local = threading.local()
_DB_PATH = None


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def parse_rfc3339(s):
    """Accept timezone-aware RFC3339 only. Raises ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError('created_at not a string')
    txt = s.strip()
    if txt.endswith('Z'):
        txt = txt[:-1] + '+00:00'
    dt = datetime.fromisoformat(txt)          # no offset means tz-naive
    if dt.tzinfo is None:
        raise ValueError('created_at must be timezone-aware')
    return dt.astimezone(timezone.utc)


def action_digest(payload):
    """Canonical hash of kind + recommended_action + link, used to decide card identity.

    Different link URLs have different digests, so they become different cards even when they
    have the same group_key (they coalesce per URL).
    """
    material = {
        'kind': payload.get('kind'),
        'action': payload.get('recommended_action'),
        'link': payload.get('link'),
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


class ValidationError(ValueError):
    pass


def validate_link_url(url):
    """Accept only absolute http/https URLs for link.url (a host is required). Reject every
    other form: javascript:, data:, file:, relative and protocol-relative. The frontend checks
    again immediately before clicking as defense in depth. Returns the accepted value unchanged."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL:
        raise ValidationError('invalid link url')
    u = urlparse(url.strip())
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise ValidationError('link url must be http(s) with host')  # hostname rather than netloc rejects ":443", etc.
    return url.strip()


def validate_payload(payload):
    """Validate producer JSON. Failure raises ValidationError with the reason; success returns
    a normalised dict."""
    if not isinstance(payload, dict):
        raise ValidationError('payload not an object')
    sv = payload.get('schema_version')
    if type(sv) is not int or sv != 1:        # reject bool True even though Python has True == 1
        raise ValidationError('unsupported schema_version')
    for f in ('event_id', 'group_key', 'source'):
        v = payload.get(f)
        if not isinstance(v, str) or not ID_RE.match(v):
            raise ValidationError(f'invalid {f}')
    kind = payload.get('kind')
    if kind not in ('action', 'info', 'link'):
        raise ValidationError('invalid kind')
    urgency = payload.get('urgency')
    if urgency not in ('urgent', 'normal'):
        raise ValidationError('invalid urgency')
    if not isinstance(payload.get('title'), str) or not payload['title'].strip():
        raise ValidationError('missing title')
    try:
        created = parse_rfc3339(payload.get('created_at'))
    except ValueError as e:
        raise ValidationError('invalid created_at: %s' % e)
    if created > now_utc() + FUTURE_SKEW:
        raise ValidationError('created_at too far in future')
    if kind == 'action':
        ra = payload.get('recommended_action')
        if not isinstance(ra, dict):
            raise ValidationError('action requires recommended_action')
        has_skill = bool(isinstance(ra.get('skill'), str) and ra['skill'].strip())
        has_prompt = bool(isinstance(ra.get('prompt'), str) and ra['prompt'].strip())
        has_exec = bool(isinstance(ra.get('exec'), list) and ra['exec'])   # direct executable
        if (has_skill + has_prompt + has_exec) != 1:      # exactly one
            raise ValidationError('recommended_action needs exactly one of skill|prompt|exec')
        if has_skill and not SKILL_RE.match(ra['skill'].strip()):
            raise ValidationError('invalid skill name')
        if has_exec and not all(isinstance(x, str) and x for x in ra['exec']):
            raise ValidationError('exec must be a non-empty list of non-empty strings')
        if not isinstance(ra.get('cwd'), str) or not ra['cwd']:
            raise ValidationError('action requires cwd')
        if not isinstance(ra.get('explain'), str) or not ra['explain'].strip():
            raise ValidationError('action requires explain')
        if urgency == 'urgent' and not (has_skill or has_prompt or has_exec):
            raise ValidationError('urgent action without recommended_action')
    elif kind == 'link':
        ln = payload.get('link')
        if not isinstance(ln, dict):
            raise ValidationError('link requires link object')
        validate_link_url(ln.get('url'))          # http(s) host is required; every other form is rejected
        label = ln.get('label')
        if label is not None and (not isinstance(label, str) or len(label) > 200):
            raise ValidationError('link label must be a short string')
    else:  # info
        for f in ('outcome', 'why_it_matters', 'followup'):
            if not isinstance(payload.get(f), str) or not payload[f].strip():
                raise ValidationError(f'info requires {f}')
    return {'created_at': created}


# ---- connection ----
def init_db(path):
    """Call once before threads are created. Initialise the schema and WAL."""
    global _DB_PATH
    _DB_PATH = path
    # 0700 explicitly, and re-applied: makedirs honours the umask, and exist_ok=True means
    # an existing directory keeps whatever mode it already had. The installer sets this up
    # correctly, but the backend recreates it whenever someone clears the state directory,
    # and the WAL/SHM files beside the DB are readable to anyone who can enter it.
    state_dir = os.path.dirname(path)
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(path)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.executescript(_SCHEMA)
        _ensure_run_lifecycle_columns(conn)
        conn.commit()
    finally:
        conn.close()
    # DB file mode 0600 (collector only).
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ensure_run_lifecycle_columns(conn):
    """Apply the run-lifecycle columns to databases created before retention existed."""
    columns = {row[1] for row in conn.execute('PRAGMA table_info(runs)').fetchall()}
    additions = (
        ('keep_requested', 'INTEGER NOT NULL DEFAULT 0'),
        ('kept_at', 'TEXT'),
        ('reclaimed_at', 'TEXT'),
    )
    for name, definition in additions:
        if name not in columns:
            conn.execute('ALTER TABLE runs ADD COLUMN %s %s' % (name, definition))


def _conn():
    c = getattr(_local, 'conn', None)
    if c is None:
        if _DB_PATH is None:
            raise RuntimeError('init_db() not called')
        c = sqlite3.connect(_DB_PATH, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA busy_timeout=5000')
        c.execute('PRAGMA foreign_keys=ON')
        _local.conn = c
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS occurrences (
  event_id     TEXT PRIMARY KEY,
  card_id      TEXT NOT NULL,
  group_key    TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  received_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_occ_flood ON occurrences(group_key, received_at);
CREATE INDEX IF NOT EXISTS idx_occ_card  ON occurrences(card_id);

CREATE TABLE IF NOT EXISTS cards (
  card_id     TEXT PRIMARY KEY,
  group_key   TEXT NOT NULL,
  source      TEXT NOT NULL,
  kind        TEXT NOT NULL,
  urgency     TEXT NOT NULL,
  title       TEXT NOT NULL,
  body        TEXT,
  action_json TEXT,
  link_json   TEXT,
  action_digest TEXT,
  created_at  TEXT NOT NULL,
  received_at TEXT NOT NULL,
  read_at     TEXT,
  slack_sent_at TEXT,
  pinned      INTEGER NOT NULL DEFAULT 0,
  archived_at TEXT,
  dismissed_at TEXT,
  occurrence_count INTEGER NOT NULL DEFAULT 1,
  last_seen   TEXT NOT NULL,
  run_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_group_open ON cards(group_key)
  WHERE dismissed_at IS NULL AND archived_at IS NULL;

CREATE TABLE IF NOT EXISTS runs (
  run_id      TEXT PRIMARY KEY,
  card_id     TEXT NOT NULL,
  plan_sha256 TEXT NOT NULL,
  plan_json   TEXT NOT NULL,
  status      TEXT NOT NULL,
  tmux_target TEXT,
  exit_code   INTEGER,
  error       TEXT,
  created_at  TEXT NOT NULL,
  started_at  TEXT,
  ended_at    TEXT,
  keep_requested INTEGER NOT NULL DEFAULT 0,
  kept_at     TEXT,
  reclaimed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_card ON runs(card_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS approvals (
  nonce       TEXT PRIMARY KEY,
  card_id     TEXT NOT NULL,
  plan_sha256 TEXT NOT NULL,
  plan_json   TEXT NOT NULL,
  issued_at   TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  used_at     TEXT
);

CREATE TABLE IF NOT EXISTS deliveries (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id     TEXT NOT NULL,
  channel     TEXT NOT NULL,
  status      TEXT NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT,
  sent_at     TEXT,
  last_error  TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_event_id TEXT,
  card_id     TEXT,
  ts          TEXT NOT NULL,
  kind        TEXT NOT NULL,
  detail      TEXT
);

CREATE TABLE IF NOT EXISTS ingest_errors (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name   TEXT NOT NULL,
  ts          TEXT NOT NULL,
  reason      TEXT NOT NULL,
  raw_head    TEXT
);
"""


def _audit(conn, kind, event_id=None, card_id=None, detail=None):
    conn.execute(
        'INSERT INTO events(subject_event_id, card_id, ts, kind, detail) VALUES(?,?,?,?,?)',
        (event_id, card_id, iso(now_utc()), kind, detail))


def record_ingest_error(file_name, reason, raw_head=''):
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            'INSERT INTO ingest_errors(file_name, ts, reason, raw_head) VALUES(?,?,?,?)',
            (file_name, iso(now_utc()), reason, raw_head[:200]))


# ---- ingest (C2/M3 card/occurrence atomic transaction) ----
def ingest(payload):
    """Ingest a validated payload. -> 'inserted'|'coalesced'|'duplicate'.

    Once called only from the spool watcher thread. It no longer is — _emit_run_result
    ingests from the sentinel watcher, the reaper and the HTTP handler as well — so the
    coalesce race is prevented by BEGIN IMMEDIATE alone rather than by single-threading.
    """
    norm = validate_payload(payload)          # ValidationError means the caller moves it to bad/
    created = norm['created_at']
    event_id = payload['event_id']
    group_key = payload['group_key']
    digest = action_digest(payload)
    now = now_utc()
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        # 1) Idempotence: an occurrence already seen is a harmless finish (crash reprocessing guard, C2).
        seen = conn.execute('SELECT card_id FROM occurrences WHERE event_id=?',
                            (event_id,)).fetchone()
        if seen is not None:
            return 'duplicate'
        # 2) Coalesce target: an open card with the same group_key and action_digest, created
        #    within 24h (the one-card-per-day rule).
        cutoff = iso(now - COALESCE_WINDOW)
        card = conn.execute(
            'SELECT * FROM cards WHERE group_key=? AND action_digest=? '
            'AND dismissed_at IS NULL AND archived_at IS NULL AND created_at>=? '
            'ORDER BY created_at DESC LIMIT 1',
            (group_key, digest, cutoff)).fetchone()
        if card is None:
            # New card: this occurrence becomes its card_id.
            card_id = event_id
            pinned = 1 if payload['urgency'] == 'urgent' else 0
            conn.execute(
                'INSERT INTO cards(card_id, group_key, source, kind, urgency, title, body, '
                'action_json, link_json, action_digest, created_at, received_at, pinned, '
                'occurrence_count, last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (card_id, group_key, payload['source'], payload['kind'], payload['urgency'],
                 payload['title'], payload.get('body'),
                 json.dumps(payload.get('recommended_action'), ensure_ascii=False)
                 if payload['kind'] == 'action' else None,
                 json.dumps(payload.get('link'), ensure_ascii=False)
                 if payload['kind'] == 'link' else None,
                 digest, iso(created), iso(now), pinned, 1, iso(now)))
            conn.execute(
                'INSERT INTO occurrences(event_id, card_id, group_key, payload_json, received_at) '
                'VALUES(?,?,?,?,?)',
                (event_id, card_id, group_key, json.dumps(payload, ensure_ascii=False), iso(now)))
            _audit(conn, 'ingested', event_id, card_id, payload['urgency'])
            if pinned:
                _audit(conn, 'pin', event_id, card_id, 'urgent-auto')
            status = 'inserted'
        else:
            # Coalesce: add an occurrence and update the card projection (M3 monotonicity / read revival).
            card_id = card['card_id']
            conn.execute(
                'INSERT INTO occurrences(event_id, card_id, group_key, payload_json, received_at) '
                'VALUES(?,?,?,?,?)',
                (event_id, card_id, group_key, json.dumps(payload, ensure_ascii=False), iso(now)))
            new_urgency = 'urgent' if (card['urgency'] == 'urgent'
                                       or payload['urgency'] == 'urgent') else 'normal'
            promote = (card['urgency'] != 'urgent' and new_urgency == 'urgent')
            conn.execute(
                'UPDATE cards SET occurrence_count=occurrence_count+1, last_seen=?, '
                'read_at=NULL, urgency=?, pinned=CASE WHEN ? THEN 1 ELSE pinned END, '
                'title=?, body=?, source=? WHERE card_id=?',
                (iso(now), new_urgency, 1 if promote else 0,
                 payload['title'], payload.get('body'), payload['source'], card_id))
            _audit(conn, 'coalesce', event_id, card_id, None)
            if promote:
                _audit(conn, 'pin', event_id, card_id, 'urgent-promote')
            status = 'coalesced'
        # 3) Enqueue the Slack outbox at the first urgent transition (the P4 worker actually sends).
        if status == 'inserted' and payload['urgency'] == 'urgent':
            _enqueue_slack(conn, card_id)
        elif status == 'coalesced' and promote:
            _enqueue_slack(conn, card_id)
    # Outside the transaction: flood detection uses a separate transaction.
    _maybe_flood(group_key)
    return status


def _enqueue_slack(conn, card_id, channel='slack'):
    # Enqueue the urgent card in the Slack outbox (P4 worker retries and sends, at least once).
    # The group_key guard in _maybe_flood excludes recursive flood notifications.
    conn.execute(
        'INSERT INTO deliveries(card_id, channel, status, next_attempt_at) VALUES(?,?,?,?)',
        (card_id, channel, 'pending', iso(now_utc())))


# ---- flood detection (M8) ----
def _maybe_flood(group_key):
    if group_key.startswith('pipe:flood:'):
        return                                 # stop recursion
    now = now_utc()
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        window_start = iso(now - FLOOD_WINDOW)
        cnt = conn.execute(
            'SELECT COUNT(*) FROM occurrences WHERE group_key=? AND received_at>=?',
            (group_key, window_start)).fetchone()[0]
        if cnt < FLOOD_THRESHOLD:
            return
        flood_gk = 'pipe:flood:' + group_key
        # 30-minute cooldown: skip if a recent flood card already exists.
        cooldown_start = iso(now - FLOOD_COOLDOWN)
        recent = conn.execute(
            'SELECT card_id FROM cards WHERE group_key=? AND created_at>=? '
            'AND dismissed_at IS NULL ORDER BY created_at DESC LIMIT 1',
            (flood_gk, cooldown_start)).fetchone()
        if recent is not None:
            # During the cooldown, only update the existing flood card's count.
            conn.execute(
                'UPDATE cards SET occurrence_count=occurrence_count+1, last_seen=? WHERE card_id=?',
                (iso(now), recent['card_id']))
            return
        card_id = flood_gk + ':' + now.strftime('%Y%m%dT%H%M%SZ')
        conn.execute(
            'INSERT INTO cards(card_id, group_key, source, kind, urgency, title, body, '
            'action_digest, created_at, received_at, pinned, occurrence_count, last_seen) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (card_id, flood_gk, 'monitor', 'info', 'urgent',
             'Message pipeline flood — ' + group_key,
             '%d or more events arrived within 10 minutes. Check the producer.' % cnt,
             'flood-' + group_key, iso(now), iso(now), 1, cnt, iso(now)))
        _audit(conn, 'flood', None, card_id, 'count=%d gk=%s' % (cnt, group_key))
        _enqueue_slack(conn, card_id)


# ---- state transitions (conditional UPDATE + audit, one transaction) ----
def _transition(card_id, set_sql, params, audit_kind, cond_sql=''):
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        cur = conn.execute(
            'UPDATE cards SET ' + set_sql + ' WHERE card_id=?' + cond_sql,
            params + (card_id,))
        if cur.rowcount != 1:
            return False
        _audit(conn, audit_kind, None, card_id, None)
        return True


def mark_read(card_id):
    return _transition(card_id, 'read_at=?', (iso(now_utc()),), 'read',
                       ' AND read_at IS NULL')


def set_pin(card_id, pinned):
    return _transition(card_id, 'pinned=?', (1 if pinned else 0,),
                       'pin' if pinned else 'unpin')


def archive(card_id):
    return _transition(card_id, 'archived_at=?', (iso(now_utc()),), 'archive',
                       ' AND archived_at IS NULL')


def dismiss(card_id):
    return _transition(card_id, 'dismissed_at=?', (iso(now_utc()),), 'dismiss',
                       ' AND dismissed_at IS NULL')


def undismiss(card_id):
    return _transition(card_id, 'dismissed_at=NULL', (), 'undismiss',
                       ' AND dismissed_at IS NOT NULL')


# ---- queries ----
def _card_to_dict(row):
    result_prefix = 'devmon:run-result:'
    group_key = row['group_key']
    result_run_id = group_key[len(result_prefix):] if group_key.startswith(result_prefix) else None
    return {
        'card_id': row['card_id'], 'group_key': group_key, 'source': row['source'],
        'kind': row['kind'], 'urgency': row['urgency'], 'title': row['title'],
        'body': row['body'],
        'action': json.loads(row['action_json']) if row['action_json'] else None,
        'link': json.loads(row['link_json']) if row['link_json'] else None,
        'created_at': row['created_at'], 'received_at': row['received_at'],
        'read_at': row['read_at'], 'slack_sent_at': row['slack_sent_at'],
        'pinned': bool(row['pinned']), 'archived': row['archived_at'] is not None,
        'occurrence_count': row['occurrence_count'], 'last_seen': row['last_seen'],
        'run_id': row['run_id'], 'result_run_id': result_run_id,
    }


ORDER = 'ORDER BY pinned DESC, (read_at IS NULL) DESC, created_at DESC, received_at DESC'


def feed(scope='active'):
    conn = _conn()
    if scope == 'archived':
        where = 'dismissed_at IS NULL AND archived_at IS NOT NULL'
    elif scope == 'all':
        where = 'dismissed_at IS NULL'
    else:  # active
        where = 'dismissed_at IS NULL AND archived_at IS NULL'
    rows = conn.execute('SELECT * FROM cards WHERE ' + where + ' ' + ORDER).fetchall()
    return {'messages': [_card_to_dict(r) for r in rows], 'counts': counts()}


def preview(limit=5):
    conn = _conn()
    rows = conn.execute(
        'SELECT * FROM cards WHERE dismissed_at IS NULL AND archived_at IS NULL '
        + ORDER + ' LIMIT ?', (limit,)).fetchall()
    return {'messages': [_card_to_dict(r) for r in rows],
            'unread_count': unread_count()}


def unread_count():
    conn = _conn()
    return conn.execute(
        'SELECT COUNT(*) FROM cards WHERE read_at IS NULL AND dismissed_at IS NULL '
        'AND archived_at IS NULL').fetchone()[0]


def counts():
    conn = _conn()
    def q(where):
        return conn.execute('SELECT COUNT(*) FROM cards WHERE ' + where).fetchone()[0]
    active = 'dismissed_at IS NULL AND archived_at IS NULL'
    return {
        'active': q(active),
        'unread': q(active + ' AND read_at IS NULL'),
        'action': q(active + " AND kind='action'"),
        'link': q(active + " AND kind='link'"),
        'urgent': q(active + " AND urgency='urgent'"),
        'archived': q('dismissed_at IS NULL AND archived_at IS NOT NULL'),
    }


# ---- sweep (M9 / retention) ----
def sweep():
    """Runs every 15 minutes: archive excess cards and hard-purge after 180d. One sweep thread."""
    now = now_utc()
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        # 1) Archive: if active > 20, archive only the oldest eligible cards, leaving 20 active.
        active = conn.execute(
            'SELECT COUNT(*) FROM cards WHERE dismissed_at IS NULL AND archived_at IS NULL'
        ).fetchone()[0]
        excess = active - ARCHIVE_ACTIVE_MIN
        if excess > 0:
            idle = iso(now - ARCHIVE_IDLE)
            rows = conn.execute(
                'SELECT card_id FROM cards WHERE dismissed_at IS NULL AND archived_at IS NULL '
                'AND pinned=0 AND read_at IS NOT NULL AND read_at<=? AND last_seen<=? '
                'ORDER BY created_at ASC LIMIT ?', (idle, idle, excess)).fetchall()
            for r in rows:
                conn.execute('UPDATE cards SET archived_at=? WHERE card_id=? '
                             'AND archived_at IS NULL AND pinned=0',
                             (iso(now), r['card_id']))
                _audit(conn, 'archive', None, r['card_id'], 'sweep')
        # 2) 180d hard purge, including the card's execution/approval/delivery ledgers so the
        #    original plan does not persist forever (#7). Exclude cards with an active run_id,
        #    a kept run, or any terminal run that still has a tmux target: deleting the DB record
        #    while the pane lives would make later generation-aware reclamation impossible.
        old = iso(now - RETENTION)
        purged = conn.execute(
            'SELECT card_id FROM cards WHERE received_at<=? AND run_id IS NULL '
            'AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.card_id=cards.card_id '
            'AND r.reclaimed_at IS NULL AND (r.keep_requested=1 OR r.tmux_target IS NOT NULL))',
            (old,)).fetchall()
        for r in purged:
            cid = r['card_id']
            conn.execute('DELETE FROM occurrences WHERE card_id=?', (cid,))
            conn.execute('DELETE FROM events WHERE card_id=?', (cid,))
            conn.execute('DELETE FROM approvals WHERE card_id=?', (cid,))
            conn.execute('DELETE FROM runs WHERE card_id=?', (cid,))
            conn.execute('DELETE FROM deliveries WHERE card_id=?', (cid,))
            conn.execute('DELETE FROM cards WHERE card_id=?', (cid,))
        # Expired approval nonces have a short TTL, so delete any over a day old at once to
        # avoid retaining the original plan.
        conn.execute('DELETE FROM approvals WHERE issued_at<=?', (iso(now - timedelta(days=1)),))
        if purged:
            _audit(conn, 'purge', None, None, 'count=%d' % len(purged))


# ============================================================
# Action axis (P3): plan (canonical + nonce) -> execute (CAS + drift) -> run FSM.
# Security invariant: preview == execution. Prompts and skills live only in plan_json; the tmux
# command line receives only a server-controlled path.
# ============================================================
RUN_ACTIVE = ('starting', 'running')
RUN_TERMINAL = ('done', 'failed', 'stopped', 'interrupted')
RUN_KEEPABLE = RUN_ACTIVE + RUN_TERMINAL


def canonical_plan(card_row, exec_cfg):
    """Derive the canonical execution plan plus sha256 from a card's current recommended_action.
    Invalid cases (not action, dismissed, cwd missing/outside, bad skill syntax) return None and
    are treated as drift/rejection. plan = {cwd(realpath), skill|prompt, explain}."""
    if card_row is None or card_row['kind'] != 'action' or card_row['dismissed_at'] is not None:
        return None
    raw = card_row['action_json']
    if not raw:
        return None
    action = json.loads(raw)
    cwd = action.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return None
    real = os.path.realpath(os.path.expanduser(cwd))
    root = exec_cfg.get('cwd_root')
    if root:
        rroot = os.path.realpath(os.path.expanduser(root))
        # Only strictly below root is allowed: root itself is refused. With root=$HOME, this allows
        #   projects below the home directory regardless of their folder convention, but never the
        #   home directory itself. The os.sep suffix prevents a prefix attack that mistakes
        #   '/srv/project-two' for a child of '/srv/project'.
        if not real.startswith(rroot + os.sep):
            return None                                   # outside the allowed root, or the root itself
    if not os.path.isdir(real):
        return None                                       # refuse a directory that does not exist
    # The plan is cwd(realpath) + skill|prompt + reason. If any of these changes after approval,
    # the newly derived sha disagrees and becomes plan_stale, preventing execution of something
    # different from what was approved.
    plan = {'cwd': real, 'explain': action.get('explain', '')}
    exec_argv = action.get('exec')
    skill = action.get('skill')
    if isinstance(exec_argv, list) and exec_argv:
        # Direct executable: argv list (no Claude and no shell parsing). exec[0] must be an existing
        #   executable absolute path. The owner previews the exact argv before approving, so it has the
        #   same trust model as a prompt: their own machine and their own script.
        if not all(isinstance(x, str) and x for x in exec_argv):
            return None
        prog = os.path.realpath(os.path.expanduser(exec_argv[0]))
        if not os.path.isabs(exec_argv[0]) or not os.path.isfile(prog) or not os.access(prog, os.X_OK):
            return None                                   # absolute path, existence and execute permission required
        plan['exec'] = [prog] + [str(x) for x in exec_argv[1:]]  # normalise prog realpath for a stable drift sha
    elif skill:
        skill = skill.strip()
        if not SKILL_RE.match(skill):
            return None
        plan['skill'] = skill
    else:
        prompt = action.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            return None
        plan['prompt'] = prompt
    blob = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    return plan, hashlib.sha256(blob.encode('utf-8')).hexdigest()


def issue_approval(card_id, exec_cfg):
    """Derive a plan from the current card and issue a one-time nonce (5 minutes). ->
    dict(ok/nonce/plan|error)."""
    conn = _conn()
    now = now_utc()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        card = conn.execute('SELECT * FROM cards WHERE card_id=?', (card_id,)).fetchone()
        if card is None:
            return {'ok': False, 'error': 'card_not_found'}
        if card['run_id'] is not None:
            return {'ok': False, 'error': 'run_active'}
        cp = canonical_plan(card, exec_cfg)
        if cp is None:
            return {'ok': False, 'error': 'not_executable'}
        plan, sha = cp
        nonce = secrets.token_urlsafe(24)
        conn.execute(
            'INSERT INTO approvals(nonce, card_id, plan_sha256, plan_json, issued_at, expires_at) '
            'VALUES(?,?,?,?,?,?)',
            (nonce, card_id, sha, json.dumps(plan, ensure_ascii=False),
             iso(now), iso(now + APPROVAL_TTL)))
        _audit(conn, 'plan', None, card_id, sha[:12])
    return {'ok': True, 'nonce': nonce, 'plan': plan, 'sha256': sha}


def redeem_approval(card_id, nonce, exec_cfg):
    """CAS the nonce (once), rederive and compare the current plan sha (mismatch means
    plan_stale = C5), then create a starting run. dev-monitor launches tmux next. ->
    dict(ok/plan/run_id|error)."""
    if not isinstance(nonce, str) or not nonce:
        return {'ok': False, 'error': 'no_nonce'}
    conn = _conn()
    now = now_utc()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        appr = conn.execute('SELECT * FROM approvals WHERE nonce=? AND card_id=?',
                            (nonce, card_id)).fetchone()
        if appr is None:
            return {'ok': False, 'error': 'no_approval'}
        if appr['used_at'] is not None:
            return {'ok': False, 'error': 'nonce_used'}
        if parse_rfc3339(appr['expires_at']) < now:
            return {'ok': False, 'error': 'expired'}
        card = conn.execute('SELECT * FROM cards WHERE card_id=?', (card_id,)).fetchone()
        if card is None:
            return {'ok': False, 'error': 'card_not_found'}
        if card['run_id'] is not None:
            return {'ok': False, 'error': 'run_active'}
        cp = canonical_plan(card, exec_cfg)
        if cp is None:
            return {'ok': False, 'error': 'plan_stale'}   # currently not executable (dismissed/cwd/skill drift)
        plan, sha = cp
        if sha != appr['plan_sha256']:
            return {'ok': False, 'error': 'plan_stale'}   # changed since approval: require confirmation again
        cur = conn.execute('UPDATE approvals SET used_at=? WHERE nonce=? AND used_at IS NULL',
                          (iso(now), nonce))
        if cur.rowcount != 1:                              # race loser (simultaneous click)
            return {'ok': False, 'error': 'nonce_used'}
        # Burn this card's OTHER outstanding approvals in the same transaction. One click
        # approves one execution; a preview that was opened and cancelled must not leave a
        # second capability alive for the rest of its five minutes, redeemable without any
        # further click once this run ends.
        conn.execute('UPDATE approvals SET used_at=? WHERE card_id=? AND used_at IS NULL',
                     (iso(now), card_id))
        run_id = 'run-' + now.strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3)
        conn.execute(
            'INSERT INTO runs(run_id, card_id, plan_sha256, plan_json, status, created_at) '
            'VALUES(?,?,?,?,?,?)',
            (run_id, card_id, sha, json.dumps(plan, ensure_ascii=False), 'starting', iso(now)))
        conn.execute('UPDATE cards SET run_id=? WHERE card_id=?', (run_id, card_id))
        _audit(conn, 'execute', None, card_id, run_id)
    return {'ok': True, 'plan': plan, 'run_id': run_id}


def run_mark_running(run_id, tmux_target):
    """starting -> running and record the target. -> True if transitioned. False means the run
    ended in the meantime, so the caller must kill the tmux window it just created as an orphan
    (#4). reap_runs never touches a targetless run, but the backend's own _reap_stuck_starting
    does once it can prove no window of this run's name exists, so False is a reachable
    outcome for a launch that took longer than that grace period — not merely defensive."""
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        cur = conn.execute(
            "UPDATE runs SET status='running', tmux_target=?, started_at=? "
            "WHERE run_id=? AND status='starting'",
            (tmux_target, iso(now_utc()), run_id))
        if cur.rowcount == 1:
            _audit(conn, 'run_running', None, None, run_id)
            return True
        return False


RUN_RESULT_LABEL = {'done': 'completed', 'failed': 'failed', 'interrupted': 'interrupted because the window closed'}


def _emit_run_result(run_id, status, exit_code, card_title):
    """Record execution termination as a message card, so its result is not missed when the
    observer modal is closed or the user is elsewhere. The execution window (tmux) remains alive,
    so this card is a notification rather than a log.

    - The group_key includes run_id, deliberately producing one card per run. With a fixed
      group_key, the 24h coalesce rule would fold multiple results into one line and lose which
      execution finished.
    - stopped is not announced: the owner just pressed Stop, so the notification would add no
      information.
    - The termination itself has already committed (this function runs outside that transaction).
      If this fails, execution state is still correct, so surface the failure on stderr but do not
      swallow it silently.
    """
    label = RUN_RESULT_LABEL.get(status)
    if label is None:
        return
    rc = '' if exit_code is None else ' (rc=%d)' % exit_code
    head = '✅ Run completed' if status == 'done' else '⚠️ Run ' + label
    title = (head + ' — ' + (card_title or run_id))[:160]
    payload = {
        'schema_version': 1,
        'event_id': 'devmon.runresult.' + run_id,
        'group_key': 'devmon:run-result:' + run_id,
        'source': 'dev-monitor',
        'kind': 'info',
        'urgency': 'normal',
        'title': title,
        'body': 'Run %s%s. The run window (tmux) is still open for 24 hours after turn end; '
                'use Keep if you want it indefinitely.' % (label, rc),
        'outcome': '%s%s' % (label, rc),
        'why_it_matters': 'This is the result of the work you approved and ran; use it to decide whether to keep watching it or run it again.',
        'followup': 'Open the run window (%s) in devterm and check its output.' % run_window_name(run_id),
        'created_at': iso(now_utc()),
    }
    try:
        ingest(payload)
    except Exception as e:  # noqa: BLE001 — notification failure must not roll back termination
        sys.stderr.write('[runresult] card emit fail run=%s: %s\n' % (run_id, e))


def _run_terminate(run_id, status, exit_code=None, error=None):
    """running/starting -> terminal. Clear the card run_id idempotently and emit a result card.
    -> (changed, tmux_target); without a change, -> (False, None)."""
    conn = _conn()
    changed, target, card_title = False, None, None
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        r = conn.execute('SELECT card_id, status, tmux_target FROM runs WHERE run_id=?',
                        (run_id,)).fetchone()
        if r is not None and r['status'] not in RUN_TERMINAL:
            conn.execute('UPDATE runs SET status=?, exit_code=?, error=?, ended_at=? WHERE run_id=?',
                        (status, exit_code, (error or '')[:500] or None, iso(now_utc()), run_id))
            conn.execute('UPDATE cards SET run_id=NULL WHERE card_id=? AND run_id=?',
                        (r['card_id'], run_id))
            _audit(conn, 'run_' + status, None, r['card_id'],
                   run_id + (' rc=%s' % exit_code if exit_code is not None else ''))
            src = conn.execute('SELECT title FROM cards WHERE card_id=?',
                               (r['card_id'],)).fetchone()
            card_title = src['title'] if src else None
            changed, target = True, r['tmux_target']
    # Notify after commit: ingest starts its own transaction, so calling it above would nest one.
    if changed:
        _emit_run_result(run_id, status, exit_code, card_title)
    return (changed, target)


def run_finish(run_id, exit_code):
    """Sentinel received -> done (rc == 0) | failed."""
    _run_terminate(run_id, 'done' if exit_code == 0 else 'failed', exit_code=exit_code)


def run_fail(run_id, error):
    """tmux launch failure, etc. -> failed."""
    _run_terminate(run_id, 'failed', error=error)


def run_stop(run_id):
    """Owner stop -> stopped. -> (changed, tmux_target); the caller kills target."""
    return _run_terminate(run_id, 'stopped')


def run_keep(run_id):
    """Record the owner's explicit request to retain a run window indefinitely.

    Keep is allowed while a run is active as well as after turn completion, so an owner can
    make the decision before stepping away. It is intentionally one-way: this operation is an
    exemption from automatic reclamation, not another timer to manage.
    -> (ok, error), where an already-kept run is an idempotent success.
    """
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            'SELECT status, keep_requested, kept_at, reclaimed_at FROM runs WHERE run_id=?',
            (run_id,)).fetchone()
        if row is None:
            return (False, 'not_found')
        if row['reclaimed_at'] is not None:
            return (False, 'already_reclaimed')
        if row['status'] not in RUN_KEEPABLE:
            return (False, 'not_keepable')
        if row['keep_requested']:
            return (True, None)
        now = iso(now_utc())
        conn.execute('UPDATE runs SET keep_requested=1, kept_at=? WHERE run_id=?',
                     (now, run_id))
        _audit(conn, 'run_keep', None, None, run_id)
    return (True, None)


def reclaimable_runs():
    """Return terminal runs whose windows may still be reclaimed by the backend reaper."""
    rows = _conn().execute(
        'SELECT * FROM runs WHERE status IN (\'done\', \'failed\', \'stopped\', \'interrupted\') '
        'AND ended_at IS NOT NULL AND keep_requested=0 AND reclaimed_at IS NULL'
    ).fetchall()
    return [dict(row) for row in rows]


def run_mark_reclaimed(run_id, reason='retention'):
    """Record that external cleanup of a terminal run completed successfully."""
    conn = _conn()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            'SELECT card_id, status, keep_requested, reclaimed_at FROM runs WHERE run_id=?',
            (run_id,)).fetchone()
        if (row is None or row['status'] not in RUN_TERMINAL or row['keep_requested']
                or row['reclaimed_at'] is not None):
            return False
        conn.execute('UPDATE runs SET reclaimed_at=? WHERE run_id=?',
                     (iso(now_utc()), run_id))
        _audit(conn, 'run_reclaimed', None, row['card_id'],
               '%s: %s' % (reason, run_id))
    return True


def run_window_name(run_id):
    """Display name of a run's tmux window, a label so a person can tell which window belongs to
    which run in devterm. It is NOT a correlation key: window names are not unique (same-name
    windows may coexist), and may also collide with a window that remains as a login shell after
    completion. The reaper matches run and window only with the unique, stable window_id
    (tmux_target)."""
    return 'exec-' + run_id.split('-')[-1]


# ---- view session: a tmux session that exposes only that run's window to the modal ----
VIEW_SESSION_PREFIX = 'devmon-view-'


def run_view_session(run_id):
    """Name of the run's observation tmux session.

    This value goes unchanged into devterm's URL `?arg=`, so it must survive devterm-shell's
    normalisation (`[^A-Za-z0-9_-]` -> `_`). run_id is `run-<UTC>-<hex>`, which is lossless in
    that character set (see redeem_approval). The prefix filters it in devterm's session list.
    """
    return VIEW_SESSION_PREFIX + run_id


def run_view_request(run_row, alive_keys, session):
    """Pure decision about whether to open an observation session. -> (ok, payload|error_code).

    Fail closed: return window_id only if the stored target matches the current-generation alive
    set by its FULL key (`<server_pid>:<window_id>`). Comparing window_id alone would attach to a
    different run's window after a tmux server restart reuses `@N` — the exact High2 trap hit in
    round 7 on the kill path. Viewing attaches with write access, so that could send keystrokes to
    someone else's run.

    error_code uses the same vocabulary as the stop path (the frontend maps its messages in one
    place): not_found / not_active / launching (target not recorded) / stale_target_format /
    stale_generation (generation mismatch or window gone) / tmux_unavailable (alive query unknown).
    """
    if run_row is None:
        return (False, 'not_found')
    if run_row['status'] not in RUN_ACTIVE:
        return (False, 'not_active')
    target = run_row['tmux_target']
    if target is None:
        return (False, 'launching')             # launching: frontend retries briefly
    if alive_keys is None:
        return (False, 'tmux_unavailable')      # defer judgement; do not misidentify a live window as gone
    if ':' not in target:
        return (False, 'stale_target_format')   # legacy (@N): generation cannot be compared
    if target not in alive_keys:
        return (False, 'stale_generation')
    return (True, {'view': run_view_session(run_row['run_id']),
                   'window_id': target.rsplit(':', 1)[-1],
                   'target': target,
                   'session': session})


def active_view_sessions():
    """Set of view-session names that must remain alive: active (starting|running) runs.
    The reconciler uses it to reap any devmon-view-* outside this set, idempotently."""
    conn = _conn()
    rows = conn.execute(
        "SELECT run_id FROM runs WHERE status IN ('starting','running')").fetchall()
    return {run_view_session(r['run_id']) for r in rows}


REAP_GRACE_S = 30


def reap_runs(alive_ids, now=None):
    """Backstop. alive_ids is the set of window_ids currently present in the exec session.

    Correlation uses only the stored tmux_target (window_id). tmux assigns a unique, non-reused
    window_id to every window, which makes it reliable; window names are not unique and therefore
    cannot be correlation keys (the root cause in rounds 4/5/6). The sentinel is the normal
    completion path. The reaper cleans up only a sudden window death (external kill, etc.) that
    happens without the sentinel:

    - No recorded target (launching, or crash before mark_running): leave it alone. The sentinel
      records normal completion, and until then the card lock prevents double execution. Ending it
      rashly here would orphan a live Claude process (round 4).
    - Target recorded and window alive: retain it.
    - Target recorded but window gone, and the target record (started_at) is older than the
      REAP_GRACE_S grace period: window (= process) death is certain -> interrupted.
      The grace period MUST use started_at (the point where the window is created and target is
      recorded), not created_at. In a straddle where the reaper snapshots windows just before one
      is created and its target recorded, started_at is approximately the snapshot time and is
      always inside grace. If based on created_at, a launch delayed over 30 seconds (lock contention
      or tmux hang) would have expired grace already, interrupting a live window, unlocking its card
      and allowing double execution (round 7 High1).
    """
    conn = _conn()
    now = now or now_utc()
    alive = set(alive_ids)
    rows = conn.execute(
        "SELECT run_id, tmux_target, started_at FROM runs "
        "WHERE status IN ('starting','running')").fetchall()
    for r in rows:
        tgt = r['tmux_target']
        if tgt is None:
            continue                                      # launching/crash-orphan: sentinel and card lock own it
        if ':' not in tgt:
            # Legacy format without generation (pid) (@N): it cannot be safely compared with a
            # current pid:@N key. Matching its suffix in this generation reopens the window-id reuse
            # overkill (High2), so do NOT terminate it. (Not present in a real deployment: runs have
            # stored native pid:wid from the first deployment. This is a format-migration guard, round 8.)
            continue
        if tgt in alive:
            continue                                      # recorded window is live (generation-aware comparison)
        # With a target, started_at must exist too; run_mark_running writes both together.
        if r['started_at'] is None:
            continue                                      # theoretically impossible: target exists without started_at
        age = (now - parse_rfc3339(r['started_at'])).total_seconds()
        if age < REAP_GRACE_S:
            continue                                      # target just recorded; snapshot may predate its window
        _run_terminate(r['run_id'], 'interrupted')        # confirmed window disappearance -> terminate


def _run_to_dict(r):
    return {'run_id': r['run_id'], 'card_id': r['card_id'], 'status': r['status'],
            'exit_code': r['exit_code'], 'error': r['error'], 'tmux_target': r['tmux_target'],
            'created_at': r['created_at'], 'started_at': r['started_at'], 'ended_at': r['ended_at'],
            'keep': bool(r['keep_requested']), 'kept_at': r['kept_at'],
            'reclaimed_at': r['reclaimed_at'],
            'plan': json.loads(r['plan_json'])}


def list_runs(card_id=None, limit=50):
    conn = _conn()
    if card_id:
        rows = conn.execute('SELECT * FROM runs WHERE card_id=? ORDER BY created_at DESC LIMIT ?',
                          (card_id, limit)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT ?',
                          (limit,)).fetchall()
    return {'runs': [_run_to_dict(r) for r in rows]}


def get_run(run_id):
    r = _conn().execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
    return _run_to_dict(r) if r else None


def active_run_targets():
    """(run_id, tmux_target): runs that should be alive. Used by the reaper for its alive check."""
    rows = _conn().execute(
        "SELECT run_id, tmux_target FROM runs WHERE status IN ('starting','running')").fetchall()
    return [(r['run_id'], r['tmux_target']) for r in rows]


# ============================================================
# Slack outbox (P4): urgent cards are enqueued into deliveries by ingest; the worker sends them.
# At least once: retry with backoff until success; after the cap mark failed. slack_sent_at is
# orthogonal to read state.
# ============================================================
MAX_DELIVERY_ATTEMPTS = 6


def claim_due_deliveries(limit=10):
    """Join pending deliveries whose next_attempt_at has arrived with card information. Used by
    the worker."""
    now = iso(now_utc())
    rows = _conn().execute(
        'SELECT d.id AS id, d.card_id AS card_id, d.channel AS channel, d.attempts AS attempts, '
        'c.title AS title, c.urgency AS urgency, c.source AS source, c.kind AS kind, '
        'c.occurrence_count AS occurrence_count '
        'FROM deliveries d JOIN cards c ON c.card_id=d.card_id '
        "WHERE d.status='pending' AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=?) "
        'ORDER BY d.id LIMIT ?', (now, limit)).fetchall()
    return [dict(r) for r in rows]


def delivery_sent(delivery_id, card_id):
    """Delivery succeeded -> mark sent and set the card's slack_sent_at (first time only).
    Does not touch read state; the two axes are orthogonal."""
    conn = _conn()
    now = iso(now_utc())
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE deliveries SET status='sent', sent_at=? WHERE id=?", (now, delivery_id))
        conn.execute('UPDATE cards SET slack_sent_at=? WHERE card_id=? AND slack_sent_at IS NULL',
                    (now, card_id))
        _audit(conn, 'slack_sent', None, card_id, 'delivery=%s' % delivery_id)


def delivery_retry(delivery_id, attempts, error):
    """Delivery failed -> attempts + 1 and reschedule with exponential backoff. On the cap, mark
    it failed rather than silently swallowing it: leave an audit trail."""
    conn = _conn()
    now = now_utc()
    new_attempts = attempts + 1
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        if new_attempts >= MAX_DELIVERY_ATTEMPTS:
            conn.execute("UPDATE deliveries SET status='failed', attempts=?, last_error=? WHERE id=?",
                        (new_attempts, (error or '')[:300], delivery_id))
            _audit(conn, 'slack_failed', None, None,
                   'delivery=%s attempts=%d' % (delivery_id, new_attempts))
        else:
            backoff = min(3600, 30 * (2 ** attempts))
            conn.execute('UPDATE deliveries SET attempts=?, next_attempt_at=?, last_error=? WHERE id=?',
                        (new_attempts, iso(now + timedelta(seconds=backoff)),
                         (error or '')[:300], delivery_id))
