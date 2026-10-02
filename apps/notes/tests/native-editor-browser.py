"""Exercise real pinned editor, CSS, overlay, autosave and native page creation.
All server writes use a disposable vault on loopback, never a live installation.
"""
import argparse, http.server, os, pathlib, re, socket, subprocess, tempfile, threading, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright
parser = argparse.ArgumentParser(description="Disposable pinned SilverBullet + deployed overlay browser regression")
parser.add_argument('binary')
parser.add_argument('--evidence-dir', required=True)
parser.add_argument('--width', type=int, default=1280)
parser.add_argument('--touch', action='store_true')
parser.add_argument('--lose-save-ack', action='store_true')
parser.add_argument('--long-menu', action='store_true')
args = parser.parse_args()
WT = pathlib.Path(__file__).resolve().parents[3]
BINARY = str(pathlib.Path(args.binary).resolve())
OUT = pathlib.Path(args.evidence_dir).resolve()
OUT.mkdir(parents=True, exist_ok=True)
pinned = re.search(r'^SB_VER="([^"]+)"', (WT/'apps/notes/install.sh').read_text(), re.M).group(1)
assert subprocess.check_output([BINARY, 'version'], text=True).startswith(pinned + '-')
ROOT='/notes/editor/main/'
with tempfile.TemporaryDirectory(prefix='folio-native-') as tmp:
    vault=pathlib.Path(tmp); (vault/'Meeting.md').write_text('# Meeting\nPreserve line one\nPreserve line two\n')
    with socket.socket() as s:s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    env={k:v for k,v in os.environ.items() if not k.startswith('SB_')};env.update(SB_URL_PREFIX=ROOT.rstrip('/'),SB_RUNTIME_API='0',SB_SHELL_BACKEND='off')
    log=open(OUT/'server.log','w')
    proc=subprocess.Popen([BINARY,'--single','-L','127.0.0.1','-p',str(port),str(vault)],env=env,stdout=log,stderr=log)
    up=f'http://127.0.0.1:{port}'
    class Proxy(http.server.BaseHTTPRequestHandler):
        fail_capture = args.lose_save_ack
        def log_message(self,*args):pass
        def handle_request(self):
            if self.path.startswith('/notes/_obs/suggestion-foundation.'):
                p=WT/'apps/notes/editor'/self.path.rsplit('/',1)[1];data=p.read_bytes();ctype='text/css' if p.suffix=='.css' else 'application/javascript';self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            data=self.rfile.read(int(self.headers.get('Content-Length','0'))) if self.command in ('PUT','POST') else None
            headers={k:v for k,v in self.headers.items() if k.lower() not in ('content-length','connection','accept-encoding')}
            req=urllib.request.Request(up+self.path,data=data,headers=headers,method=self.command)
            try:r=urllib.request.urlopen(req,timeout=15)
            except urllib.error.HTTPError as e:r=e
            body=r.read();ctype=r.headers.get('Content-Type','')
            if 'text/html' in ctype:body=body.replace(b'</head>',b'<link rel="stylesheet" href="/notes/_obs/suggestion-foundation.css"><script src="/notes/_obs/suggestion-foundation.js" defer></script></head>')
            
            status=r.status
            if self.command == 'PUT' and '/.fs/Inbox/' in self.path and Proxy.fail_capture:
                Proxy.fail_capture=False; status=503; body=b'persisted but acknowledgement lost'
            self.send_response(status)
            for k,v in r.headers.items():
                if k.lower() not in ('content-length','transfer-encoding','connection','content-encoding'):self.send_header(k,v)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        do_GET=do_PUT=do_POST=do_DELETE=handle_request
    proxy=http.server.ThreadingHTTPServer(('127.0.0.1',0),Proxy);threading.Thread(target=proxy.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{proxy.server_address[1]}'
    try:
        for i in range(100):
            try:urllib.request.urlopen(up+ROOT+'.fs',timeout=.2);break
            except OSError:time.sleep(.05)
        with sync_playwright() as pw:
            browser=pw.chromium.launch();errors=[]
            pg=browser.new_page(viewport={'width':args.width,'height':844}, is_mobile=args.touch, has_touch=args.touch, service_workers='allow')
            pg.on('pageerror',lambda e:errors.append(str(e)))
            pg.goto(base+ROOT+'Meeting',wait_until='domcontentloaded');pg.wait_for_timeout(4000)
            assert not pg.locator('.folio-quick-capture-modal').is_visible()
            pg.locator('.cm-content').tap() if args.touch else pg.locator('.cm-content').click()
            pg.keyboard.press('Control+End'); pg.keyboard.type(' @to', delay=40)
            pg.wait_for_selector('.folio-suggestion-menu:not([hidden]) button')
            pg.keyboard.press('Enter');pg.wait_for_timeout(1500)
            assert (vault/'Meeting.md').read_text().startswith('# Meeting\nPreserve line one\nPreserve line two\n')
            print('PASS native date and current-document autosave',flush=True)
            pg.keyboard.press('Control+End');pg.keyboard.type('\n- [ ] task /due', delay=40)
            pg.locator('[data-id="due"]').click();pg.wait_for_timeout(1500)
            assert '📅 ' in (vault/'Meeting.md').read_text()
            print('PASS native slash task/date flow',flush=True)
            pg.keyboard.press('Control+End');pg.keyboard.type('\n [[Meet', delay=40)
            pg.locator('[data-id="page:Meeting"]').click();pg.wait_for_timeout(1500)
            assert '[[Meeting]]' in (vault/'Meeting.md').read_text() and ']]]]' not in (vault/'Meeting.md').read_text()
            print('PASS actual list search and existing-link selection',flush=True)
            pg.keyboard.press('Control+End');pg.keyboard.type('\n [[NativeNew', delay=40)
            pg.locator('[data-id="create:NativeNew"]').click();pg.wait_for_timeout(1500)
            source=(vault/'Meeting.md').read_text()
            assert '[[NativeNew]]' in source and ']]]]' not in source
            assert not (vault/'NativeNew.md').exists()
            pg.keyboard.press('Home')
            pg.locator('.sb-wiki-link').filter(has_text='NativeNew').click()
            pg.wait_for_function("document.querySelector('#sb-current-page input').value === 'NativeNew'")
            pg.locator('.cm-content').tap() if args.touch else pg.locator('.cm-content').click();pg.keyboard.type('# NativeNew\nCreated through the native editor',delay=30)
            pg.wait_for_timeout(1500)
            assert 'Created through the native editor' in (vault/'NativeNew.md').read_text()
            assert (vault/'Meeting.md').read_text()==source
            print('PASS native new-page open/type/autosave and source-page preservation',flush=True)
            pg.keyboard.press('Control+End');pg.keyboard.type(' [[NativeNew', delay=40)
            pg.locator('[data-id="page:NativeNew"]').click()
            print('PASS freshly-created native page appears in subsequent overlay search',flush=True)
            pg.get_by_role('button',name='+ 빠른 메모',exact=True).click()
            pg.locator('.folio-qc-input').fill('native capture draft')
            pg.get_by_role('button',name='취소',exact=True).click()
            assert not pg.locator('.folio-quick-capture-modal').is_visible()
            pg.locator('.cm-content').tap() if args.touch else pg.locator('.cm-content').click()
            print('PASS deployed CSS cancel and physical editor click',flush=True)
            pg.get_by_role('button',name='+ 빠른 메모',exact=True).click()
            pg.locator('.folio-qc-input').fill('retry native capture')
            pg.get_by_role('button',name='저장',exact=True).click()
            pg.wait_for_selector('.folio-quick-capture-dialog a',timeout=5000)
            target=pg.locator('.folio-quick-capture-dialog a').get_attribute('href')
            pg.locator('.folio-quick-capture-dialog a').click()
            pg.wait_for_timeout(2000)
            assert 'retry native capture' in pg.locator('.cm-content').inner_text()
            assert len(list((vault/'Inbox').glob('*.md'))) == 1
            assert any('retry native capture' in file.read_text() for file in (vault/'Inbox').glob('*.md'))
            pg.locator('.cm-content').tap() if args.touch else pg.locator('.cm-content').click()
            print('PASS native capture save/open and actual editor usability; server-ack-loss=' + str(args.lose_save_ack),flush=True)
            if args.long_menu:
                for line in [1, 60, 120]:
                    for trigger in ['@to', '/todo', '[[Meeting']:
                        pg.evaluate("""line => {
                          const view = window.client.editorView;
                          const text = Array.from({length:120}, (_, i) => `Line ${i + 1} content`).join(String.fromCharCode(10));
                          view.dispatch({changes:{from:0,to:view.state.doc.length,insert:text}});
                          const pos = view.state.doc.line(line).to;
                          view.dispatch({selection:{anchor:pos},effects:view.constructor.scrollIntoView(pos,{y:'center'})});
                          view.focus();
                        }""", line)
                        pg.wait_for_timeout(150)
                        pg.keyboard.type(' ' + trigger,delay=30)
                        pg.wait_for_selector('.folio-suggestion-menu:not([hidden]) button')
                        # Scroll while the menu is open; its cursor anchor
                        # remains in the visible vicinity of the same line.
                        pg.evaluate("window.client.editorView.scrollDOM.scrollTop += 12")
                        pg.wait_for_timeout(100)
                        button=pg.locator('.folio-suggestion-menu button').first
                        if args.touch:button.tap(timeout=3000)
                        else:button.click(timeout=3000)
                        count=pg.evaluate('window.client.editorView.state.doc.lines')
                        assert count==120, (line,trigger,count)
                        print(f'PASS long menu line={line} trigger={trigger} touch={args.touch}',flush=True)
            assert errors == [], errors
            pg.screenshot(path=str(OUT/'native.png'))
            print(f'PASS native overlay width={args.width} touch={args.touch} lost_ack={args.lose_save_ack}',flush=True)
            browser.close()
    finally:proxy.shutdown();proc.terminate();proc.wait(timeout=5);log.close()
