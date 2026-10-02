"""Real-browser regression for the CM6 insert repair (hal-3).

Serves the repo's suggestion-foundation.js plus a CodeMirror 6 harness page,
then drives real Chromium (desktop + 390px) through Playwright:
  (b) end-of-document @ insert preserves all lines,
  (c) mid-document trigger opens from the editor selection,
  (d) one Ctrl-Z restores the exact pre-insert document,
  (e) Korean IME composition never opens the menu mid-syllable,
  (f) the mobile '@ 날짜' button inserts through the same transaction path.
Fails on any console error / pageerror.
"""
import datetime
import functools
import http.server
import json
import os
import sys
import threading

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EDITOR_JS = os.path.join(REPO_ROOT, "apps", "notes", "editor", "suggestion-foundation.js")
HARNESS_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "cm6-harness.html")
INDEX_JSON = json.dumps({"files": [{"name": "Inbox.md"}, {"name": "회의록.md"}]})
TODAY = datetime.date.today().strftime("%Y-%m-%d")
ORIGINAL = "# 회의록\n첫 줄 내용\n둘째 줄 "


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/editor/suggestion-foundation.js":
            with open(EDITOR_JS, encoding="utf-8") as f:
                self._send(f.read(), "application/javascript")
        elif path == "/harness.html":
            with open(HARNESS_HTML, encoding="utf-8") as f:
                self._send(f.read(), "text/html; charset=utf-8")
        elif path == "/.fs":
            self._send(INDEX_JSON, "application/json")
        else:
            self.send_response(404)
            self.end_headers()


def check(name, actual, expected):
    if actual != expected:
        print(f"FAIL {name}: expected {expected!r}, got {actual!r}")
        return False
    print(f"ok {name}")
    return True


def run_viewport(width, height, mobile):
    from playwright.sync_api import sync_playwright

    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": height})
        pg = ctx.new_page()
        errors = []
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.goto(f"{BASE}/harness.html?mode=late", wait_until="domcontentloaded")
        try:
            pg.wait_for_function("window.harnessReady === true", timeout=30000)
        except Exception:
            # The pinned esm.sh CodeMirror bundle is unreachable (hermetic
            # environment). Skip instead of failing: pinning keeps this
            # deterministic wherever the network exists.
            print("SKIP viewport (esm.sh unreachable)")
            browser.close()
            return True
        ok &= check("overlay booted", pg.evaluate("!!window.FolioSuggestions"), True)
        ok &= check("overlay attached late editor",
                    pg.evaluate("!document.querySelector('.folio-mobile-bar').hidden"), True)
        pg.wait_for_selector(".cm-content[contenteditable='true']", timeout=10000)

        focus_end = ("window.view.focus(); window.view.dispatch("
                     "{selection:{anchor:window.view.state.doc.length}})")
        doc = lambda: pg.evaluate("window.view.state.doc.toString()")  # noqa: E731
        menu_open = lambda: pg.evaluate(  # noqa: E731
            "!document.querySelector('.folio-suggestion-menu').hidden")
        menu_items = lambda: pg.evaluate(  # noqa: E731
            "[...document.querySelectorAll('.folio-suggestion-menu button')].map(b=>b.textContent)")

        # (b) end-of-document @ insert
        pg.evaluate(focus_end)
        pg.keyboard.type("@to", delay=40)
        pg.wait_for_function("!document.querySelector('.folio-suggestion-menu').hidden",
                             timeout=5000)
        items = menu_items()
        ok &= check("menu offers today", any(TODAY in i for i in items), True)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        after = doc()
        ok &= check("end insert text", after, ORIGINAL + "@to".replace("@to", TODAY))
        ok &= check("end insert keeps 3 lines", after.count("\n"), 2)

        # (d) one Ctrl-Z restores the exact original
        pg.keyboard.press("Control+z")
        pg.wait_for_timeout(500)
        ok &= check("undo restores original", doc(), ORIGINAL)

        # (c) mid-document trigger (line 2 end) inserts at the selection
        pg.evaluate("window.view.focus(); window.view.dispatch("
                    "{selection:{anchor:window.view.state.doc.line(2).to}})")
        pg.keyboard.type(" @to", delay=40)
        pg.wait_for_function("!document.querySelector('.folio-suggestion-menu').hidden",
                             timeout=5000)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        mid = doc()
        lines = mid.split("\n")
        ok &= check("mid keeps 3 lines", len(lines), 3)
        ok &= check("mid line 1 intact", lines[0], "# 회의록")
        ok &= check("mid line 2 inserted", lines[1], f"첫 줄 내용 {TODAY}")
        ok &= check("mid line 3 intact", lines[2], "둘째 줄 ")

        # An already-open menu must not apply old offsets to a model loaded
        # without an input event. Click in the same turn, before observers run.
        pg.evaluate(focus_end)
        pg.keyboard.type(" @to", delay=40)
        pg.wait_for_function("!document.querySelector('.folio-suggestion-menu').hidden")
        replacement = "소중한 원문 전체입니다"
        pg.evaluate("""text => {
          const stale = document.querySelector('.folio-suggestion-menu button');
          window.view.dispatch({changes: {from: 0, to: window.view.state.doc.length, insert: text}});
          stale.click();
        }""", replacement)
        ok &= check("stale menu preserves loaded document", doc(), replacement)

        pg.evaluate(focus_end)
        pg.keyboard.type(" @to", delay=40)
        pg.wait_for_function("!document.querySelector('.folio-suggestion-menu').hidden")
        before_move = doc()
        pg.evaluate("""() => {
          const stale = document.querySelector('.folio-suggestion-menu button');
          window.view.dispatch({selection: {anchor: 0}});
          stale.click();
        }""")
        ok &= check("stale menu preserves text after cursor move", doc(), before_move)
        pg.evaluate(focus_end)

        # (e) IME composition: no menu mid-syllable, menu after commit
        pg.evaluate(focus_end)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('.cm-content')"
                    ".dispatchEvent(new Event('compositionstart'))")
        pg.keyboard.type("/할", delay=40)
        pg.wait_for_timeout(400)
        ok &= check("no menu while composing", menu_open(), False)
        pg.evaluate("document.querySelector('.cm-content')"
                    ".dispatchEvent(new Event('compositionend'))")
        pg.wait_for_function("!document.querySelector('.folio-suggestion-menu').hidden",
                             timeout=5000)
        ok &= check("menu filters after commit",
                    pg.evaluate("[...document.querySelectorAll("
                               "'.folio-suggestion-menu button')].map(b=>b.dataset.id)"),
                    ["todo", "due", "due-custom", "due-tomorrow"])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        if mobile:
            # (f) mobile trigger button shares the transaction path
            pg.evaluate(focus_end)
            before = doc()
            pg.click("text=@ 날짜")
            pg.wait_for_timeout(500)
            ok &= check("mobile @ inserts at cursor",
                        doc(), before + " @")
            ok &= check("mobile keeps lines", doc().count("\n"), before.count("\n"))
            ok &= check("mobile opens menu", menu_open(), True)

        ok &= check("console errors", errors, [])
        browser.close()
    return ok


