// Integration runner: point FOLIO_TEST_BASE_URL at a temporary SilverBullet
// server of the version pinned in install.sh, using /notes/editor/main/.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const base = process.env.FOLIO_TEST_BASE_URL;
if (!base) {
  console.log('server-api: SKIP (FOLIO_TEST_BASE_URL is not set)');
} else {
  const context = {window: {}, document: {}, console, Date};
  vm.runInNewContext(fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8'), context);
  const {createDocumentProvider, createPageAction, createQuickCaptureAction} = context.window.FolioSuggestions;
  const root = '/notes/editor/main/';
  const fetchImpl = (path, options) => fetch(new URL(path, base), options);
  const provider = createDocumentProvider({root, fetchImpl});
  assert.ok((await provider.getItems('Meeting')).some(item => item.id === 'page:Meeting'));
  const create = createPageAction({root, fetchImpl});
  await create({type: 'create-page', name: '회의/새 문서'});
  const created = await fetchImpl(`${root}.fs/${encodeURIComponent('회의')}/${encodeURIComponent('새 문서')}.md`);
  assert.equal(await created.text(), '# 회의/새 문서\n');
  await create({type: 'create-page', name: 'Meeting'});
  assert.equal(await (await fetchImpl(`${root}.fs/Meeting.md`)).text(), '# Existing meeting\n');
  const capture = createQuickCaptureAction({root, fetchImpl});
  await capture({text: 'new note', destination: 'inbox'});
  assert.equal(await (await fetchImpl(`${root}.fs/Inbox.md`)).text(), '# Inbox\n- existing note\n- new note\n');
  console.log('server-api: PASS listing, Unicode page creation, existing page preservation and append');
}
