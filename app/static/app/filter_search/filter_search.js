import { FilterQuery } from './filter_query.js';
import { FilterRowMatcher } from './filter_row_matcher.js';
import { FilterSuggestions } from './filter_suggestions.js';

// One filter search box (partials/filter_search.html): filters the
// `data-filter-row` elements in its `data-filter-scope` as the query
// changes, suggests fields and values under the box (arrow keys, Enter or
// Tab, Escape, or the mouse), and keeps its menu buttons ticked to match
// the query, which they edit too.
//
// The scope can ask for a refresh when a row's values change
// (`filter-search:refresh`), and any `[data-filter-toggle][data-filter-value]`
// in it ticks that value (a label chip in a row, say). After each pass it
// sends `filter-search:applied` with { visible, total }.
export class FilterSearch {
  constructor(element) {
    this.element = element;
    this.input = element.querySelector('[data-filter-input]');
    this.list = element.querySelector('[data-filter-suggestions]');
    this.fields = JSON.parse(element.querySelector('script[type="application/json"]').textContent).fields;
    this.keys = this.fields.map((f) => f.key);
    this.scope = element.closest('[data-filter-scope]') || document.body;
    this.matcher = new FilterRowMatcher(this.fields);
    this.suggestions = new FilterSuggestions(this.fields);
    this.shown = [];
    this.active = -1;
    this.listen();
    this.apply();
  }

  get query() {
    return FilterQuery.parse(this.input.value, this.keys);
  }

  listen() {
    this.input.addEventListener('input', () => { this.apply(); this.suggest(); });
    this.input.addEventListener('focus', () => { this.closeMenus(); this.suggest(); });
    this.input.addEventListener('click', () => this.suggest());
    this.input.addEventListener('keydown', (event) => this.onKey(event));
    this.input.addEventListener('blur', () => { this.hideSuggestions(); this.apply(); });
    // Pick with the mouse without the box losing focus first.
    this.list.addEventListener('mousedown', (event) => event.preventDefault());
    this.list.addEventListener('click', (event) => {
      const option = event.target.closest('[data-suggestion]');
      if (option) this.accept(this.shown[Number(option.dataset.suggestion)]);
    });
    this.element.querySelectorAll('[data-filter-clear]').forEach((button) =>
      button.addEventListener('click', () => { this.setText(''); this.input.focus(); }));
    this.element.querySelectorAll('[data-filter-menu]').forEach((menu) => this.listenToMenu(menu));
    this.scope.addEventListener('filter-search:refresh', () => this.apply());
    this.scope.addEventListener('click', (event) => {
      const toggle = event.target.closest('[data-filter-toggle]');
      if (!toggle || !this.scope.contains(toggle)) return;
      event.preventDefault();
      this.toggle(toggle.dataset.filterToggle, toggle.dataset.filterValue);
    });
    document.addEventListener('click', (event) => {
      if (!this.element.contains(event.target)) this.closeMenus();
    });
  }

  listenToMenu(menu) {
    const button = menu.querySelector('[data-filter-menu-button]');
    const panel = menu.querySelector('[data-filter-menu-panel]');
    const find = menu.querySelector('[data-filter-menu-find]');
    button.addEventListener('click', () => {
      const opening = panel.classList.contains('hidden');
      this.closeMenus();
      if (opening) this.openMenu(menu);
    });
    menu.addEventListener('click', (event) => {
      const option = event.target.closest('[data-filter-option]');
      if (option) this.toggle(option.dataset.key, option.dataset.value);
    });
    menu.addEventListener('keydown', (event) => this.onMenuKey(event, menu));
    if (find) {
      find.addEventListener('input', () => {
        const wanted = find.value.trim().toLowerCase();
        menu.querySelectorAll('[data-filter-option]').forEach((option) =>
          option.classList.toggle('hidden', !option.textContent.toLowerCase().includes(wanted)));
      });
    }
  }

  openMenu(menu) {
    menu.querySelector('[data-filter-menu-panel]').classList.remove('hidden');
    menu.querySelector('[data-filter-menu-button]').setAttribute('aria-expanded', 'true');
    const first = menu.querySelector('[data-filter-menu-find]') || menu.querySelector('[data-filter-option]');
    if (first) first.focus();
  }

  closeMenus() {
    this.element.querySelectorAll('[data-filter-menu]').forEach((menu) => {
      menu.querySelector('[data-filter-menu-panel]').classList.add('hidden');
      menu.querySelector('[data-filter-menu-button]').setAttribute('aria-expanded', 'false');
    });
  }