def run_empty_banner():
    from playwright.sync_api import sync_playwright

    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        try:
            pg.goto(f"{BASE}/harness.html?mode=late&doc=empty", wait_until="domcontentloaded")
            pg.wait_for_function("window.harnessReady === true", timeout=30000)
        except Exception:
            print("SKIP viewport (esm.sh unreachable)")
            browser.close()
            return True
        pg.wait_for_function("!document.querySelector('.folio-mobile-bar').hidden", timeout=10000)
        ok &= check("late attach shows starter banner",
                    pg.evaluate("!document.querySelector('.folio-activation-banner').hidden"), True)
        ok &= check("banner offers three starters",
                    pg.evaluate("document.querySelectorAll('.folio-activation-btn').length"), 3)
        # A model-driven late document load emits no DOM input. Clicking
        # the stale button in that same turn must preserve the loaded text.
        loaded = "# 기존 문서\n보존할 본문"
        pg.evaluate("""text => {
          const stale = document.querySelector('[data-starter="blank"]');
          window.view.dispatch({changes: {from: 0, to: window.view.state.doc.length, insert: text}});
          stale.click();
        }""", loaded)
        ok &= check("stale starter preserves loaded document",
                    pg.evaluate("window.view.state.doc.toString()"), loaded)
        pg.wait_for_function("document.querySelector('.folio-activation-banner').hidden")
        ok &= check("model update hides starter", pg.evaluate("document.querySelector('.folio-activation-banner').hidden"), True)
        ok &= check("console errors", errors, [])
        browser.close()
    return ok


