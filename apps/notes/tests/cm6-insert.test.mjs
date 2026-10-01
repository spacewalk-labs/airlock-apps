import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Regression for the SilverBullet/CodeMirror 6 insert repair: writes must go
// through one editor transaction at the cursor (never a wholesale
// contenteditable rewrite), the trigger must be read from the editor
// selection, and mobile buttons must share the same path.

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
const equalJson = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

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
  querySelectorAll(selectorList) { return matchAll(this, selectorList); }
}

function matchesSelector(el, part) {
  if (part === 'textarea') return el._tag === 'textarea';
  if (part === 'input[type="text"]') return el._tag === 'input' && el.attributes.type === 'text';
  if (part === '[contenteditable="true"]') return el.attributes.contenteditable === 'true';
  return false;
}

function matchAll(root, selectorList) {
  const parts = selectorList.split(',').map((part) => part.trim());
  const out = [];
  (function visit(node) {
    for (const child of node.children) {
      if (parts.some((part) => matchesSelector(child, part))) out.push(child);
      visit(child);
    }
  })(root);
  return out;
}

// Minimal CodeMirror 6 EditorView stand-in: a document string, a selection
// head, and an undoable dispatch log. One dispatch === one native undo step.
function makeFakeView(text, head, { contained = true } = {}) {
  const history = [text];
  const view = {
    _text: text,
    _head: head,
    dispatches: [],
    focused: false,
    dom: { contains: () => contained },
    state: {
      doc: { toString: () => view._text, get length() { return view._text.length; } },
      selection: { main: { get head() { return view._head; } } },
    },
    dispatch(tr) {
      view.dispatches.push(tr);
      history.push(view._text);
      const { from, to, insert } = tr.changes;
      view._text = view._text.slice(0, from) + insert + view._text.slice(to);
      view._head = tr.selection ? tr.selection.anchor : from + insert.length;
    },
    undo() { view._text = history.pop() ?? view._text; },
    focus() { view.focused = true; },
  };
  return view;
}

function loadModule(view, overrides = {}) {
  const body = new FakeElement('body');
  const fakeDocument = { body, createElement: (tag) => new FakeElement(tag), querySelectorAll: (sel) => matchAll(body, sel) };
  if (overrides.createRange) fakeDocument.createRange = overrides.createRange;
  if (overrides.createTextNode) fakeDocument.createTextNode = overrides.createTextNode;
  const fakeWindow = { getSelection: overrides.getSelection || (() => undefined) };
  if (view) fakeWindow.client = { editorView: view };
  const ctx = { window: fakeWindow, document: fakeDocument, Event, console, queueMicrotask };
  vm.runInNewContext(source, ctx);
  return { FolioSuggestions: ctx.window.FolioSuggestions, document: fakeDocument, window: fakeWindow };
}

const providers = [
  { trigger: '@', items: [{ id: 'today', label: '오늘 · 2026-10-01', insert: '[[2026-10-01]]' }] },
];

function mountEditor(view) {
  const { FolioSuggestions, document: fakeDocument } = loadModule(view);
  const container = fakeDocument.createElement('div');
  fakeDocument.body.appendChild(container);
  const editor = fakeDocument.createElement('div');
  editor.setAttribute('contenteditable', 'true');
  container.appendChild(editor);
  const controller = FolioSuggestions.createController({ root: container, providers });
  const popup = fakeDocument.body.children[fakeDocument.body.children.length - 1];
  return { controller, editor, popup };
}

const input = async (target) => {
  target.dispatchEvent(new Event('input'));
  // Editor-backed targets re-read view.state one microtask later (CodeMirror
  // folds the keystroke in after the synchronous listeners run).
  await Promise.resolve();
};
const keydown = (target, key) => {
  const event = new Event('keydown', { cancelable: true });
  event.key = key;
  target.dispatchEvent(event);
  return event;
};

// spanForReplace: every write carries the same minimal single-span edit.
{
  const { FolioSuggestions } = loadModule(null);
  const { spanForReplace } = FolioSuggestions;
  const cases = [
    ['a @to b', 'a [[2026-10-01]] b'],
    ['- [ ] x', '- [ ] x 📅 2026-10-01'],
    ['abc', 'xyz'],
    ['ab', 'abc'],
    ['ab', 'ab'],
    ['# 회의록\n첫 줄 내용\n둘째 줄 @', '# 회의록\n첫 줄 내용\n둘째 줄 [[2026-10-01]]'],
  ];
  for (const [oldText, newText] of cases) {
    const span = spanForReplace(oldText, newText);
    assert.equal(oldText.slice(0, span.from) + span.insert + oldText.slice(span.to), newText);
  }
  equalJson(spanForReplace('a @to b', 'a [[2026-10-01]] b'), { from: 2, to: 5, insert: '[[2026-10-01]]' });
  console.log('cm6-insert: PASS spanForReplace reconstructs every replacement');
}