  // Up and down move between a menu's options; Escape closes it.
  onMenuKey(event, menu) {
    if (event.key === 'Escape') {
      this.closeMenus();
      menu.querySelector('[data-filter-menu-button]').focus();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const options = [...menu.querySelectorAll('[data-filter-option]:not(.hidden)')];
    const at = options.indexOf(document.activeElement);
    const next = event.key === 'ArrowDown' ? Math.min(at + 1, options.length - 1) : Math.max(at - 1, 0);
    if (options[next]) options[next].focus();
  }

  onKey(event) {
    const open = !this.list.classList.contains('hidden');
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) { this.suggest(); return; }
      const count = this.shown.length;
      const from = this.active < 0 ? (event.key === 'ArrowDown' ? -1 : 0) : this.active;
      this.highlight((from + (event.key === 'ArrowDown' ? 1 : -1) + count) % count);
    } else if ((event.key === 'Enter' || event.key === 'Tab') && open && this.active >= 0) {
      event.preventDefault();
      this.accept(this.shown[this.active]);
    } else if (event.key === 'Enter') {
      event.preventDefault();  // never submits the form around it
      this.hideSuggestions();
    } else if (event.key === 'Escape' && open) {
      event.preventDefault();
      this.hideSuggestions();
    }
  }

  setText(text, caret = text.length) {
    this.input.value = text;
    this.input.setSelectionRange(caret, caret);
    this.apply();
  }

  toggle(key, value) {
    this.setText(this.query.withValueToggled(key, value));
  }

  // A field leaves the caret after its colon, for its values; a value ends
  // its token with one space, ready for the next.
  accept(suggestion) {
    const text = this.input.value;
    let before = text.slice(0, suggestion.start) + suggestion.insert;
    let after = text.slice(suggestion.end);
    if (!suggestion.opensValues) {
      before += ' ';
      after = after.replace(/^\s+/, '');
    }
    this.setText(before + after, before.length);
    // A field goes on to its values; after a value, the results show until the next key.
    if (suggestion.opensValues) this.suggest();
    else this.hideSuggestions();
  }

  suggest() {
    if (document.activeElement !== this.input) return;
    this.shown = this.suggestions.at(this.input.value, this.input.selectionStart ?? this.input.value.length);
    if (!this.shown.length) { this.hideSuggestions(); return; }
    this.list.replaceChildren(...this.shown.map((s, i) => this.optionFor(s, i)));
    this.list.classList.remove('hidden');
    this.input.setAttribute('aria-expanded', 'true');
    // Nothing typed yet: list the fields but leave Enter and Tab alone.
    this.highlight(this.typingAToken() ? 0 : -1);
  }

  typingAToken() {
    const caret = this.input.selectionStart ?? this.input.value.length;
    return caret > 0 && !/\s/.test(this.input.value.charAt(caret - 1));
  }

  optionFor(suggestion, index) {
    const option = document.createElement('li');
    option.id = `${this.list.id}-${index}`;
    option.className = 'gg-filter-suggestion';
    option.setAttribute('role', 'option');
    option.dataset.suggestion = String(index);
    const text = document.createElement('span');
    text.className = 'font-mono';
    text.textContent = suggestion.text;
    const hint = document.createElement('span');
    hint.className = 'gg-filter-suggestion-hint';
    hint.textContent = suggestion.hint;
    option.append(text, hint);
    return option;
  }

  highlight(index) {
    this.active = index;
    [...this.list.children].forEach((option, i) => option.setAttribute('aria-selected', String(i === index)));
    const current = this.list.children[index];
    if (current) {
      this.input.setAttribute('aria-activedescendant', current.id);
      current.scrollIntoView({ block: 'nearest' });
    } else {
      this.input.removeAttribute('aria-activedescendant');
    }
  }

  // The query as it filters while a token is still being typed: a word on
  // its way to a field's key (`imp` → `importance:`) is no search yet, and
  // a value being typed (`label:do`) matches the values it starts.
  whileTyping(query) {
    if (document.activeElement !== this.input) return query;
    const caret = this.input.selectionStart ?? this.input.value.length;
    const typing = query.tokens.find((t) => t.start < caret && caret === t.end);
    if (!typing) return query;
    if (typing.kind === 'word') {
      const word = typing.raw.replace(/^-/, '').toLowerCase();
      if (!this.keys.some((key) => key.startsWith(word))) return query;
      return new FilterQuery(query.text, query.tokens.filter((t) => t !== typing));
    }
    const partly = { ...typing, lastValueTyped: true };
    return new FilterQuery(query.text, query.tokens.map((t) => (t === typing ? partly : t)));
  }

  hideSuggestions() {
    this.list.classList.add('hidden');
    this.input.setAttribute('aria-expanded', 'false');
    this.input.removeAttribute('aria-activedescendant');
    this.active = -1;
  }

  // Shows the matching rows, ticks the menus to match the query.
  apply() {
    const query = this.query;
    const filtering = this.whileTyping(query);
    const rows = [...this.scope.querySelectorAll('[data-filter-row]')];
    let visible = 0;
    rows.forEach((row) => {
      const match = this.matcher.matches(row, filtering);
      row.classList.toggle('hidden', !match);
      if (match) visible += 1;
    });
    const empty = this.scope.querySelector('[data-filter-empty]');
    if (empty) empty.classList.toggle('hidden', visible > 0 || !rows.length);
    this.element.querySelectorAll('[data-filter-clear]').forEach((b) => b.classList.toggle('hidden', query.isEmpty));
    this.element.querySelectorAll('[data-filter-menu]').forEach((menu) => {
      const chosen = query.chosenValues(menu.dataset.filterMenu);
      menu.querySelectorAll('[data-filter-option]').forEach((option) =>
        option.setAttribute('aria-checked', String(chosen.has(option.dataset.value))));
      const count = menu.querySelector('[data-filter-menu-count]');
      count.textContent = String(chosen.size);
      count.classList.toggle('hidden', !chosen.size);
    });
    this.scope.dispatchEvent(new CustomEvent('filter-search:applied', { detail: { visible, total: rows.length } }));
  }
}
