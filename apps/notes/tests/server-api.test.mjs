// Integration runner: point FOLIO_TEST_BASE_URL at a temporary SilverBullet
// server of the version pinned in install.sh, using /notes/editor/main/.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';

const base = process.env.FOLIO_TEST_BASE_URL;
if (!base) {
  console.log('server-api: SKIP (FOLIO_TEST_BASE_URL is not set)');
} else {
  const context = {window: {crypto: {randomUUID}}, document: {}, console, Date};
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
  const [first, second] = await Promise.all([
    capture({text: 'first captured note', destination: 'inbox'}),
    capture({text: 'second captured note', destination: 'inbox'}),
    fetchImpl(`${root}.fs/Inbox.md`, {method: 'PUT', body: '# Inbox\n- simultaneous editor autosave\n'}),
  ]);
  assert.notEqual(first.path, second.path);
  assert.ok((await (await fetchImpl(first.path)).text()).includes('first captured note'));
  assert.ok((await (await fetchImpl(second.path)).text()).includes('second captured note'));
  assert.equal(await (await fetchImpl(`${root}.fs/Inbox.md`)).text(), '# Inbox\n- simultaneous editor autosave\n');
  const listing = await (await fetchImpl(`${root}.fs`)).json();
  for (const saved of [first, second]) {
    const name = decodeURIComponent(saved.path.slice(`${root}.fs/`.length));
    assert.ok(listing.some(file => file.name === name), name);
  }
  console.log('server-api: PASS listing, Unicode creation, existing preservation, concurrent captures and editor autosave');
}
