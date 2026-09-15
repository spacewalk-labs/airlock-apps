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
console.log('suggestion-foundation: PASS');
