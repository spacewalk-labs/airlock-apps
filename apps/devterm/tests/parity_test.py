#!/usr/bin/env python3
"""Offline regression for devterm's approved public-parity contracts."""

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib


APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]


class Reader:
    def __init__(self, data=b""):
        self.data = data

    async def read(self, _size=-1):
        data, self.data = self.data, b""
        return data


class Writer:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        return None

    def close(self):
        return None


def response(writer):
    head, body = bytes(writer.data).split(b"\r\n\r\n", 1)
    return head.split(b"\r\n", 1)[0], body


def request(method, path, identity="owner@example.test", body=b""):
    lines = [f"{method} {path} HTTP/1.1", f"X-Test-Identity: {identity}"]
    if body:
        lines.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gate(home):
    os.environ.update({
        "HOME": str(home),
        "AIRLOCK_OWNER": "owner@example.test",
        "AIRLOCK_IDENTITY_HEADER": "X-Test-Identity",
        "DEVTERM_WEB": str(APP / "web"),
    })
    spec = importlib.util.spec_from_file_location(
        "airlock_devterm_parity_gate", APP / "backend" / "devterm-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def test_font_and_notice():
    expected = {
        "d2coding-400.woff2": "49a1a380c1079bc74950acf6152cbfc4fd69101813e18127e1be45bd8bb15063",
        "d2coding-700.woff2": "7e03de7314d7a2d5a8a275531c760902c71494ac1c7d1fde0dab4f2f318f0ca0",
        "D2Coding-OFL.txt": "1807e8dec4d65f474cbf9be39f5e2254ecb81702babc320749e272ea66ffcc69",
        "symbols-nerd-font-mono.woff2": "8efa6ba89f0a1f3eefde028f36aa64a13e36282e15ea0ca6929c664501037467",
        "SymbolsNerdFontMono-OFL.txt": "cf7e117fa08dc292484a0d087caaf6dfc339d912837b18a43af9bc410446390f",
    }
    for name, digest in expected.items():
        path = APP / "web" / "vendor" / name
        assert path.is_file() and sha256(path) == digest, name
    notice = (APP / "NOTICE").read_text()
    assert "9d6f0559691ebe670a23fbf7b72a8dc42362f1fb" in notice
    assert "SIL Open Font License, Version 1.1" in notice
    index = (APP / "web" / "index.html").read_text()
    client = (APP / "web" / "app.js").read_text()
    assert "d2coding-400.woff2" in index and "d2coding-700.woff2" in index
    assert "symbols-nerd-font-mono.woff2" in index
    family = next(line for line in client.splitlines() if "fontFamily:" in line)
    assert (family.index("ui-monospace") < family.index("D2Coding")
            < family.index("Symbols Nerd Font Mono") < family.rindex("monospace"))


def test_keep_contracts():
    manifest = tomllib.loads((APP / "airlock-app.toml").read_text())
    defaults = manifest["config"]["defaults"]
    assert defaults["accounts"] is False
    assert defaults["lang"] == "C.UTF-8"
    assert {"airlock-devterm.service", "airlock-devterm-gate.service"} == set(
        manifest["artifacts"]["units"])

    install = (APP / "install.sh").read_text()
    assert 'if [ "$ACCOUNTS" = true ]; then' in install
    assert "AIRLOCK_IDENTITY_HEADER" in install and "AIRLOCK_OWNER" in install
    assert "systemctl --user is-active --quiet airlock-devterm.service || changed_ttyd=1" in install
    assert "systemctl --user is-active --quiet airlock-devterm-gate.service || changed_gate=1" in install
    assert '"$HERE/web/keytest.html"' in install

    render = APP / "render.sh"
    ttyd_unit = subprocess.check_output([
        "bash", "-c", 'source "$1"; render_devterm_unit_ttyd C.UTF-8 9911 /bin/ttyd 15',
        "parity", str(render)], text=True)
    gate_unit = subprocess.check_output([
        "bash", "-c", 'source "$1"; render_devterm_unit_gate 9912 "" /usr/bin/python3 /gate.py',
        "parity", str(render)], text=True)
    assert "KillMode=process" in ttyd_unit and "KillMode=process" in gate_unit

    gate_source = (APP / "backend" / "devterm-gate.py").read_text()
    assert '~/.local/state/airlock/devterm' in gate_source
    assert "_codex_usage_state_load" in gate_source and "_codex_usage_state_save" in gate_source


def test_plaintext_retirement_contract():
    manifest = tomllib.loads((APP / "airlock-app.toml").read_text())
    defaults = manifest["config"]["defaults"]
    assert "public_port" not in defaults
    assert "redirect_port" not in defaults
    assert "plaintext_redirect" not in manifest

    lifecycle = tomllib.loads((ROOT / "abi" / "apps" / "devterm.toml").read_text())
    assert lifecycle["capabilities"] == []

    # DT-R1 selected route: renderer emits only the owner gate. A sentinel makes
    # any accidental reintroduction of the generic plaintext redirect fatal.
    script = r'''
emit_owner_gate() { printf 'owner=%s upstream=%s predicate=%s\n' "$1" "$2" "$3"; }
emit_https_redirect() { exit 97; }
source "$1"
render_devterm_nginx 9910 9912
'''
    rendered = subprocess.check_output(
        ["bash", "-c", script, "_", str(APP / "render.sh")], text=True)
    assert rendered == (
        "# devterm owner gate — generated by apps/devterm/install.sh\n"
        "owner=9910 upstream=127.0.0.1:9912 predicate=owner_ok\n"
    )

    for path in (APP / "install.sh", APP / "smoke.sh", APP / "render.sh"):
        source = path.read_text()
        for forbidden in (
            "AIRLOCK_DEVTERM_PUBLIC_PORT",
            "AIRLOCK_DEVTERM_REDIRECT_PORT",
            "emit_https_redirect",
            "9900",
            "9913",
        ):
            assert forbidden not in source, (path, forbidden)
        assert not re.search(r"--http(?:=|\s)", source), path
        assert not re.search(
            r"(?m)^\s*(?:sudo\s+)?tailscale\s+serve\b", source
        ), path


async def test_gate_routes(gate):
    writer = Writer()
    await gate.handle(Reader(request("GET", "/vendor/symbols-nerd-font-mono.woff2")), writer)
    head, font = bytes(writer.data).split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"\r\nContent-Type: font/woff2\r\n" in head
    assert hashlib.sha256(font).hexdigest() == (
        "8efa6ba89f0a1f3eefde028f36aa64a13e36282e15ea0ca6929c664501037467"
    )

    writer = Writer()
    await gate.handle(Reader(request("GET", "/keytest.html")), writer)
    status, body = response(writer)
    assert status == b"HTTP/1.1 200 OK" and "한글 입력 진단".encode() in body

    writer = Writer()
    await gate.handle(Reader(request("GET", "/keytest.html", "other@example.test")), writer)
    status, body = response(writer)
    assert status == b"HTTP/1.1 403 Forbidden" and "한글 입력 진단".encode() not in body

    wrong = (("GET", "/secret-put"), ("POST", "/secret-list"), ("DELETE", "/secret-del"))
    for method, path in wrong:
        writer = Writer()
        await gate.handle(Reader(request(method, path)), writer)
        status, body = response(writer)
        assert status == b"HTTP/1.1 405 Method Not Allowed", (method, path, status)
        assert json.loads(body) == {"ok": False, "error": "method not allowed"}

    allowed = (("POST", "/secret-put", b"{}"), ("GET", "/secret-list", b""),
               ("POST", "/secret-del", b"{}"))
    for method, path, payload in allowed:
        writer = Writer()
        await gate.handle(Reader(request(method, path, body=payload)), writer)
        status, body = response(writer)
        assert status != b"HTTP/1.1 405 Method Not Allowed", (method, path, status)
        assert isinstance(json.loads(body), dict)


async def test_owner_only_status_routes(gate):
    calls = []

    def stub(name):
        async def serve(*args):
            calls.append(name)
            await gate._send_json(args[-1], b"200 OK", {"route": name})
        return serve

    handlers = {
        "/claude-status": "_serve_claude_status",
        "/claude-usage": "_serve_claude_usage",
        "/claude-usage-store": "_serve_usage_store",
        "/codex-usage": "_serve_codex_usage",
    }
    originals = {name: getattr(gate, name) for name in handlers.values()}
    try:
        for route, name in handlers.items():
            setattr(gate, name, stub(route))
        for route in handlers:
            writer = Writer()
            await gate.handle(Reader(request("GET", route)), writer)
            status, body = response(writer)
            assert status == b"HTTP/1.1 200 OK" and json.loads(body)["route"] == route

            before = list(calls)
            writer = Writer()
            await gate.handle(Reader(request("GET", route, "other@example.test")), writer)
            status, _body = response(writer)
            assert status == b"HTTP/1.1 403 Forbidden"
            assert calls == before, (route, calls)
    finally:
        for name, original in originals.items():
            setattr(gate, name, original)
    assert calls == list(handlers)


async def test_legacy_prefs(gate, home):
    legacy = home / ".config" / "devterm" / "tabs.json"
    canonical = home / ".config" / "airlock-devterm" / "tabs.json"
    legacy.parent.mkdir(parents=True)
    legacy_bytes = b'{"order":["legacy"],"theme":"matrix"}'
    legacy.write_bytes(legacy_bytes)

    writer = Writer()
    await gate._serve_get_prefs(writer)
    status, body = response(writer)
    assert status == b"HTTP/1.1 200 OK" and body == legacy_bytes

    new = b'{"order":["canonical"],"theme":"spwk-navy"}'
    writer = Writer()
    await gate._serve_put_prefs(Reader(), {b"content-length": str(len(new)).encode()}, new, writer)
    status, body = response(writer)
    assert status == b"HTTP/1.1 200 OK" and json.loads(body) == {"ok": True}
    assert json.loads(canonical.read_bytes()) == json.loads(new)
    assert legacy.read_bytes() == legacy_bytes

    writer = Writer()
    await gate._serve_get_prefs(writer)
    _, body = response(writer)
    assert json.loads(body) == json.loads(new)


def main():
    test_font_and_notice()
    test_keep_contracts()
    test_plaintext_retirement_contract()
    with tempfile.TemporaryDirectory(prefix="devterm-parity-") as tmp:
        home = Path(tmp)
        gate = load_gate(home)
        asyncio.run(test_gate_routes(gate))
        asyncio.run(test_owner_only_status_routes(gate))
        asyncio.run(test_legacy_prefs(gate, home))
    print("ok: devterm parity (DT-C4 DT-U2 DT-N1 DT-C2 DT-R1 DT-R2 DT-A1 DT-A2 DT-N2 DT-N3 DT-C1 DT-C3 DT-S1 DT-S2)")


if __name__ == "__main__":
    main()
