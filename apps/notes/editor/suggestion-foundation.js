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

  function filterSuggestions(providers, trigger, query) {
    const needle = query.trim().toLocaleLowerCase();
    return providers
      .filter((provider) => provider.trigger === trigger)
      .flatMap((provider) => provider.items || [])
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

  function applySuggestion(text, context, item) {
    if (!context || !item) return null;
    const replacement = typeof item.insert === 'function' ? item.insert(context) : item.insert;
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
      { trigger: '/', items: [{ id: 'todo', label: '할 일', keywords: ['task'], insert: '- [ ] ' }] },
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

  function createController({ root = document, providers = defaultProviders(), onInsert = defaultInsert, onAction = createPageAction() } = {}) {
    let active = null;
    let composing = false;
    let requestId = 0;

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
      const immediate = filterSuggestions(matching, context.trigger, context.query);
      const pending = matching
        .filter((provider) => typeof provider.getItems === 'function')
        .map((provider) => Promise.resolve(provider.getItems(context.query, context)));
      if (!pending.length) return renderItems(target, context, immediate, renderRequestId);
      if (immediate.length) renderItems(target, context, immediate, renderRequestId);
      else {
        active = null;
        popup.hidden = true;
        popup.replaceChildren();
      }
      Promise.all(pending)
        .then((groups) => renderItems(target, context, [...immediate, ...groups.flat()].slice(0, 8), renderRequestId))
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
      // Close before inserting: onInsert dispatches a synthetic 'input' event
      // that re-enters onInput synchronously on this same target. If close()
      // ran after onInsert, it would wipe out any menu that reentrant call
      // just opened (e.g. an insert whose text recreates its own trigger),
      // and it would inspect a now-stale `active`.
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
      const context = triggerAt(text, cursor);
      if (context && TRIGGERS.includes(context.trigger)) render(target, context);
      else close();
    };

    const onKeydown = (event) => {
      if (event.isComposing || composing) return;
      if (event.key === 'Escape' && active) {
        event.preventDefault();
        close();
        return;
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
    return { close, destroy: () => { targets.forEach((target) => target.removeEventListener('input', onInput)); close(); popup.remove(); } };
  }

  window.FolioSuggestions = {
    TRIGGERS, triggerAt, filterSuggestions, applySuggestion, localDateValue, dateSuggestions,
    documentNames, documentSuggestions, validPageName, spaceRoot, pagePath, createDocumentProvider, createPageAction,
    defaultProviders, createController,
  };

  const boot = () => {
    const targets = document.querySelectorAll?.('textarea, input[type="text"], [contenteditable="true"]') || [];
    if (targets.length) createController();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
