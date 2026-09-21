import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
const context = { window: {}, document: {}, console, Date };
vm.runInNewContext(source, context);
const {
  triggerAt,
  applySuggestion,
  dateSuggestions,
  documentNames,
  documentSuggestions,
  validPageName,
  spaceRoot,
  pagePath,
  createDocumentProvider,
  createPageAction,
} = context.window.FolioSuggestions;
const equalJson = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

// Dates are calculated in the user's local calendar, including month/year boundaries,
// and inserted as ordinary wiki links so SilverBullet indexes their backlinks.
{
  const items = dateSuggestions(new Date(2026, 11, 31, 23, 59));
  equalJson(items.map(({ id, insert }) => ({ id, insert })), [
    { id: 'today', insert: '[[2026-12-31]]' },
    { id: 'tomorrow', insert: '[[2027-01-01]]' },
    { id: 'yesterday', insert: '[[2026-12-30]]' },
  ]);
  const input = '회의 @내';
  const result = applySuggestion(input, triggerAt(input, input.length), items[1]);
  equalJson(result, { text: '회의 [[2027-01-01]]', cursor: 17, action: null });
}

// Existing Markdown pages become wiki-link suggestions; non-page files and hidden
// files never leak into the picker. Prefix matches are ranked ahead of contains.
{
  const index = [
    { name: '회의/주간.md' },
    { name: '지난 회의.md' },
    { name: '회의록.md' },
    { name: 'image.png' },
    { name: '.settings.md' },
  ];
  equalJson(documentNames(index), ['회의/주간', '지난 회의', '회의록']);
  equalJson(documentSuggestions(index, '회의').map((item) => item.id), [
    'page:회의/주간', 'page:회의록', 'page:지난 회의', 'create:회의',
  ]);
  equalJson(documentSuggestions(index, '회의록').map((item) => item.id), ['page:회의록']);
  equalJson(documentSuggestions(index, '../private').map((item) => item.id), []);
}

// The provider uses SilverBullet's authenticated file-list endpoint and caches it
// while the user narrows a query.
{
  const calls = [];
  const provider = createDocumentProvider({
    root: '/notes/editor/main/',
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, json: async () => [{ name: '제품 계획.md' }, { name: '회고.md' }] };
    },
  });
  assert.equal((await provider.getItems('제품'))[0].insert, '[[제품 계획]]');
  await provider.getItems('회고');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/notes/editor/main/index.json');
  assert.equal(calls[0].options.headers['X-Sync-Mode'], 'true');
}

// A missing title is created without overwriting an existing document. The inserted
// [[wiki link]] is the backlink contract; SilverBullet indexes it bidirectionally.
{
  assert.equal(spaceRoot('/notes/editor/main/제품'), '/notes/editor/main/');
  assert.equal(pagePath('/notes/editor/main/', '회의/주간 계획'), '/notes/editor/main/%ED%9A%8C%EC%9D%98/%EC%A3%BC%EA%B0%84%20%EA%B3%84%ED%9A%8D.md');
  assert.equal(validPageName('../private'), false);
  assert.throws(() => pagePath('/', '../private'));

  const calls = [];
  const action = createPageAction({
    root: '/notes/editor/main/',
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return calls.length === 1 ? { ok: false, status: 404 } : { ok: true, status: 200 };
    },
  });
  await action({ type: 'create-page', name: '새 문서' });
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[1].options.method, 'PUT');
  assert.equal(calls[1].options.body, '# 새 문서\n');

  const existingCalls = [];
  const preserveExisting = createPageAction({
    fetchImpl: async (url, options) => { existingCalls.push({ url, options }); return { ok: true, status: 200 }; },
  });
  await preserveExisting({ type: 'create-page', name: '기존 문서' });
  assert.equal(existingCalls.length, 1);
}

console.log('mention-link-flow: PASS');
