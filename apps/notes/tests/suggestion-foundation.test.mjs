import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
const context = { window: {}, document: {}, console };
vm.runInNewContext(source, context);
const { triggerAt, filterSuggestions, applySuggestion, defaultProviders } = context.window.FolioSuggestions;
const equalJson = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

equalJson(triggerAt('오늘 @tod', 7), { trigger: '@', query: 'tod', start: 3, end: 7 });
equalJson(triggerAt('문서 /to', 7), { trigger: '/', query: 'to', start: 3, end: 7 });
equalJson(triggerAt('연결 [[회의', 7), { trigger: '[[', query: '회의', start: 3, end: 7 });
assert.equal(triggerAt('email@example.com', 17), null);
assert.equal(triggerAt('단어/명령', 5), null);

const providers = [
  { trigger: '/', items: [{ id: 'todo', label: '할 일', keywords: ['task'], insert: '- [ ] ' }, { id: 'quote', label: '인용', insert: '> ' }] },
  { trigger: '@', items: [{ id: 'today', label: '오늘 날짜', keywords: ['date'], insert: '@today' }] },
];
equalJson(filterSuggestions(providers, '/', 'task').map((item) => item.id), ['todo']);
equalJson(filterSuggestions(providers, '/', '').map((item) => item.id), ['todo', 'quote']);

const contextForTodo = triggerAt('메모 /to', 7);
equalJson(applySuggestion('메모 /to', contextForTodo, providers[0].items[0]), {
  text: '메모 - [ ] ', cursor: 9, action: null,
});
assert.equal(applySuggestion('메모 /to', contextForTodo, null), null);
equalJson(defaultProviders().map((provider) => provider.trigger), ['@', '/', '[[' ]);

// --- DOM behavior: keyboard nav, Escape, touch tap, Korean IME boundary ---
// No jsdom dependency is vendored for this app, so this builds the minimal
// fake DOM createController() actually touches (EventTarget-based elements,
// a fixed 3-selector querySelectorAll) on top of Node's real global
// Event/EventTarget, instead of asserting against internals.

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

function loadDomModule() {
  const body = new FakeElement('body');
  const fakeDocument = { body, createElement: (tag) => new FakeElement(tag), querySelectorAll: (sel) => matchAll(body, sel) };
  class InputEventLike extends Event {
    constructor(type, opts = {}) { super(type, opts); this.inputType = opts.inputType; }
  }
  const domCtx = { window: { getSelection: () => undefined }, document: fakeDocument, Event, InputEvent: InputEventLike, console };
  vm.runInNewContext(source, domCtx);
  return { FolioSuggestions: domCtx.window.FolioSuggestions, document: fakeDocument };
}

function mountController(providers, onInsert) {
  const { FolioSuggestions, document: fakeDocument } = loadDomModule();
  const container = fakeDocument.createElement('div');
  fakeDocument.body.appendChild(container);
  const textarea = fakeDocument.createElement('textarea');
  container.appendChild(textarea);
  const insertCalls = [];
  FolioSuggestions.createController({
    root: container,
    providers,
    onInsert: onInsert || ((payload) => insertCalls.push(payload)),
  });
  const popup = fakeDocument.body.children[fakeDocument.body.children.length - 1];
  return { textarea, popup, insertCalls };
}

const domProviders = [
  { trigger: '/', items: [
    { id: 'todo', label: '할 일', keywords: ['task'], insert: '- [ ] ' },
    { id: 'quote', label: '인용', insert: '> ' },
  ] },
  { trigger: '@', items: [{ id: 'today', label: '오늘 날짜', keywords: ['date'], insert: '@today' }] },
  { trigger: '[[', items: [{ id: 'page', label: '문서 연결', insert: '[[' }] },
];

const type = (target, value, cursor) => {
  target.value = value;
  target.selectionStart = cursor;
  target.dispatchEvent(new Event('input'));
};
const keydown = (target, key) => {
  const event = new Event('keydown', { cancelable: true });
  event.key = key;
  target.dispatchEvent(event);
  return event;
};

