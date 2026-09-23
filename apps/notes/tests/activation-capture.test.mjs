import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
const context = { window: {}, document: {}, console, Date };
vm.runInNewContext(source, context);
const {
  starterTemplates,
  isDocumentEmpty,
  applyStarter,
  QUICK_CAPTURE_DESTINATIONS,
  formatQuickCaptureEntry,
  quickCapturePath,
  createQuickCaptureAction,
  createController,
} = context.window.FolioSuggestions;

const fixedDate = new Date(2026, 8, 22); // 2026-09-22

// 1. Starter templates for empty pages: blank, template, daily journal
{
  const templates = starterTemplates(fixedDate);
  assert.ok(templates.blank);
  assert.ok(templates.template);
  assert.ok(templates.journal);

  assert.equal(templates.blank.label, '빈 문서');
  assert.equal(templates.template.label, '템플릿');
  assert.ok(templates.template.content.includes('# 회의록'));
  assert.equal(templates.journal.label, '오늘 일지');
  assert.ok(templates.journal.content.includes('# 일지 · 2026-09-22'));

  // isDocumentEmpty accurately detects empty and near-empty states
  assert.equal(isDocumentEmpty(''), true);
  assert.equal(isDocumentEmpty('   \n  '), true);
  assert.equal(isDocumentEmpty('# 제목만 있는 문서'), true);
  assert.equal(isDocumentEmpty('# 제목\n본문이 시작됨'), false);

  // applyStarter applies chosen template
  const journalResult = applyStarter('', 'journal', { now: fixedDate });
  assert.equal(journalResult.starter, 'journal');
  assert.ok(journalResult.text.startsWith('# 일지 · 2026-09-22'));

  const templateResult = applyStarter('', 'template', { now: fixedDate });
  assert.ok(templateResult.text.includes('## 다음 할 일'));
}

// 2. Quick Capture entry formatting and path resolution
{
  // Default destination is inbox
  assert.equal(QUICK_CAPTURE_DESTINATIONS[0].id, 'inbox');
  assert.equal(QUICK_CAPTURE_DESTINATIONS[0].label, '받은 메모');

  // Path resolution
  assert.ok(quickCapturePath('inbox', fixedDate, '/notes/editor/main/').endsWith('Inbox.md'));
  assert.ok(quickCapturePath('tasks', fixedDate, '/notes/editor/main/').includes('%ED%95%A0%20%EC%9D%BC.md'));
  assert.ok(quickCapturePath('journal', fixedDate, '/notes/editor/main/').includes('2026-09-22.md'));

  // Entry formatting
  const inboxEntry = formatQuickCaptureEntry('아이디어 메모', 'inbox', fixedDate);
  assert.equal(inboxEntry, '- 아이디어 메모\n');

  const taskEntry = formatQuickCaptureEntry('릴리스 점검 완료하기', 'tasks', fixedDate);
  assert.equal(taskEntry, '- [ ] 릴리스 점검 완료하기 📅 2026-09-22\n');

  const existingTaskEntry = formatQuickCaptureEntry('- [x] 이미 완료된 작업', 'tasks', fixedDate);
  assert.equal(existingTaskEntry, '- [x] 이미 완료된 작업\n');
}

// 3. Quick Capture persistence flow: GET existing (or 404), append entry, PUT
{
  const calls = [];
  const capture = createQuickCaptureAction({
    root: '/notes/editor/main/',
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      if (options.method === 'GET') {
        return { ok: false, status: 404 }; // first time, creates new file
      }
      return { ok: true, status: 200 };
    },
  });

  const res = await capture({ text: '첫 빠른 메모', destination: 'inbox', now: fixedDate });
  assert.equal(res.ok, true);
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[1].options.method, 'PUT');
  assert.ok(calls[1].options.body.includes('# 받은 메모\n\n- 첫 빠른 메모\n'));

  // Appending to existing content
  const calls2 = [];
  const captureExisting = createQuickCaptureAction({
    root: '/notes/editor/main/',
    fetchImpl: async (url, options) => {
      calls2.push({ url, options });
      if (options.method === 'GET') {
        return { ok: true, status: 200, text: async () => '# 받은 메모\n\n- 이전 메모\n' };
      }
      return { ok: true, status: 200 };
    },
  });

  await captureExisting({ text: '두 번째 메모', destination: 'inbox', now: fixedDate });
  assert.equal(calls2[1].options.body, '# 받은 메모\n\n- 이전 메모\n- 두 번째 메모\n');
}

// 4. DOM integration: activation banner, mobile action bar, quick capture modal
{
  class FakeElement extends EventTarget {
    constructor(tag) {
      super();
      this._tag = tag;
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.style = {};
      this.hidden = false;
      this.className = '';
      this.textContent = '';
      if (tag === 'textarea' || tag === 'input') this.value = '';
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...nodes) { this.children = nodes; }
    remove() {}
    getBoundingClientRect() { return { left: 0, right: 0, top: 0, bottom: 0 }; }
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  }

  const body = new FakeElement('body');
  const fakeDocument = { body, createElement: (tag) => new FakeElement(tag) };
  class InputEventLike extends Event {
    constructor(type, opts = {}) { super(type, opts); this.inputType = opts.inputType; }
  }
  const domCtx = { window: { getSelection: () => undefined }, document: fakeDocument, Event, InputEvent: InputEventLike, console };
  vm.runInNewContext(source, domCtx);

  const container = new FakeElement('div');
  const textarea = new FakeElement('textarea');
  container.appendChild(textarea);

  const controller = domCtx.window.FolioSuggestions.createController({
    root: { querySelectorAll: () => [textarea] },
    now: fixedDate,
  });

  // Empty document shows activation banner
  assert.equal(controller.banner.hidden, false);
  const starterButtons = controller.banner.children.filter((c) => c._tag === 'button');
  assert.equal(starterButtons.length, 3);

  // Clicking template applies template content and hides banner
  starterButtons[1].dispatchEvent(new Event('click'));
  assert.ok(textarea.value.includes('# 회의록'));
  assert.equal(controller.banner.hidden, true);

  // Mobile action bar is rendered with touchable buttons
  assert.ok(controller.mobileBar.children.length >= 4);
  const mobileQcBtn = controller.mobileBar.children.find((c) => c.textContent === '+ 빠른 메모');
  assert.ok(mobileQcBtn);

  // Opening quick capture displays modal
  controller.openQuickCapture();
  assert.equal(controller.qcModal.hidden, false);

  // Escape closes quick capture modal
  const escEvent = new Event('keydown', { cancelable: true });
  escEvent.key = 'Escape';
  textarea.dispatchEvent(escEvent);
  assert.equal(controller.qcModal.hidden, true);

  controller.destroy();
}

console.log('activation-capture: PASS');