// resolveEditorView: only a live CodeMirror view containing the target.
{
  const { FolioSuggestions, window: fakeWindow } = loadModule(null);
  const { resolveEditorView } = FolioSuggestions;
  const target = new FakeElement('div');
  assert.equal(resolveEditorView(target), null);
  fakeWindow.client = {};
  assert.equal(resolveEditorView(target), null);
  const view = makeFakeView('hi', 2);
  fakeWindow.client = { editorView: view };
  assert.equal(resolveEditorView(target), view);
  const foreign = makeFakeView('hi', 2, { contained: false });
  fakeWindow.client = { editorView: foreign };
  assert.equal(resolveEditorView(target), null);
  fakeWindow.client = { editorView: { state: { doc: {} } } };
  assert.equal(resolveEditorView(target), null);
  console.log('cm6-insert: PASS resolveEditorView gates on a containing editor view');
}

// End-of-document insert: one transaction at the cursor, lines preserved,
// one undo step back to the exact original.
{
  const before = '# 회의록\n첫 줄 내용\n둘째 줄 @';
  const view = makeFakeView(before, before.length);
  const { editor, popup } = mountEditor(view);
  await input(editor);
  assert.equal(popup.hidden, false);
  assert.equal(popup.children.length, 1);
  const event = keydown(editor, 'Enter');
  assert.equal(event.defaultPrevented, true);
  assert.equal(view.dispatches.length, 1);
  equalJson(view.dispatches[0].changes, { from: before.length - 1, to: before.length, insert: '[[2026-10-01]]' });
  assert.equal(view._text, '# 회의록\n첫 줄 내용\n둘째 줄 [[2026-10-01]]');
  assert.equal(view._text.split('\n').length, 3);
  assert.equal(view._head, before.length - 1 + '[[2026-10-01]]'.length);
  view.undo();
  assert.equal(view._text, before, 'a single undo step must restore the pre-insert document');
  console.log('cm6-insert: PASS end-of-document insert is one transaction and undoes cleanly');
}

// Mid-document trigger: the menu opens from the editor selection, and only
// the trigger line changes.
{
  const before = '첫 줄\n둘째 줄 @\n셋째 줄';
  const head = before.indexOf('@') + 1;
  const view = makeFakeView(before, head);
  const { editor, popup } = mountEditor(view);
  await input(editor);
  assert.equal(popup.hidden, false, 'mid-document trigger must open from the selection, not the text end');
  keydown(editor, 'Enter');
  const lines = view._text.split('\n');
  assert.equal(lines.length, 3);
  assert.equal(lines[0], '첫 줄');
  assert.equal(lines[1], '둘째 줄 [[2026-10-01]]');
  assert.equal(lines[2], '셋째 줄');
  console.log('cm6-insert: PASS mid-document trigger inserts at the selection');
}

// Mobile trigger button shares the insert path (transaction, not value swap).
{
  const before = '메모 ';
  const view = makeFakeView(before, before.length);
  const { controller } = mountEditor(view);
  assert.equal(controller.mobileBar.hidden, false);
  const atButton = controller.mobileBar.children.find((c) => c.textContent === '@ 날짜');
  assert.ok(atButton);
  atButton.dispatchEvent(new Event('click'));
  assert.equal(view.dispatches.length, 1);
  equalJson(view.dispatches[0].changes, { from: before.length, to: before.length, insert: '@' });
  assert.equal(view._text, '메모 @');
  console.log('cm6-insert: PASS mobile trigger button inserts through the editor transaction');
}

// Korean IME: composing input must not open or re-filter the menu.
{
  const view = makeFakeView('@', 1);
  const { editor, popup } = mountEditor(view);
  await input(editor);
  assert.equal(popup.hidden, false);
  editor.dispatchEvent(new Event('compositionstart'));
  view._text = '@할';
  view._head = 2;
  await input(editor);
  assert.equal(popup.children.length, 1, 'interim IME input must not re-filter the menu');
  const event = keydown(editor, 'Escape');
  assert.equal(event.defaultPrevented, false, 'Escape belongs to the IME while composing');
  console.log('cm6-insert: PASS IME composition boundary on editor targets');
}

