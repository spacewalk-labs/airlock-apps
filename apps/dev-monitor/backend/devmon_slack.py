#!/usr/bin/env python3
"""devmon_slack — the outbox worker that pushes urgent cards to Slack. stdlib only.

At-least-once, deliberately: a duplicate ping is a nuisance, a missed one is the failure
this feature exists to prevent. ingest() enqueues at the moment a card becomes urgent; this
worker claims pending deliveries, sends, and either marks them sent or reschedules with
backoff (giving up as failed after the cap).

The webhook URL is a SECRET, injected via DEV_MONITOR_SLACK_WEBHOOK. This module never puts
that value into a log line or an exception message — which is why send() returns a short
error string of its own making rather than letting a urllib exception carry the URL out.
"""
import json
import sys
import urllib.error
import urllib.request

import devmon_messages as MSG

URGENCY_MARK = {'urgent': '🔴', 'normal': '•'}
# enum -> what a human reads in Slack. Not an identity map: the point is that 'action'
# reads as something being asked of you, which the bare enum name does not convey.
KIND_LABEL = {'action': 'action requested', 'link': 'link', 'info': 'notice'}


def esc_mrkdwn(s):
    """Escape Slack mrkdwn control characters, so a semi-trusted title cannot turn into
    <!channel> or a disguised <url|link>. Slack's rule is that escaping & < > is enough to
    neutralise both the link and the mention syntax."""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def format_text(card, console_url=''):
    """Build the message text. A card's title/source go to the owner's own channel so they
    are not secrets, but they are escaped anyway to prevent mrkdwn injection. console_url is
    server-generated, so it is used as-is."""
    mark = URGENCY_MARK.get(card.get('urgency'), '•')
    kind = KIND_LABEL.get(card.get('kind'), card.get('kind', ''))
    lines = ['%s *%s*' % (mark, esc_mrkdwn(card.get('title', '(no title)'))),
             '_%s · %s_' % (esc_mrkdwn(card.get('source', '?')), esc_mrkdwn(kind))]
    if card.get('occurrence_count', 1) > 1:
        lines[-1] += '  ×%d' % card['occurrence_count']
    if console_url:
        lines.append('<%s|Open in the console>' % console_url)
    return '\n'.join(lines)


def send(webhook, text, timeout=8):
    """POST to the webhook. -> (ok, short_error). The error never contains the URL."""
    data = json.dumps({'text': text}).encode('utf-8')
    req = urllib.request.Request(webhook, data=data,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = getattr(r, 'status', r.getcode())
            return (200 <= code < 300), 'http %d' % code
    except urllib.error.HTTPError as e:
        return False, 'http %d' % e.code
    except Exception as e:                          # noqa: BLE001 — type only, never the URL
        return False, type(e).__name__


def run_worker(webhook, stop_event, console_url=''):
    """The outbox worker: one thread, one pass every 5 seconds."""
    while not stop_event.is_set():
        try:
            for d in MSG.claim_due_deliveries(10):
                ok, err = send(webhook, format_text(d, console_url))
                if ok:
                    MSG.delivery_sent(d['id'], d['card_id'])
                else:
                    MSG.delivery_retry(d['id'], d['attempts'], err)
        except Exception as e:                      # noqa: BLE001 — the worker must not die
            sys.stderr.write('[slack] worker err: %s\n' % type(e).__name__)
        stop_event.wait(5)
