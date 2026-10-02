import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
let noteId = 0;
const context = { window: {crypto: {randomUUID: () => `capture-${++noteId}`}}, document: {}, console, Date };
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
  assert.ok(quickCapturePath('inbox', fixedDate, '/notes/editor/main/').includes('Inbox/2026-09-22-'));
  assert.ok(quickCapturePath('tasks', fixedDate, '/notes/editor/main/').includes('%ED%95%A0%20%EC%9D%BC/2026-09-22-'));
  assert.ok(quickCapturePath('journal', fixedDate, '/notes/editor/main/').includes('2026-09-22/2026-09-22-'));

  // Entry formatting
  const inboxEntry = formatQuickCaptureEntry('아이디어 메모', 'inbox', fixedDate);
  assert.equal(inboxEntry, '- 아이디어 메모\n');

  const taskEntry = formatQuickCaptureEntry('릴리스 점검 완료하기', 'tasks', fixedDate);
  assert.equal(taskEntry, '- [ ] 릴리스 점검 완료하기 📅 2026-09-22\n');

  const existingTaskEntry = formatQuickCaptureEntry('- [x] 이미 완료된 작업', 'tasks', fixedDate);
  assert.equal(existingTaskEntry, '- [x] 이미 완료된 작업\n');
}

// 3. Each capture writes a distinct file; existing documents are untouched.
{
  const calls = [];
  const capture = createQuickCaptureAction({
    root: '/notes/editor/main/',
    fetchImpl: async (url, options) => {calls.push({url, options}); return {ok: true, status: 200};},
  });
  const first = await capture({text: '첫 메모', destination: 'inbox', now: fixedDate});
  const second = await capture({text: '두 번째 메모', destination: 'inbox', now: fixedDate});
  assert.notEqual(first.path, second.path);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(call => call.options.method === 'PUT' && call.url !== '/notes/editor/main/.fs/Inbox.md'));
  assert.equal(calls[0].options.body, '# 받은 메모\n\n- 첫 메모\n');
  assert.equal(calls[1].options.body, '# 받은 메모\n\n- 두 번째 메모\n');
  assert.ok(first.url.startsWith('/notes/editor/main/Inbox/'));
  assert.equal(first.url.endsWith('.md'), false);
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
  const domCtx = { window: { getSelection: () => undefined, crypto: {randomUUID: () => 'test-draft'} }, document: fakeDocument, Event, InputEvent: InputEventLike, console };
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

  // A controller and its already-rendered choices outlive local midnight.
  let clock = new Date(2026, 9, 2, 23, 59).getTime();
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  domCtx.Date = ClockDate;
  const api = domCtx.window.FolioSuggestions;
  const providers = api.defaultProviders();
  const oldDate = providers[0].items[0];
  const oldDue = providers[1].items.find(item => item.id === 'due');
  textarea.value = '';
  let capturedDate;
  const lateController = api.createController({
    root: {querySelectorAll: () => [textarea]},
    onQuickCapture: async ({now}) => { capturedDate = now; return {url: '/notes/editor/main/Inbox/saved-note'}; },
  });
  const journal = lateController.banner.children.find(button => button.dataset.starter === 'journal');
  lateController.openQuickCapture('tasks');
  clock = new Date(2026, 9, 3, 0, 1).getTime();
  assert.equal(oldDate.insert, '2026-10-03');
  assert.ok(providers[0].items[0].label.includes('2026-10-03'));
  const dueText = '- [ ] 업무 /due';
  assert.equal(api.applySuggestion(dueText, api.triggerAt(dueText, dueText.length), oldDue).text, '- [ ] 업무 📅 2026-10-03');
  journal.dispatchEvent(new Event('click'));
  assert.ok(textarea.value.startsWith('# 일지 · 2026-10-03'));
  const dialog = lateController.qcModal.children[0];
  dialog.children.find(child => child._tag === 'textarea').value = '자정 뒤 메모';
  dialog.children.at(-1).children.find(child => child.textContent === '저장').dispatchEvent(new Event('click'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(capturedDate.getDate(), 3);
  const confirmation = lateController.qcModal.children[0];
  assert.equal(confirmation.children.find(child => child._tag === 'a').href, '/notes/editor/main/Inbox/saved-note');
  lateController.destroy();
}

console.log('activation-capture: PASS');
