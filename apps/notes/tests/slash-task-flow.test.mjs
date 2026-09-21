import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../editor/suggestion-foundation.js', import.meta.url), 'utf8');
const context = { window: {}, document: {}, console, Date };
vm.runInNewContext(source, context);
const {
  triggerAt,
  applySuggestion,
  inCodeBlock,
  lineContext,
  formatDueDateLabel,
  applyDueDate,
  toggleTaskItem,
  slashCommands,
  filterSlashCommands,
  createSlashProvider,
  defaultProviders,
} = context.window.FolioSuggestions;
const equalJson = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

const fixedDate = new Date(2026, 8, 22); // 2026-09-22

// 1. Slash commands provide intuitive Korean labels, descriptions and keywords
{
  const commands = slashCommands({ now: fixedDate });
  const ids = commands.map((c) => c.id);
  assert.ok(ids.includes('h1'));
  assert.ok(ids.includes('h2'));
  assert.ok(ids.includes('h3'));
  assert.ok(ids.includes('todo'));
  assert.ok(ids.includes('bullet'));
  assert.ok(ids.includes('quote'));
  assert.ok(ids.includes('code'));
  assert.ok(ids.includes('divider'));
  assert.ok(ids.includes('link'));
  assert.ok(ids.includes('toc'));
  assert.ok(ids.includes('template'));
  assert.ok(ids.includes('due'));
  assert.ok(ids.includes('due-tomorrow'));

  // Korean and English keyword search
  const todoMatches = filterSlashCommands(commands, '체크박스');
  assert.equal(todoMatches[0].id, 'todo');

  const headingMatches = filterSlashCommands(commands, 'h1');
  assert.equal(headingMatches[0].id, 'h1');
  assert.ok(headingMatches[0].label.includes('대제목'));

  const dueMatches = filterSlashCommands(commands, '마감');
  assert.ok(dueMatches.some((m) => m.id === 'due'));
}

// 2. Context-based command hiding: hide commands that do not fit context
{
  const commands = slashCommands({ now: fixedDate });

  // Inside code blocks: all slash commands are hidden
  const codeText = '```\nconsole.log("/test");\n```';
  const inCode = lineContext(codeText, 15);
  assert.equal(inCode.inCode, true);
  equalJson(filterSlashCommands(commands, '', inCode), []);

  // Inside a todo line: block headings (h1, h2, h3, quote, divider) are hidden,
  // while task-relevant commands (due, link, code) are available
  const todoLineText = '- [ ] 중요한 작업 /';
  const todoCtx = lineContext(todoLineText, todoLineText.length);
  assert.equal(todoCtx.isTodo, true);
  const todoAvailable = filterSlashCommands(commands, '', todoCtx).map((c) => c.id);
  assert.ok(!todoAvailable.includes('h1'));
  assert.ok(!todoAvailable.includes('h2'));
  assert.ok(!todoAvailable.includes('divider'));
  assert.ok(todoAvailable.includes('due'));
  assert.ok(todoAvailable.includes('due-tomorrow'));

  // On a heading line: heading/todo/divider/quote are hidden
  const headingLineText = '# 문서 제목 /';
  const headingCtx = lineContext(headingLineText, headingLineText.length);
  assert.equal(headingCtx.isHeading, true);
  const headingAvailable = filterSlashCommands(commands, '', headingCtx).map((c) => c.id);
  assert.ok(!headingAvailable.includes('h1'));
  assert.ok(!headingAvailable.includes('todo'));
  assert.ok(!headingAvailable.includes('divider'));
  assert.ok(headingAvailable.includes('link'));

  // Mid-line text: block-level commands are hidden
  const midLineText = '중간 텍스트 /';
  const midCtx = lineContext(midLineText, midLineText.length);
  assert.equal(midCtx.isEmpty, false);
  const midAvailable = filterSlashCommands(commands, '', midCtx).map((c) => c.id);
  assert.ok(!midAvailable.includes('h1'));
  assert.ok(!midAvailable.includes('divider'));
  assert.ok(midAvailable.includes('due'));
}

// 3. /due task date manipulation and replacement:
// Replacing an existing date rather than duplicating it
{
  const inputWithoutDate = '- [ ] 분기 기획서 작성 /due';
  const ctx1 = triggerAt(inputWithoutDate, inputWithoutDate.length);
  const res1 = applyDueDate(inputWithoutDate, ctx1, '2026-09-22');
  assert.equal(res1.text, '- [ ] 분기 기획서 작성 📅 2026-09-22');
  assert.equal(res1.action.replaced, false);

  // When /due is run on a task line that already has a due date, replace cleanly
  const inputWithOldDate = '- [ ] 분기 기획서 작성 📅 2026-09-15 /due';
  const ctx2 = triggerAt(inputWithOldDate, inputWithOldDate.length);
  const res2 = applyDueDate(inputWithOldDate, ctx2, '2026-09-22');
  assert.equal(res2.text, '- [ ] 분기 기획서 작성 📅 2026-09-22');
  assert.equal(res2.action.replaced, true);

  // Undo restores exact previous state
  assert.equal(res2.undo.text, inputWithOldDate);

  // On an ordinary line without todo syntax, converts to a todo with due date
  const inputPlain = '회의록 정리 /due';
  const ctx3 = triggerAt(inputPlain, inputPlain.length);
  const res3 = applyDueDate(inputPlain, ctx3, '2026-09-22');
  assert.equal(res3.text, '- [ ] 회의록 정리 📅 2026-09-22');
}

// 4. Human-readable relative date label formatting
{
  assert.equal(formatDueDateLabel('2026-09-22', fixedDate), '오늘');
  assert.equal(formatDueDateLabel('2026-09-23', fixedDate), '내일');
  assert.equal(formatDueDateLabel('2026-09-21', fixedDate), '어제');
  assert.equal(formatDueDateLabel('2026-09-19', fixedDate), '3일 지남');
  assert.equal(formatDueDateLabel('2026-09-27', fixedDate), '5일 후');
}

// 5. Task completion toggle and undo
{
  const unchecked = '- [ ] 배포 검증 완료하기 📅 2026-09-22';
  const toggled = toggleTaskItem(unchecked, 5);
  assert.equal(toggled.checked, true);
  assert.equal(toggled.text, '- [x] 배포 검증 완료하기 📅 2026-09-22');
  assert.equal(toggled.undo.text, unchecked);

  const untoggled = toggleTaskItem(toggled.text, 5);
  assert.equal(untoggled.checked, false);
  assert.equal(untoggled.text, unchecked);
}

// 6. Integration via applySuggestion with slash commands
{
  const commands = slashCommands({ now: fixedDate });
  const h1Item = commands.find((c) => c.id === 'h1');
  const h1Input = '/h1';
  const h1Ctx = triggerAt(h1Input, h1Input.length);
  const h1Res = applySuggestion(h1Input, h1Ctx, h1Item);
  assert.equal(h1Res.text, '# ');

  const dueItem = commands.find((c) => c.id === 'due');
  const dueInput = '- [ ] 제품 배포 /due';
  const dueCtx = triggerAt(dueInput, dueInput.length);
  const dueRes = applySuggestion(dueInput, dueCtx, dueItem);
  assert.equal(dueRes.text, '- [ ] 제품 배포 📅 2026-09-22');
  assert.ok(dueRes.undo);
}

console.log('slash-task-flow: PASS');
