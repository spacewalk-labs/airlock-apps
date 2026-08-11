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
import asyncio, importlib.machinery, importlib.util, os, shutil, sys, time, types
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
# The case the old grader got wrong: it skipped the 5h axis entirely once the window was
# spent, so a fully exhausted account with a quiet 7d window graded "none" — healthy.
# 100 is worse than crit5, never exempt from it.
check("5h spent alone is crit", g._acct_alert_level(100, 0, None) == ("crit", "usage"))
check("5h spent is crit even with 7d at zero and no login warning",
      g._acct_alert_level(100, 0, 30) == ("crit", "usage"))
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

# codex usage survives a restart. The in-memory cache dies with the process and the
# reading costs an app-server spawn, so the panel used to open blank and stay blank
# while the probe ran. What must NOT survive: another account's numbers, and the claim
# that a remembered value is a fresh observation.
import tempfile
_codex_state_tmp = tempfile.mkdtemp(prefix="devterm-codex-state-")
g.CODEX_USAGE_STATE_DIR = _codex_state_tmp
g.CODEX_USAGE_STATE = os.path.join(_codex_state_tmp, "codex-usage.json")


def _codex_state_case(value_age, auth_mtime_at_load, payload=None):
    """Save a reading, wipe the memory cache, then load as a fresh process would."""
    g._codex_usage_state_drop()
    now = time.time()
    g._codex_usage_cache.update(valueAt=now - value_age, lastTryAt=now, task=None,
                                authMtime="login-A",
                                payload=payload or {"use5h": 4, "use7d": 5, "stale": False})
    saved = g._codex_usage_state_save()
    g._codex_usage_cache.update(valueAt=0.0, lastTryAt=0.0, payload=None,
                                authMtime=None, task=None)
    g._codex_auth_mtime = lambda: auth_mtime_at_load
    return saved, g._codex_usage_state_load(), g._codex_usage_cache.get("payload")


_real_auth_mtime = g._codex_auth_mtime
saved, loaded, payload = _codex_state_case(0, "login-A")
check("a fresh reading is saved and restored", saved and loaded and payload["use7d"] == 5)
check("a reading inside the TTL is restored as fresh", payload.get("stale") is False)

_, loaded, payload = _codex_state_case(g.CODEX_USAGE_TTL + 60, "login-A")
check("a reading past the TTL is restored as stale (the row says 'last value')",
      loaded and payload.get("stale") is True)

_, loaded, payload = _codex_state_case(0, "login-B")
check("another login's numbers are refused", not loaded and payload is None)
check("and the file holding them is dropped", not os.path.exists(g.CODEX_USAGE_STATE))

saved, _, _ = _codex_state_case(0, "login-A", payload={"use5h": None, "use7d": None})
check("a value-less payload is not saved", not saved)

g._codex_auth_mtime = lambda: "login-A"
g._codex_usage_cache.update(valueAt=time.time(), payload={"use5h": 1, "use7d": 2},
                            authMtime="login-A")
g._codex_usage_state_save()
g._invalidate_codex_usage_cache()
check("login/logout drops the file, so a restart cannot resurrect it",
      not os.path.exists(g.CODEX_USAGE_STATE))

g._codex_auth_mtime = _real_auth_mtime
shutil.rmtree(_codex_state_tmp, ignore_errors=True)

# --- codex binary discovery (the whole Codex line went dark on version-manager boxes) --
# _codex_bin() was `which("codex") or ~/.npm-global/bin/codex`. A systemd --user unit
# and a remote `su - <user> -c` both get a PATH with none of the directories a node CLI
# installs into, so `which` came back empty on a box where codex ran fine from a shell;
# the hardcoded fallback then put one innocent path into the error message. Everything
# below runs with an EMPTY PATH, because that is the shape of the environment the gate
# is actually started in. The candidate list itself is pinned by the shared corpus
# (backend/test_bin_discovery.py); these checks pin the two call sites onto it.
def _mkbin(path, mode=0o755):
    """Create an executable at `path`, pinning every directory made to 0755. Without
    that, a permissive umask makes the FIXTURE world-writable and bin_discovery's trust
    rules reject it — a red test for a reason that has nothing to do with discovery."""
    parts = os.path.dirname(path)
    os.makedirs(parts, exist_ok=True)
    while len(parts) > len(_disc_home):
        os.chmod(parts, 0o755)
        parts = os.path.dirname(parts)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, mode)


_disc_home = tempfile.mkdtemp(prefix="devterm-bindisc-")
os.chmod(_disc_home, 0o755)
_disc_saved = dict(os.environ)
try:
    os.environ.update(HOME=_disc_home, PATH="")
    os.environ.pop("CODEX_BIN", None)
    os.environ.pop("CODEX_EXTRA_BIN_DIRS", None)
    check("no codex anywhere -> None, never a path that was not verified",
          g._codex_bin() is None)
    check("...so the feature reports itself unavailable", g._codex_available() is False)
    _msg = g._codex_missing_error()
    check("the refusal names the command", "codex" in _msg)
    check("the refusal says where it looked", "searched" in _msg and "PATH(" in _msg)
    # The old text was the bare string "codex not available", which sent every
    # investigation to the box. A path may still appear now, but only in the rejected
    # list with the reason attached — never as a verdict about where codex should be.
    check("the refusal replaces the opaque wording",
          "not available" not in _msg and "not found" in _msg)
    check("the refusal says what to do next", "fix:" in _msg)
    # The outage shape: installed, working, and invisible to `which`.
    _fnm = os.path.join(_disc_home, ".local/share/fnm/aliases/default/bin/codex")
    _mkbin(_fnm)
    check("codex under a node version manager is found with an empty PATH",
          g._codex_bin() == _fnm)
    check("...and what is returned is really executable", os.access(g._codex_bin(), os.X_OK))
    check("...so the endpoints stop refusing", g._codex_available() is True)
    check("claude-status resolves the same binary as the gate (one contract, one module)",
          cs._codex_bin() == _fnm)
finally:
    os.environ.clear(); os.environ.update(_disc_saved)
    shutil.rmtree(_disc_home, ignore_errors=True)

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