def run_quick_capture():
    from playwright.sync_api import sync_playwright
    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        errors, pending = [], []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.route("**/.fs/**", lambda route: pending.append(route))
        pg.goto(f"{BASE}/harness.html?mode=late", wait_until="domcontentloaded")
        pg.wait_for_function("window.harnessReady === true", timeout=30000)
        pg.wait_for_selector('.folio-mobile-bar:not([hidden])')
        open_modal = lambda: pg.click('text=+ 빠른 메모')
        save = lambda: pg.get_by_role('button', name='저장', exact=True).click()
        open_modal()
        pg.locator('.folio-qc-input').fill('first draft')
        save()
        pg.wait_for_timeout(100)
        ok &= check('capture begins one request', len(pending), 1)
        # A second click during the same save is ignored, even if invoked
        # directly rather than through the disabled native button.
        pg.evaluate("document.querySelector('.folio-qc-save-btn').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        pg.wait_for_timeout(100)
        ok &= check('pending save has no duplicate request', len(pending), 1)
        pg.get_by_role('button', name='취소', exact=True).click()
        open_modal()
        pg.locator('.folio-qc-input').fill('second unsaved draft')
        pending.pop(0).fulfill(status=200, body='')
        pg.wait_for_timeout(100)
        ok &= check('old response preserves reopened draft', pg.locator('.folio-qc-input').input_value(), 'second unsaved draft')
        save()
        pg.wait_for_timeout(100)
        ok &= check('new draft begins its own save', len(pending), 1)
        pending.pop(0).fulfill(status=503, body='')
        pg.wait_for_timeout(100)
        ok &= check('failed save preserves draft', pg.locator('.folio-qc-input').input_value(), 'second unsaved draft')
        ok &= check('failed save re-enables button', pg.locator('.folio-qc-save-btn').is_enabled(), True)
        ok &= check('failed save shows retry error', pg.get_by_role('alert').is_visible(), True)
        save()
        pg.wait_for_timeout(100)
        ok &= check('retry sends one request', len(pending), 1)
        pending.pop(0).fulfill(status=200, body='')
        pg.wait_for_timeout(100)
        ok &= check('saved page has an open link', pg.locator('.folio-quick-capture-dialog a').count(), 1)
        pg.keyboard.press('Escape')
        ok &= check('capture confirmation closes with Escape', pg.locator('.folio-quick-capture-modal').is_visible(), False)
        open_modal()
        pg.keyboard.press('Escape')
        ok &= check('capture textarea closes with Escape', pg.locator('.folio-quick-capture-modal').is_visible(), False)
        ok &= check('quick capture has no unhandled errors', errors, [])
        browser.close()
    return ok


def run_mobile_after_capture_cancel(touch):
    from playwright.sync_api import sync_playwright
    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=touch, has_touch=touch)
        errors = []
        pg.on("pageerror", lambda error: errors.append(str(error)))
        pg.goto(f"{BASE}/harness.html?mode=late", wait_until="domcontentloaded")
        pg.wait_for_function("window.harnessReady === true", timeout=30000)
        pg.wait_for_selector('.folio-mobile-bar:not([hidden])')
        pg.get_by_role('button', name='+ 빠른 메모', exact=True).click()
        pg.locator('.folio-qc-input').fill('capture draft')
        pg.get_by_role('button', name='취소', exact=True).click()
        original = "# 회의록\n첫 줄 내용\n둘째 줄 "
        for label in ['@ 날짜', '/ 기능', '[[ 연결']:
            pg.evaluate("""text => {
              window.view.dispatch({changes:{from:0,to:window.view.state.doc.length,insert:text}});
              window.view.dispatch({selection:{anchor:window.view.state.doc.line(2).to}});
              window.view.focus();
            }""", original)
            button = pg.get_by_role('button', name=label, exact=True)
            if touch: button.tap()
            else: button.click()
            pg.wait_for_selector('.folio-suggestion-menu:not([hidden]) button')
            choice = pg.locator('.folio-suggestion-menu button').first
            if touch: choice.tap()
            else: choice.click()
            value = pg.evaluate('window.view.state.doc.toString()')
            lines = value.split('\n')
            ok &= check(f'{label} selects visible editor after cancel (touch={touch})', len(lines) == 3 and lines[0] == '# 회의록' and lines[2] == '둘째 줄 ' and lines[1] != '첫 줄 내용', True)
            ok &= check('hidden capture draft remains untouched', pg.locator('.folio-qc-input').input_value(), 'capture draft')
        ok &= check('mobile cancel has no unhandled errors', errors, [])
        browser.close()
    return ok


if __name__ == "__main__":
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP cm6-insert-browser: playwright not installed")
        sys.exit(0)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    BASE = f"http://127.0.0.1:{srv.server_address[1]}"

    all_ok = True
    print("== late attach arms the starter banner on an empty doc ==")
    all_ok &= run_empty_banner()
    print("== viewport desktop 1280x800 ==")
    all_ok &= run_viewport(1280, 800, mobile=False)
    print("== viewport mobile 390x844 ==")
    all_ok &= run_viewport(390, 844, mobile=True)
    print("== quick capture delayed responses and retry ==")
    all_ok &= run_quick_capture()
    all_ok &= run_mobile_after_capture_cancel(False)
    all_ok &= run_mobile_after_capture_cancel(True)
    print("cm6-insert-browser: " + ("PASS" if all_ok else "FAIL"))
    sys.exit(0 if all_ok else 1)
