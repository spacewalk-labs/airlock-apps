"""Offline contract checks for devterm's account line — no HTTP, no box, no network.

Run: python3 apps/devterm/test-accounts.py   (exit 0 = pass)

What it pins down, because these are the parts that fail quietly:
  - the warning grade per axis, and which reason wins at equal severity;
  - that a spent 5h window does not mute a critical 7d window;
  - that /acct-alert still works with NO shared usage store (a single box has no
    collector) by falling back to this box probing its own live account, and that with
    no source at all it reports level="none" instead of inventing one;
  - that the cross-origin echo is limited to this same box (tailnet domains are public
    suffixes, so "same-site" is not a boundary);
  - that a revoked Codex credential (auth.json still present, refresh token dead) is
    graded crit instead of passing for a healthy login;
  - that no identity ever appears in the alert payload.
"""
import asyncio, importlib.machinery, importlib.util, os, sys, types
os.environ.setdefault("AIRLOCK_OWNER", "owner@example.com")
spec = importlib.util.spec_from_file_location("gate", "apps/devterm/backend/devterm-gate.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
# claude-status has no .py extension (it is a command on PATH), so it needs an explicit
# source loader. Importing it runs no side effects — main() is behind __main__.
cs_loader = importlib.machinery.SourceFileLoader("claude_status", "apps/devterm/bin/claude-status")
cs_spec = importlib.util.spec_from_loader("claude_status", cs_loader)
cs = importlib.util.module_from_spec(cs_spec); cs_loader.exec_module(cs)

fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

TH = g.USAGE_TH
# level grading
check("no data -> none", g._acct_alert_level(None, None, None) == ("none", None))
check("5h warn", g._acct_alert_level(TH["warn5"], 0, None) == ("warn", "usage"))
check("5h crit", g._acct_alert_level(TH["crit5"], 0, None) == ("crit", "usage"))
check("5h spent does not mute 7d crit",
      g._acct_alert_level(100, TH["crit7"], None) == ("crit", "usage"))
check("login warn beats usage warn at equal severity",
      g._acct_alert_level(TH["warn5"], 0, 3) == ("warn", "login"))
check("usage crit beats login warn",
      g._acct_alert_level(TH["crit5"], 0, 3) == ("crit", "usage"))
check("codex axis grades", g._acct_alert_level(0, 0, None, TH["crit7"]) == ("crit", "codex"))
check("codex never displaces claude at equal severity",
      g._acct_alert_level(TH["warn5"], 0, None, TH["warn7"]) == ("warn", "usage"))
# A revoked Codex credential: auth.json is still there, so nothing else in the account
# line looks wrong. It has to raise the level on its own.
check("revoked codex login is crit",
      g._acct_alert_level(0, 0, None, None, "auth") == ("crit", "codex-login"))
check("revoked codex login does not displace a claude crit",
      g._acct_alert_level(TH["crit5"], 0, None, None, "auth") == ("crit", "usage"))
check("a retryable codex error is not an alert",
      g._acct_alert_level(0, 0, None, None, "rpc-500") == ("none", None))

# claude-status is the only thing that can tell a revoked credential from a hiccup: it
# is the caller that actually spends the token. Field message from the agent that failed.
check("revoked-token message classifies as auth",
      cs._codex_auth_revoked({"code": -32603, "message":
          "Your access token could not be refreshed because you have since logged out "
          "or signed in to another account. Please sign in again."}))
check("401 classifies as auth", cs._codex_auth_revoked({"code": 401, "message": ""}))
check("an unrelated rpc error is not auth",
      not cs._codex_auth_revoked({"code": -32603, "message": "internal error"}))
check("a non-dict error is not auth", not cs._codex_auth_revoked("boom"))
check("NaN is not a number", g._finite_number(float("nan")) is None)
check("bool is not a number", g._finite_number(True) is None)
check("int passes", g._finite_number(0) == 0)

# CORS: same first hostname label echoes, anything else does not
import socket
host = socket.gethostname().split(".")[0]
check("same-box origin echoes",
      g._cors_origin({b"origin": f"https://{host}.example.ts.net:8447".encode()})
      == f"https://{host}.example.ts.net:8447".encode())
check("other node does not echo",
      g._cors_origin({b"origin": b"https://someone-else.example.ts.net"}) is None)
check("no origin -> None", g._cors_origin({}) is None)
check("garbage origin -> None", g._cors_origin({b"origin": b"::::"}) is None)

# _resp keeps the ACAO header out unless asked
r = g._resp(b"200 OK", b"{}", b"application/json")
check("no ACAO by default", b"Access-Control-Allow-Origin" not in r)
r2 = g._resp(b"200 OK", b"{}", b"application/json", extra=b"Access-Control-Allow-Origin: x\r\n")
check("ACAO + Connection both present", b"Access-Control-Allow-Origin: x\r\n" in r2 and b"Connection: close" in r2)

# codex cache: pending shape has every key the success shape has
succ = {"use5h": 1, "use7d": 2, "reset5h": None, "reset7d": None, "plan": None,
        "resetCredits": None, "observedAt": None, "err": None}
pend = g._codex_pending_payload()
check("pending payload keeps the success keys", set(succ) <= set(pend))
check("has_usage_value false on empty", not g._codex_has_usage_value({"use5h": None, "use7d": None}))
check("has_usage_value true on one axis", g._codex_has_usage_value({"use5h": 0, "use7d": None}))

# /acct-alert falls back to the live probe when the shared store has nothing,
# and never invents a level out of nothing.
async def alert_with(list_payload, live_payload, codex_payload):
    g._acct_alert_cache.update(at=0.0, payload=None)
    g._live_usage_cache.update(at=0.0, payload=None)
    g._acct_list_with_usage = lambda: asyncio.sleep(0, result=list_payload)
    g._live_usage_cached = lambda: asyncio.sleep(0, result=live_payload)
    g._codex_usage_cached = lambda *a, **k: asyncio.sleep(0, result=codex_payload)
    sent = {}
    async def fake_send(cw, status, payload, cors=None):
        sent.update(status=status, payload=payload, cors=cors)
    g._send_json = fake_send
    await g._serve_acct_alert({}, None)
    return sent["payload"]

store_empty = {"accounts": [{"active": True, "usage": {"err": "no data"}, "rtExpiry": None}]}
p = asyncio.run(alert_with(store_empty, {"use5h": 90, "use7d": 10}, {}))
check("falls back to live probe", (p["level"], p["use5h"]) == ("crit", 90))
p = asyncio.run(alert_with(store_empty, {}, {}))
check("no source anywhere -> none, no invented numbers",
      (p["level"], p["reason"], p["use5h"], p["use7d"]) == ("none", None, None, None))
p = asyncio.run(alert_with(
    {"accounts": [{"active": True, "usage": {"use5h": 5, "use7d": 5}, "rtExpiry": None}]},
    {"use5h": 99, "use7d": 99}, {}))
check("shared store wins over the probe", (p["use5h"], p["level"]) == (5, "none"))
p = asyncio.run(alert_with(store_empty, {}, {"use7d": 95}))
check("codex alone can raise the level", (p["level"], p["reason"]) == ("crit", "codex"))
p = asyncio.run(alert_with(store_empty, {}, {"use7d": 5, "stale": True, "lastErr": "auth"}))
check("a revoked codex login reaches the alert, numbers or not",
      (p["level"], p["reason"], p["codexErr"]) == ("crit", "codex-login", "auth"))
check("thresholds are shipped with the verdict", p["thresholds"] == TH)
check("no identity in the payload",
      not any(k in p for k in ("email", "accounts", "token", "accessToken")))
p = asyncio.run(alert_with("not-a-dict", {}, {}))
check("broken account data degrades to none + typed err",
      p["level"] == "none" and str(p["err"]).startswith("accounts-"))

print(("\nFAILED: " + ", ".join(fails)) if fails else "\nall contract checks passed")
sys.exit(1 if fails else 0)