// Contract: a contenteditable without an editor view is never rewritten
// wholesale — defaultInsert reports 'noop' instead of touching textContent.
{
  const { FolioSuggestions, document: fakeDocument } = loadModule(null);
  const plain = fakeDocument.createElement('div');
  plain.setAttribute('contenteditable', 'true');
  plain.textContent = '둘째 줄 @';
  const how = FolioSuggestions.defaultInsert({
    target: plain,
    result: { text: '둘째 줄 [[2026-10-01]]', cursor: 18 },
    edit: { from: 5, to: 6, insert: '[[2026-10-01]]' },
  });
  assert.equal(how, 'noop');
  assert.equal(plain.textContent, '둘째 줄 @');
  console.log('cm6-insert: PASS plain contenteditable is never rewritten wholesale');
}

// destroy() detaches listeners and the late-attach observer state.
{
  const view = makeFakeView('@', 1);
  const { controller, editor, popup } = mountEditor(view);
  controller.destroy();
  await input(editor);
  assert.equal(popup.hidden, true);
  assert.equal(view.dispatches.length, 0);
  console.log('cm6-insert: PASS destroy detaches editor targets');
}

// Attaching an empty editor arms the starter banner (late attach included).
{
  const view = makeFakeView('', 0);
  const { controller } = mountEditor(view);
  assert.equal(controller.banner.hidden, false);
  assert.equal(controller.banner.children.filter((c) => c._tag === 'button').length, 3);
  console.log('cm6-insert: PASS empty editor attach shows the starter banner');
}

// Starter buttons re-read the document at click time: a draft that arrived
// after the banner opened is replaced, never merged.
{
  const view = makeFakeView('', 0);
  const { controller } = mountEditor(view);
  const buttons = controller.banner.children.filter((c) => c._tag === 'button');
  view._text = 'draft';
  view._head = 5;
  buttons[1].dispatchEvent(new Event('click'));
  assert.ok(view._text.startsWith('# 회의록\n\n## 안건'));
  assert.equal(view._text.includes('draft'), false);
  console.log('cm6-insert: PASS starter click replaces the current document');
}

// Manual Range fallback announces itself with a synthetic input so host
// models stay in sync — and still never rewrites textContent.
{
  const ranges = [];
  const fakeRange = {
    setStart() {}, setEnd() {}, deleteContents() {}, collapse() {}, insertNode() {},
  };
  const { FolioSuggestions, document: fakeDocument } = loadModule(null, {
    createRange: () => { ranges.push(1); return fakeRange; },
    createTextNode: (t) => ({ nodeType: 3, textContent: t }),
    getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
  });
  const plain = fakeDocument.createElement('div');
  plain.setAttribute('contenteditable', 'true');
  plain.textContent = '둘째 줄 @';
  let inputCount = 0;
  plain.addEventListener('input', () => { inputCount += 1; });
  const how = FolioSuggestions.defaultInsert({
    target: plain,
    result: { text: '둘째 줄 [[2026-10-01]]', cursor: 18 },
    edit: { from: 5, to: 6, insert: '[[2026-10-01]]' },
  });
  assert.equal(how, 'range');
  assert.equal(inputCount, 1);
  assert.equal(plain.textContent, '둘째 줄 @');
  console.log('cm6-insert: PASS range fallback announces input without wholesale rewrite');
}

// Mobile buttons target the focused field, falling back to the most
// recently attached one — never blindly the first input on the page.
{
  const view = makeFakeView('메모 ', 5);
  const loaded = loadModule(view);
  const container = loaded.document.createElement('div');
  loaded.document.body.appendChild(container);
  const search = loaded.document.createElement('input');
  search.setAttribute('type', 'text');
  container.appendChild(search);
  const editor = loaded.document.createElement('div');
  editor.setAttribute('contenteditable', 'true');
  container.appendChild(editor);
  // The fake view only owns the editor node, like a real CodeMirror
  // view.dom.contains check.
  view.dom.contains = (el) => el === editor;
  const controller = loaded.FolioSuggestions.createController({ root: container, providers });
  const atButton = controller.mobileBar.children.find((c) => c.textContent === '@ 날짜');
  assert.ok(atButton);
  // Focused editor wins over the earlier search box.
  loaded.document.activeElement = editor;
  atButton.dispatchEvent(new Event('click'));
  assert.equal(view.dispatches.length, 1);
  assert.equal(view._text, '메모 @');
  assert.equal(search.value, '');
  // Focused search box wins instead.
  loaded.document.activeElement = search;
  atButton.dispatchEvent(new Event('click'));
  assert.equal(search.value, '@');
  assert.equal(view.dispatches.length, 1);
  // No focus: the most recently attached target (the editor) wins.
  delete loaded.document.activeElement;
  view._head = view._text.length;
  atButton.dispatchEvent(new Event('click'));
  assert.equal(view.dispatches.length, 2);
  assert.equal(view._text, '메모 @ @');
  console.log('cm6-insert: PASS mobile buttons target the focused field');
}

console.log('cm6-insert: PASS');
