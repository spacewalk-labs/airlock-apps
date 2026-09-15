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

  function defaultProviders() {
    return [
      { trigger: '@', items: [{ id: 'today', label: '오늘 날짜', keywords: ['date'], insert: '@today' }] },
      { trigger: '/', items: [{ id: 'todo', label: '할 일', keywords: ['task'], insert: '- [ ] ' }] },
      { trigger: '[[', items: [{ id: 'page', label: '문서 연결', keywords: ['page', 'link'], insert: '[[' }] },
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

  function createController({ root = document, providers = defaultProviders(), onInsert = defaultInsert, onAction = () => {} } = {}) {
    let active = null;
    let composing = false;

    const popup = document.createElement('div');
    popup.hidden = true;
    popup.className = 'folio-suggestion-menu';
    popup.setAttribute('role', 'listbox');
    popup.setAttribute('aria-label', '입력 후보');
    document.body.appendChild(popup);

    const close = () => {
      active = null;
      popup.hidden = true;
      popup.replaceChildren();
    };

    const render = (target, context) => {
      const items = filterSuggestions(providers, context.trigger, context.query);
      if (!items.length) return close();
      active = { target, context, items, index: 0 };
      popup.replaceChildren();
      items.forEach((item, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'folio-suggestion-item';
        button.setAttribute('role', 'option');
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

    const choose = (index) => {
      if (!active) return;
      const item = active.items[index];
      const selection = window.getSelection?.();
      const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
      const text = active.target.value ?? active.target.textContent ?? '';
      const result = applySuggestion(text, active.context, item);
      if (!result) return close();
      onInsert({ target: active.target, result, range });
      if (result.action) onAction(result.action, item);
      close();
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

  window.FolioSuggestions = { TRIGGERS, triggerAt, filterSuggestions, applySuggestion, defaultProviders, createController };

  const boot = () => {
    const targets = document.querySelectorAll?.('textarea, input[type="text"], [contenteditable="true"]') || [];
    if (targets.length) createController();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
