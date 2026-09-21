(() => {
  'use strict';

  const TRIGGERS = ['@', '/', '[[' ];

  function triggerAt(text, cursor) {
    const before = text.slice(0, cursor);
    const match = before.match(/(?:^|\s)(@|\/|\[\[)([^\s\]]*)$/u);
    if (!match) return null;
    return {
      trigger: match[1],
      query: match[2],
      start: match.index + match[0].length - match[2].length - match[1].length,
      end: cursor,
    };
  }

  function inCodeBlock(text, cursor = 0) {
    const before = text.slice(0, cursor);
    const fences = before.match(/(?:^|\n)```/g);
    return Boolean(fences && fences.length % 2 === 1);
  }

  function lineContext(text, cursor = 0) {
    const safeCursor = Math.max(0, Math.min(text.length, cursor));
    const lineStart = text.lastIndexOf('\n', safeCursor - 1) + 1;
    let lineEnd = text.indexOf('\n', safeCursor);
    if (lineEnd === -1) lineEnd = text.length;
    const line = text.slice(lineStart, lineEnd);
    const beforeCursor = text.slice(lineStart, safeCursor);
    const isTodo = /^\s*-\s*\[[ xX]\]/u.test(line);
    const isHeading = /^\s*#{1,6}\s/u.test(line);
    const isBullet = /^\s*-\s+/u.test(line) && !isTodo;
    const isQuote = /^\s*>\s+/u.test(line);
    const isEmpty = /^\s*$/u.test(beforeCursor.replace(/\/[^\s]*$/u, ''));
    const hasDueDate = /📅\s*\d{4}-\d{2}-\d{2}/u.test(line);
    return {
      lineStart,
      lineEnd,
      line,
      beforeCursor,
      isTodo,
      isHeading,
      isBullet,
      isQuote,
      isEmpty,
      hasDueDate,
      inCode: inCodeBlock(text, safeCursor),
    };
  }

  function formatDueDateLabel(dueDateStr, now = new Date()) {
    if (typeof dueDateStr !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(dueDateStr)) return '';
    const [y, m, d] = dueDateStr.split('-').map(Number);
    const target = new Date(y, m - 1, d);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diffMs = target.getTime() - today.getTime();
    const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return '오늘';
    if (diffDays === 1) return '내일';
    if (diffDays === -1) return '어제';
    if (diffDays < -1) return `${Math.abs(diffDays)}일 지남`;
    return `${diffDays}일 후`;
  }

  function applyDueDate(text, context, dueDateStr) {
    const lineStart = text.lastIndexOf('\n', context.start - 1) + 1;
    let lineEnd = text.indexOf('\n', context.end);
    if (lineEnd === -1) lineEnd = text.length;
    const line = text.slice(lineStart, lineEnd);

    const relStart = context.start - lineStart;
    const relEnd = context.end - lineStart;
    const withoutTrigger = line.slice(0, relStart) + line.slice(relEnd);

    const dueDateRegex = /\s*📅\s*\d{4}-\d{2}-\d{2}/u;
    const hasExisting = dueDateRegex.test(withoutTrigger);
    const cleaned = withoutTrigger.replace(dueDateRegex, '').trimEnd();

    let newLine;
    if (/^\s*-\s*\[[ xX]\]/u.test(cleaned)) {
      newLine = `${cleaned} 📅 ${dueDateStr}`;
    } else if (/^\s*-\s+/u.test(cleaned)) {
      newLine = cleaned.replace(/^\s*-\s+/u, '- [ ] ') + ` 📅 ${dueDateStr}`;
    } else if (cleaned.trim().length === 0) {
      newLine = `- [ ] 📅 ${dueDateStr}`;
    } else {
      newLine = `- [ ] ${cleaned.trim()} 📅 ${dueDateStr}`;
    }

    const newText = text.slice(0, lineStart) + newLine + text.slice(lineEnd);
    const newCursor = lineStart + newLine.length;
    return {
      text: newText,
      cursor: newCursor,
      undo: { text, cursor: context.start },
      action: { type: 'set-due-date', date: dueDateStr, replaced: hasExisting },
    };
  }

  function toggleTaskItem(text, cursorOrOffset = 0) {
    const offset = typeof cursorOrOffset === 'number' ? cursorOrOffset : 0;
    const lineStart = text.lastIndexOf('\n', offset - 1) + 1;
    let lineEnd = text.indexOf('\n', offset);
    if (lineEnd === -1) lineEnd = text.length;
    const line = text.slice(lineStart, lineEnd);

    let toggledLine = null;
    let nextChecked = null;
    if (/^\s*-\s*\[ \]/u.test(line)) {
      toggledLine = line.replace(/^(\s*-\s*\[) (\])/u, '$1x$2');
      nextChecked = true;
    } else if (/^\s*-\s*\[[xX]\]/u.test(line)) {
      toggledLine = line.replace(/^(\s*-\s*\[)[xX](\])/u, '$1 $2');
      nextChecked = false;
    }

    if (!toggledLine) return null;

    const newText = text.slice(0, lineStart) + toggledLine + text.slice(lineEnd);
    return {
      text: newText,
      checked: nextChecked,
      undo: { text, cursor: offset },
      action: { type: 'toggle-task', checked: nextChecked },
    };
  }

  function slashCommands({ now = new Date() } = {}) {
    const today = localDateValue(now);
    const tomorrowDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    const tomorrow = localDateValue(tomorrowDate);

    return [
      { id: 'todo', label: '할 일 · 체크박스', description: '체크박스가 있는 할 일을 만듭니다', keywords: ['task', 'todo', '체크박스', '할일'], insert: '- [ ] ', group: 'task' },
      { id: 'h1', label: '제목 1 · 대제목', description: '가장 큰 제목을 삽입합니다', keywords: ['h1', '대제목', '헤딩1'], insert: '# ', group: 'write' },
      { id: 'h2', label: '제목 2 · 중제목', description: '중간 크기 제목을 삽입합니다', keywords: ['h2', '중제목', '헤딩2'], insert: '## ', group: 'write' },
      { id: 'h3', label: '제목 3 · 소제목', description: '작은 크기 제목을 삽입합니다', keywords: ['h3', '소제목', '헤딩3'], insert: '### ', group: 'write' },
      { id: 'bullet', label: '글머리 기호 목록', description: '단순 글머리 기호 목록을 만듭니다', keywords: ['bullet', '목록', '리스트'], insert: '- ', group: 'write' },
      { id: 'quote', label: '인용구', description: '인용 블록을 작성합니다', keywords: ['quote', '인용', '인용문'], insert: '> ', group: 'write' },
      { id: 'code', label: '코드 블록', description: '코드 블록을 삽입합니다', keywords: ['code', '코드', '스크립트'], insert: '```\n\n```', group: 'write' },
      { id: 'divider', label: '구분선', description: '가로 구분선을 삽입합니다', keywords: ['divider', 'hr', '구분선'], insert: '---\n', group: 'write' },
      { id: 'link', label: '링크', description: '외부 링크를 삽입합니다', keywords: ['link', '링크', 'url'], insert: '[](url)', group: 'organize' },
      { id: 'toc', label: '목차', description: '문서 목차를 생성합니다', keywords: ['toc', '목차', '차례'], insert: '```toc\n```\n', group: 'organize' },
      { id: 'template', label: '템플릿', description: '서식 템플릿을 불러옵니다', keywords: ['template', '템플릿', '서식'], insert: '{{template}}', group: 'organize' },
      {
        id: 'due',
        label: `마감일 설정 · 오늘 (${today})`,
        description: '할 일 마감일을 오늘로 설정하거나 교체합니다',
        keywords: ['due', '마감', '오늘', '날짜'],
        apply: (text, context) => applyDueDate(text, context, today),
        group: 'task',
      },
      {
        id: 'due-tomorrow',
        label: `마감일 설정 · 내일 (${tomorrow})`,
        description: '할 일 마감일을 내일로 설정하거나 교체합니다',
        keywords: ['due', '내일', 'tomorrow', '마감'],
        apply: (text, context) => applyDueDate(text, context, tomorrow),
        group: 'task',
      },
    ];
  }

  function filterSlashCommands(items, query, contextInfo) {
    if (contextInfo?.inCode) return [];

    const needle = (query || '').trim().toLocaleLowerCase();

    return items
      .filter((item) => {
        if (contextInfo?.isTodo) {
          if (['h1', 'h2', 'h3', 'quote', 'divider', 'todo'].includes(item.id)) return false;
        } else if (contextInfo?.isHeading) {
          if (['todo', 'bullet', 'divider', 'quote', 'h1', 'h2', 'h3'].includes(item.id)) return false;
        } else if (contextInfo && contextInfo.isEmpty === false) {
          if (['divider', 'h1', 'h2', 'h3', 'quote', 'bullet'].includes(item.id)) return false;
        }

        if (!needle) return true;
        const haystack = [item.label, item.id, ...(item.keywords || []), item.description || '']
          .join(' ')
          .toLocaleLowerCase();
        return haystack.includes(needle);
      })
      .slice(0, 8);
  }

  function createSlashProvider(options = {}) {
    const commands = slashCommands(options);
    return {
      trigger: '/',
      getItems(query, context, lineCtx) {
        return filterSlashCommands(commands, query, lineCtx);
      },
      items: commands,
    };
  }

  function filterSuggestions(providers, trigger, query, lineCtx) {
    const needle = query.trim().toLocaleLowerCase();
    return providers
      .filter((provider) => provider.trigger === trigger)
      .flatMap((provider) => {
        if (typeof provider.getItems === 'function' && lineCtx) {
          const res = provider.getItems(query, null, lineCtx);
          if (Array.isArray(res)) return res;
        }
        return provider.items || [];
      })
      .filter((item) => {
        const haystack = [item.label, item.id, ...(item.keywords || [])]
          .join(' ')
          .toLocaleLowerCase();
        return !needle || haystack.includes(needle);
      })
      .slice(0, 8);
  }

  function localDateValue(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function dateSuggestions(now = new Date()) {
    return [
      { id: 'today', label: '오늘', offset: 0, keywords: ['today', '금일'] },
      { id: 'tomorrow', label: '내일', offset: 1, keywords: ['tomorrow', '익일'] },
      { id: 'yesterday', label: '어제', offset: -1, keywords: ['yesterday'] },
    ].map(({ offset, ...item }) => {
      const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
      const value = localDateValue(date);
      return { ...item, label: `${item.label} · ${value}`, insert: `[[${value}]]`, kind: 'date' };
    });
  }

  function documentNames(index) {
    const entries = Array.isArray(index) ? index : (index?.files || []);
    return entries
      .map((entry) => typeof entry === 'string' ? entry : entry?.name)
      .filter((name) => typeof name === 'string' && name.endsWith('.md') && !name.startsWith('.'))
      .map((name) => name.slice(0, -3));
  }

  function documentSuggestions(index, query) {
    const cleanQuery = query.trim().replace(/^\[\[/u, '').replace(/\]\]$/u, '');
    const needle = cleanQuery.toLocaleLowerCase();
    const names = documentNames(index);
    const matches = names
      .filter((name) => !needle || name.toLocaleLowerCase().includes(needle))
      .sort((a, b) => {
        const aLower = a.toLocaleLowerCase();
        const bLower = b.toLocaleLowerCase();
        return Number(bLower.startsWith(needle)) - Number(aLower.startsWith(needle)) || a.localeCompare(b, 'ko');
      })
      .slice(0, 7)
      .map((name) => ({ id: `page:${name}`, label: name, insert: `[[${name}]]`, kind: 'page' }));
    const exact = names.some((name) => name.toLocaleLowerCase() === needle);
    if (cleanQuery && !exact && validPageName(cleanQuery)) {
      matches.push({
        id: `create:${cleanQuery}`,
        label: `새 문서 만들기 · ${cleanQuery}`,
        insert: `[[${cleanQuery}]]`,
        kind: 'create-page',
        action: { type: 'create-page', name: cleanQuery },
      });
    }
    return matches.slice(0, 8);
  }

  function validPageName(name) {
    return typeof name === 'string'
      && name.trim() === name
      && name.length > 0
      && !name.split('/').some((part) => !part || part === '.' || part === '..')
      && !/[\\\u0000-\u001f]/u.test(name);
  }

  function spaceRoot(pathname = window.location?.pathname || '/') {
    const marker = '/editor/';
    const markerAt = pathname.indexOf(marker);
    return markerAt < 0 ? '/' : `${pathname.slice(0, markerAt + marker.length)}${pathname.slice(markerAt + marker.length).split('/')[0]}/`;
  }

  function pagePath(root, name) {
    if (!validPageName(name)) throw new Error('올바른 문서 제목이 아닙니다');
    return `${root}${name.split('/').map(encodeURIComponent).join('/')}.md`;
  }

  function createDocumentProvider({ fetchImpl = window.fetch?.bind(window), root = spaceRoot() } = {}) {
    let cachedIndex = null;
    return {
      trigger: '[[',
      async getItems(query) {
        if (!fetchImpl) return [];
        if (!cachedIndex) {
          const response = await fetchImpl(`${root}index.json`, { headers: { 'X-Sync-Mode': 'true' } });
          if (!response.ok) throw new Error(`문서 목록을 불러오지 못했습니다 (${response.status})`);
          cachedIndex = await response.json();
        }
        return documentSuggestions(cachedIndex, query);
      },
    };
  }

  function createPageAction({ fetchImpl = window.fetch?.bind(window), root = spaceRoot() } = {}) {
    return async (action) => {
      if (action?.type !== 'create-page' || !fetchImpl) return;
      const path = pagePath(root, action.name);
      const existing = await fetchImpl(path, { method: 'GET', headers: { 'X-Get-Meta': 'true', 'X-Sync-Mode': 'true' } });
      if (existing.ok) return;
      if (existing.status !== 404) throw new Error(`문서를 확인하지 못했습니다 (${existing.status})`);
      const created = await fetchImpl(path, {
        method: 'PUT',
        headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
        body: `# ${action.name}\n`,
      });
      if (!created.ok) throw new Error(`문서를 만들지 못했습니다 (${created.status})`);
    };
  }

  function starterTemplates(now = new Date()) {
    const today = localDateValue(now);
    return {
      blank: {
        id: 'blank',
        label: '빈 문서',
        description: '깨끗한 빈 페이지에서 바로 입력을 시작합니다',
        content: '',
      },
      template: {
        id: 'template',
        label: '템플릿',
        description: '기본 회의록 및 프로젝트 양식으로 시작합니다',
        content: '# 회의록\n\n## 안건\n- \n\n## 결정 사항\n- \n\n## 다음 할 일\n- [ ] \n',
      },
      journal: {
        id: 'journal',
        label: '오늘 일지',
        description: `오늘 날짜(${today})의 일일 업무 일지를 시작합니다`,
        content: `# 일지 · ${today}\n\n## 오늘 할 일\n- [ ] \n\n## 기록 및 메모\n- \n`,
      },
    };
  }

  function isDocumentEmpty(text) {
    if (typeof text !== 'string') return true;
    const trimmed = text.trim();
    return trimmed.length === 0 || /^#\s+[^\n]*\s*$/u.test(trimmed);
  }

  function applyStarter(text, starterId, options = {}) {
    const templates = starterTemplates(options.now || new Date());
    const choice = templates[starterId];
    if (!choice) return null;
    return {
      text: choice.content,
      cursor: choice.content.length,
      starter: choice.id,
    };
  }

  const QUICK_CAPTURE_DESTINATIONS = [
    { id: 'inbox', label: '받은 메모', name: 'Inbox' },
    { id: 'tasks', label: '할 일', name: '할 일' },
    { id: 'journal', label: '오늘 일지', name: (now) => `일지/${localDateValue(now)}` },
  ];

  function formatQuickCaptureEntry(text, destination = 'inbox', now = new Date()) {
    const trimmed = (text || '').trim();
    if (!trimmed) return null;
    const today = localDateValue(now);
    switch (destination) {
      case 'tasks':
        return /^\s*-\s*\[[ xX]\]/u.test(trimmed)
          ? `${trimmed}\n`
          : `- [ ] ${trimmed} 📅 ${today}\n`;
      case 'journal':
      case 'inbox':
      default:
        return `- ${trimmed}\n`;
    }
  }

  function quickCapturePath(destination = 'inbox', now = new Date(), root = spaceRoot()) {
    const today = localDateValue(now);
    let name = 'Inbox';
    if (destination === 'tasks') name = '할 일';
    else if (destination === 'journal') name = `일지/${today}`;
    return pagePath(root, name);
  }

  function createQuickCaptureAction({ fetchImpl = window.fetch?.bind(window), root = spaceRoot() } = {}) {
    return async ({ text, destination = 'inbox', now = new Date() }) => {
      if (!fetchImpl) throw new Error('fetch가 지원되지 않는 환경입니다');
      const entry = formatQuickCaptureEntry(text, destination, now);
      if (!entry) throw new Error('메모 내용이 비어 있습니다');
      const path = quickCapturePath(destination, now, root);

      let existingContent = '';
      const check = await fetchImpl(path, { method: 'GET', headers: { 'X-Sync-Mode': 'true' } });
      if (check.ok) {
        existingContent = await check.text();
      } else if (check.status !== 404) {
        throw new Error(`메모 문서를 불러오지 못했습니다 (${check.status})`);
      }

      let newContent;
      if (!existingContent) {
        const title = destination === 'tasks' ? '할 일' : (destination === 'journal' ? `일지 · ${localDateValue(now)}` : '받은 메모');
        newContent = `# ${title}\n\n${entry}`;
      } else {
        newContent = existingContent.endsWith('\n') ? `${existingContent}${entry}` : `${existingContent}\n${entry}`;
      }

      const saved = await fetchImpl(path, {
        method: 'PUT',
        headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
        body: newContent,
      });
      if (!saved.ok) throw new Error(`메모를 저장하지 못했습니다 (${saved.status})`);
      return { ok: true, path, entry, destination };
    };
  }

  function applySuggestion(text, context, item) {
    if (!context || !item) return null;
    if (typeof item.apply === 'function') {
      return item.apply(text, context);
    }
    const replacement = typeof item.insert === 'function' ? item.insert(context, text) : item.insert;
    if (typeof replacement === 'object' && replacement !== null) {
      return replacement;
    }
    if (typeof replacement !== 'string') return null;
    return {
      text: text.slice(0, context.start) + replacement + text.slice(context.end),
      cursor: context.start + replacement.length,
      action: item.action || null,
    };
  }

  function defaultProviders(options = {}) {
    return [
      { trigger: '@', items: dateSuggestions(options.now || new Date()) },
      createSlashProvider(options),
      createDocumentProvider(options),
    ];
  }

  function defaultInsert({ target, result }) {
    if ('value' in target) {
      target.value = result.text;
      target.setSelectionRange?.(result.cursor, result.cursor);
      target.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    target.textContent = result.text;
    target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText' }));
  }

  function createController({
    root = document,
    providers = defaultProviders(),
    onInsert = defaultInsert,
    onAction = createPageAction(),
    onQuickCapture = createQuickCaptureAction(),
    now = new Date(),
  } = {}) {
    let active = null;
    let composing = false;
    let requestId = 0;

    const banner = document.createElement('div');
    banner.hidden = true;
    banner.className = 'folio-activation-banner';
    document.body.appendChild(banner);

    const mobileBar = document.createElement('div');
    mobileBar.className = 'folio-mobile-bar';
    document.body.appendChild(mobileBar);

    const qcModal = document.createElement('div');
    qcModal.hidden = true;
    qcModal.className = 'folio-quick-capture-modal';
    document.body.appendChild(qcModal);

    const popup = document.createElement('div');
    popup.hidden = true;
    popup.className = 'folio-suggestion-menu';
    popup.setAttribute('role', 'listbox');
    popup.setAttribute('aria-label', '입력 후보');
    document.body.appendChild(popup);

    const close = () => {
      requestId += 1;
      active = null;
      popup.hidden = true;
      popup.replaceChildren();
    };

    const checkActivation = (target) => {
      if (!target) return;
      const text = target.value ?? target.textContent ?? '';
      if (isDocumentEmpty(text)) {
        banner.replaceChildren();
        const title = document.createElement('span');
        title.className = 'folio-activation-title';
        title.textContent = '문서 시작하기: ';
        banner.appendChild(title);

        ['blank', 'template', 'journal'].forEach((type) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'folio-activation-btn';
          btn.dataset.starter = type;
          const t = starterTemplates(now)[type];
          btn.textContent = t.label;
          btn.title = t.description;
          btn.addEventListener('click', () => {
            const started = applyStarter(text, type, { now });
            if (started) {
              onInsert({ target, result: started });
              banner.hidden = true;
              target.focus?.();
            }
          });
          banner.appendChild(btn);
        });
        banner.hidden = false;
      } else {
        banner.hidden = true;
      }
    };

    const openQuickCapture = (initialDest = 'inbox') => {
      qcModal.hidden = false;
      qcModal.replaceChildren();

      const dialog = document.createElement('div');
      dialog.className = 'folio-quick-capture-dialog';

      const header = document.createElement('div');
      header.className = 'folio-qc-header';
      header.textContent = '빠른 메모 (기본: 받은 메모)';
      dialog.appendChild(header);

      let currentDest = initialDest;
      const destGroup = document.createElement('div');
      destGroup.className = 'folio-qc-dest-group';
      const destButtons = [];

      QUICK_CAPTURE_DESTINATIONS.forEach((d) => {
        const destBtn = document.createElement('button');
        destBtn.type = 'button';
        destBtn.className = d.id === currentDest ? 'folio-qc-dest-btn active' : 'folio-qc-dest-btn';
        destBtn.dataset.destination = d.id;
        destBtn.textContent = d.label;
        destBtn.addEventListener('click', () => {
          currentDest = d.id;
          destButtons.forEach((b) => {
            b.className = b.dataset.destination === currentDest ? 'folio-qc-dest-btn active' : 'folio-qc-dest-btn';
          });
        });
        destButtons.push(destBtn);
        destGroup.appendChild(destBtn);
      });
      dialog.appendChild(destGroup);

      const input = document.createElement('textarea');
      input.className = 'folio-qc-input';
      dialog.appendChild(input);

      const footer = document.createElement('div');
      footer.className = 'folio-qc-footer';

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'folio-qc-cancel-btn';
      cancelBtn.textContent = '취소';
      cancelBtn.addEventListener('click', () => { qcModal.hidden = true; });

      const saveBtn = document.createElement('button');
      saveBtn.type = 'button';
      saveBtn.className = 'folio-qc-save-btn';
      saveBtn.textContent = '저장';
      saveBtn.addEventListener('click', async () => {
        const text = input.value?.trim() || '';
        if (!text) return;
        try {
          await onQuickCapture({ text, destination: currentDest, now });
          qcModal.hidden = true;
        } catch (err) {
          console.error('Quick capture failed:', err);
        }
      });

      footer.appendChild(cancelBtn);
      footer.appendChild(saveBtn);
      dialog.appendChild(footer);
      qcModal.appendChild(dialog);
      input.focus?.();
    };

    const renderItems = (target, context, items, renderRequestId) => {
      if (renderRequestId !== requestId) return;
      if (!items.length) return close();
      active = { target, context, items, index: 0 };
      popup.replaceChildren();
      items.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'folio-suggestion-item';
        button.setAttribute('role', 'option');
        button.setAttribute('aria-selected', String(index === 0));
        button.textContent = item.label;
        button.dataset.id = item.id;
        button.addEventListener('mousedown', (event) => event.preventDefault());
        button.addEventListener('click', () => choose(index));
        popup.appendChild(button);
      });
      popup.hidden = false;
      popup.style.left = `${Math.max(8, target.getBoundingClientRect().left)}px`;
      popup.style.top = `${target.getBoundingClientRect().bottom + 6}px`;
    };

    const render = (target, context) => {
      const renderRequestId = ++requestId;
      const matching = providers.filter((provider) => provider.trigger === context.trigger);
      const text = 'value' in target ? target.value : (target.textContent || '');
      const ctxInfo = lineContext(text, context.start);
      const syncProviders = matching.filter((p) => typeof p.getItems !== 'function');
      const asyncProviders = matching.filter((p) => typeof p.getItems === 'function');
      const immediate = filterSuggestions(syncProviders, context.trigger, context.query, ctxInfo);
      if (!asyncProviders.length) return renderItems(target, context, immediate, renderRequestId);
      if (immediate.length) renderItems(target, context, immediate, renderRequestId);
      else {
        active = null;
        popup.hidden = true;
        popup.replaceChildren();
      }
      const pending = asyncProviders.map((p) => Promise.resolve(p.getItems(context.query, context, ctxInfo, text)));
      Promise.all(pending)
        .then((groups) => {
          const combined = [...immediate, ...groups.flat()];
          const seen = new Set();
          const unique = combined.filter((item) => {
            if (!item || seen.has(item.id)) return false;
            seen.add(item.id);
            return true;
          });
          renderItems(target, context, unique.slice(0, 8), renderRequestId);
        })
        .catch(() => { if (renderRequestId === requestId) close(); });
    };

    const choose = (index) => {
      if (!active) return;
      const item = active.items[index];
      const selection = window.getSelection?.();
      const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
      const target = active.target;
      const text = target.value ?? target.textContent ?? '';
      const result = applySuggestion(text, active.context, item);
      close();
      if (!result) return;
      onInsert({ target, result, range });
      if (result.action) Promise.resolve(onAction(result.action, item)).catch((error) => console.error('folio suggestion action:', error));
    };

    const onInput = (event) => {
      if (composing) return;
      const target = event.currentTarget;
      const text = target.value ?? target.textContent ?? '';
      const cursor = target.selectionStart ?? text.length;
      checkActivation(target);
      const context = triggerAt(text, cursor);
      if (context && TRIGGERS.includes(context.trigger)) render(target, context);
      else close();
    };

    const onKeydown = (event) => {
      if (event.isComposing || composing) return;
      if ((event.altKey && (event.key === 'n' || event.key === 'N')) ||
          (event.ctrlKey && event.shiftKey && (event.key === 'c' || event.key === 'C'))) {
        event.preventDefault();
        openQuickCapture();
        return;
      }
      if (event.key === 'Escape') {
        if (!qcModal.hidden) {
          event.preventDefault();
          qcModal.hidden = true;
          return;
        }
        if (active) {
          event.preventDefault();
          close();
          return;
        }
      }
      if (!active) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        active.index = (active.index + (event.key === 'ArrowDown' ? 1 : -1) + active.items.length) % active.items.length;
        [...popup.children].forEach((child, index) => child.setAttribute('aria-selected', String(index === active.index)));
      } else if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        choose(active.index);
      }
    };

    const onCompositionStart = () => { composing = true; };
    const onCompositionEnd = (event) => { composing = false; onInput(event); };
    const targets = root.querySelectorAll?.('textarea, input[type="text"], [contenteditable="true"]') || [];
    targets.forEach((target) => {
      target.addEventListener('input', onInput);
      target.addEventListener('keydown', onKeydown);
      target.addEventListener('compositionstart', onCompositionStart);
      target.addEventListener('compositionend', onCompositionEnd);
    });

    // Mobile trigger buttons
    const triggerButtons = [
      { label: '@ 날짜', trigger: '@' },
      { label: '/ 기능', trigger: '/' },
      { label: '[[ 연결', trigger: '[[' },
    ];
    triggerButtons.forEach(({ label, trigger }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'folio-mobile-btn';
      btn.textContent = label;
      btn.addEventListener('click', () => {
        const activeTarget = targets[0];
        if (!activeTarget) return;
        const val = activeTarget.value ?? activeTarget.textContent ?? '';
        const cursor = activeTarget.selectionStart ?? val.length;
        const before = val.slice(0, cursor);
        const needSpace = before.length > 0 && !/\s$/u.test(before);
        const insertStr = (needSpace ? ' ' : '') + trigger;
        const newText = val.slice(0, cursor) + insertStr + val.slice(cursor);
        const newPos = cursor + insertStr.length;
        if ('value' in activeTarget) {
          activeTarget.value = newText;
          activeTarget.setSelectionRange?.(newPos, newPos);
          activeTarget.dispatchEvent(new Event('input', { bubbles: true }));
        }
        activeTarget.focus?.();
      });
      mobileBar.appendChild(btn);
    });

    const qcMobileBtn = document.createElement('button');
    qcMobileBtn.type = 'button';
    qcMobileBtn.className = 'folio-mobile-btn folio-mobile-qc-btn';
    qcMobileBtn.textContent = '+ 빠른 메모';
    qcMobileBtn.addEventListener('click', () => openQuickCapture());
    mobileBar.appendChild(qcMobileBtn);

    if (targets.length) checkActivation(targets[0]);

    return {
      close,
      openQuickCapture,
      checkActivation,
      banner,
      mobileBar,
      qcModal,
      destroy: () => {
        targets.forEach((target) => {
          target.removeEventListener('input', onInput);
          target.removeEventListener('keydown', onKeydown);
          target.removeEventListener('compositionstart', onCompositionStart);
          target.removeEventListener('compositionend', onCompositionEnd);
        });
        close();
        popup.remove?.();
        banner.remove?.();
        mobileBar.remove?.();
        qcModal.remove?.();
      },
    };
  }

  window.FolioSuggestions = {
    TRIGGERS, triggerAt, filterSuggestions, applySuggestion, localDateValue, dateSuggestions,
    documentNames, documentSuggestions, validPageName, spaceRoot, pagePath, createDocumentProvider, createPageAction,
    inCodeBlock, lineContext, formatDueDateLabel, applyDueDate, toggleTaskItem, slashCommands, filterSlashCommands, createSlashProvider,
    starterTemplates, isDocumentEmpty, applyStarter, QUICK_CAPTURE_DESTINATIONS, formatQuickCaptureEntry, quickCapturePath, createQuickCaptureAction,
    defaultProviders, createController,
  };

  const boot = () => {
    const targets = document.querySelectorAll?.('textarea, input[type="text"], [contenteditable="true"]') || [];
    if (targets.length) createController();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