// Keyboard nav: ArrowDown wraps, and each nav call prevents the default scroll/caret move.
{
  const { textarea, popup } = mountController(domProviders);
  type(textarea, '/', 1);
  assert.equal(popup.hidden, false);
  assert.equal(popup.children.length, 2);
  let event = keydown(textarea, 'ArrowDown');
  assert.equal(event.defaultPrevented, true);
  equalJson(popup.children.map((c) => c.getAttribute('aria-selected')), ['false', 'true']);
  event = keydown(textarea, 'ArrowDown');
  equalJson(popup.children.map((c) => c.getAttribute('aria-selected')), ['true', 'false']);
  console.log('suggestion-foundation: PASS keyboard nav wraps and prevents default');
}

// Escape closes the menu (and prevents default), except while an IME composition is open.
{
  const { textarea, popup } = mountController(domProviders);
  type(textarea, '/', 1);
  let event = keydown(textarea, 'Escape');
  assert.equal(event.defaultPrevented, true);
  assert.equal(popup.hidden, true);

  type(textarea, '/', 1);
  textarea.dispatchEvent(new Event('compositionstart'));
  // Korean IME interim keystrokes fire 'input' while composing; they must
  // not be treated as query text until compositionend commits the syllable.
  type(textarea, '/할', 2);
  assert.equal(popup.children.length, 2, 'interim IME input must not re-filter the menu');
  event = keydown(textarea, 'Escape');
  assert.equal(event.defaultPrevented, false, 'Escape must be swallowed by the IME, not the menu, while composing');
  assert.equal(popup.hidden, false);
  textarea.dispatchEvent(new Event('compositionend'));
  assert.equal(popup.children.length, 1, 'compositionend must apply the committed 할 query');
  assert.equal(popup.children[0].dataset.id, 'todo');
  console.log('suggestion-foundation: PASS escape and Korean IME composition boundary');
}

// Touch/mouse selection: mousedown must not steal focus/selection (preventDefault),
// and the tap is completed on click.
{
  const { textarea, popup, insertCalls } = mountController(domProviders);
  type(textarea, '@', 1);
  const button = popup.children[0];
  const mousedown = new Event('mousedown', { cancelable: true });
  button.dispatchEvent(mousedown);
  assert.equal(mousedown.defaultPrevented, true);
  button.dispatchEvent(new Event('click'));
  assert.equal(insertCalls.length, 1);
  assert.equal(insertCalls[0].result.text, '@today');
  assert.equal(popup.hidden, true);
  console.log('suggestion-foundation: PASS touch/mouse tap selects and closes');
}

// Regression: choosing an item must not let a stale close() (queued behind the
// synthetic 'input' event onInsert dispatches) clobber a menu that reentrant
// input just reopened. '[[' -> 'page' re-inserts '[[' itself, so choosing it
// should hand control to the reopened link-query menu, not close it. This
// needs the real defaultInsert (not a capture stub) since the reentrancy
// comes from defaultInsert's own synthetic 'input' dispatch.
{
  const { FolioSuggestions, document: fakeDocument } = loadDomModule();
  const container = fakeDocument.createElement('div');
  fakeDocument.body.appendChild(container);
  const textarea = fakeDocument.createElement('textarea');
  container.appendChild(textarea);
  FolioSuggestions.createController({ root: container, providers: domProviders });
  const popup = fakeDocument.body.children[fakeDocument.body.children.length - 1];
  type(textarea, '[[', 2);
  assert.equal(popup.children.length, 1);
  const event = keydown(textarea, 'Enter');
  assert.equal(event.defaultPrevented, true);
  assert.equal(textarea.value, '[[', 'insert must not duplicate the trigger text');
  assert.equal(popup.hidden, false, 'reentrant reopen must survive choose()');
  assert.equal(popup.children.length, 1);
  console.log('suggestion-foundation: PASS choose() does not clobber a reentrant reopen');
}

console.log('suggestion-foundation: PASS');
