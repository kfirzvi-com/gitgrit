import { SmartTableColumns } from './smart_table_columns.js';
import { SmartTableGroups } from './smart_table_groups.js';
import { SmartTableSelection } from './smart_table_selection.js';
import { SmartTableSort } from './smart_table_sort.js';

// One smart table (partials/smart_table_toolbar.html): sorts and groups the
// `data-smart-row` rows of its `data-smart-table-body` in place, as its
// toolbar menus and its `data-smart-sort` headers choose. The filter search
// in the same `data-filter-scope` hides rows (`hidden`); after each pass
// (`filter-search:applied`) the table recounts its rows and groups.
//
// Grouped by a field a row has several values of (a project in two stacks),
// the row shows under each: copies, `data-smart-copy`, which the filter
// search filters like any row. The choice rides in the address
// (?group=owner&sort=score&dir=desc), and so does the filter search's query
// (?q=…), so a link — or the table fetched again after a bulk change
// (`smart-table:reload`) — reads the same. Which columns show is the
// viewer's own choice (SmartTableColumns), kept in their browser.
export class SmartTable {
  constructor(element) {
    this.element = element;
    this.config = JSON.parse(element.querySelector(':scope > script[type="application/json"]').textContent);
    this.body = element.querySelector('[data-smart-table-body]');
    this.table = this.body.closest('table');
    this.rows = [...this.body.querySelectorAll('[data-smart-row]')];
    this.empty = this.body.querySelector('[data-filter-empty]');
    this.scope = element.closest('[data-filter-scope]');
    this.filtered = Boolean(this.scope && this.scope.querySelector('[data-filter-search]'));
    this.sorts = new Map(this.config.sorts.map((s) => [s.key, s]));
    this.groupOptions = new Map(this.config.groups.map((g) => [g.key, g]));
    this.collapsed = new Set();
    this.columns = new SmartTableColumns(this);
    this.readAddress();
    this.restoreQuery();
    this.decorateHeaders();
    this.selection = element.querySelector('[data-bulk-bar]') ? new SmartTableSelection(this) : null;
    this.listen();
    this.render();
  }

  get filterInput() {
    return this.scope ? this.scope.querySelector('[data-filter-input]') : null;
  }

  // The filter query from the address, into the search box (which then filters).
  restoreQuery() {
    const q = new URLSearchParams(window.location.search).get('q');
    const input = this.filterInput;
    if (!q || !input || input.value) return;
    input.value = q;
    this.scope.dispatchEvent(new CustomEvent('filter-search:refresh'));
  }

  // A row changed in place (a standard's Enabled toggle), maybe in one of its
  // copies: that row becomes the item's own (`data-smart-id`), and the table
  // is laid out again from it, so every copy and its group follow.
  adopt(row) {
    if (!row || !row.dataset.smartId) return;
    const at = this.rows.findIndex((r) => r.dataset.smartId === row.dataset.smartId);
    if (at < 0) return;
    if (this.rows[at] !== row) {
      row.removeAttribute('data-smart-copy');
      row.setAttribute('data-smart-row', '');
      this.rows[at] = row;
    }
    this.render();
  }

  // After a bulk change: the page's list again, in place.
  reload() {
    const list = this.element.closest('[data-smart-list]');
    if (!list || !window.htmx) { window.location.reload(); return; }
    window.htmx.ajax('GET', window.location.href, { target: list, select: '[data-smart-list]', swap: 'outerHTML' });
  }

  readAddress() {
    const params = new URLSearchParams(window.location.search);
    const sort = params.get('sort');
    this.sort = this.sorts.has(sort) ? sort : this.config.defaultSort;
    const dir = params.get('dir');
    this.descending = dir === 'desc' || dir === 'asc' ? dir === 'desc' : this.sorts.get(this.sort).descending;
    const group = params.get('group');
    this.group = this.groupOptions.has(group) ? group : this.config.defaultGroup || '';
  }

  writeAddress() {
    const params = new URLSearchParams(window.location.search);
    // Only what differs from how the table reads first.
    const set = (key, value, fallback) => (value === fallback ? params.delete(key) : params.set(key, value));
    set('sort', this.sort, this.config.defaultSort);
    set('dir', this.descending ? 'desc' : 'asc', this.sorts.get(this.sort).descending ? 'desc' : 'asc');
    set('group', this.group, this.config.defaultGroup || '');
    const input = this.filterInput;
    if (input) set('q', input.value.trim(), '');
    const query = params.toString();
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`);
  }

  // Each sortable header becomes a button that sorts by its key (again: the other way).
  decorateHeaders() {
    this.table.querySelectorAll('th[data-smart-sort]').forEach((th) => {
      if (!this.sorts.has(th.dataset.smartSort)) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'gg-smart-sort-button';
      button.append(...th.childNodes);
      const arrow = document.createElement('span');
      arrow.className = 'gg-smart-sort-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      button.append(arrow);
      th.append(button);
      button.addEventListener('click', () => this.sortBy(th.dataset.smartSort));
    });
  }

  listen() {
    this.element.querySelectorAll('[data-smart-menu]').forEach((menu) => {
      const button = menu.querySelector('[data-smart-menu-button]');
      button.addEventListener('click', () => {
        const opening = menu.querySelector('[data-smart-menu-panel]').classList.contains('hidden');
        this.closeMenus();
        if (opening) this.openMenu(menu);
      });
      menu.addEventListener('keydown', (event) => this.onMenuKey(event, menu));
    });
    this.element.addEventListener('click', (event) => {
      const option = event.target.closest('[data-smart-option]');
      if (option) this.choose(option.dataset.smartOption, option.dataset.value);
      const header = event.target.closest('[data-smart-group-toggle]');
      if (header) this.toggleGroup(header.dataset.smartGroupToggle);
    });
    document.addEventListener('click', (event) => {
      if (!event.target.closest('[data-smart-menu]')) this.closeMenus();
    });
    if (this.scope) {
      this.scope.addEventListener('filter-search:applied', () => { this.recount(); this.writeAddress(); });
    }
    this.element.addEventListener('smart-table:reload', () => this.reload());
    this.element.addEventListener('smart-table:row-changed', (event) => this.adopt(event.target.closest('tr')));
  }

  openMenu(menu) {
    menu.querySelector('[data-smart-menu-panel]').classList.remove('hidden');
    menu.querySelector('[data-smart-menu-button]').setAttribute('aria-expanded', 'true');
    const ticked = menu.querySelector('[data-smart-option][aria-checked="true"]') || menu.querySelector('[data-smart-option]');
    if (ticked) ticked.focus();
  }

  closeMenus() {
    this.element.querySelectorAll('[data-smart-menu]').forEach((menu) => {
      menu.querySelector('[data-smart-menu-panel]').classList.add('hidden');
      menu.querySelector('[data-smart-menu-button]').setAttribute('aria-expanded', 'false');
    });
  }

  onMenuKey(event, menu) {
    if (event.key === 'Escape') {
      this.closeMenus();
      menu.querySelector('[data-smart-menu-button]').focus();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const options = [...menu.querySelectorAll('[data-smart-option]')];
    const at = options.indexOf(document.activeElement);
    const next = event.key === 'ArrowDown' ? Math.min(at + 1, options.length - 1) : Math.max(at - 1, 0);
    if (options[next]) options[next].focus();
  }

  choose(kind, value) {
    if (kind === 'column') {
      // The menu stays open: several columns are often turned at once.
      this.columns.toggle(value);
      this.showChoice();
      return;
    }
    if (kind === 'group') {
      this.group = value;
      this.collapsed.clear();
      this.closeMenus();
    } else if (kind === 'sort') {
      this.sortBy(value);
      return;
    } else if (kind === 'dir') {
      this.descending = value === 'desc';
    }
    this.render();
  }

  // A new key sorts in its own direction; the current one turns around.
  sortBy(key) {
    if (key === this.sort) this.descending = !this.descending;
    else {
      this.sort = key;
      this.descending = this.sorts.get(key).descending;
    }
    this.render();
  }

  toggleGroup(value) {
    if (this.collapsed.has(value)) this.collapsed.delete(value);
    else this.collapsed.add(value);
    this.groups.collapse(this.collapsed);
  }

  render() {
    const sorted = new SmartTableSort(this.sorts.get(this.sort), this.descending).sorted(this.rows);
    const option = this.groupOptions.get(this.group);
    this.groups = new SmartTableGroups(option, this.table.querySelector('thead tr').children.length);
    this.body.replaceChildren(...this.groups.arrange(sorted), ...(this.empty ? [this.empty] : []));
    this.groups.collapse(this.collapsed);
    if (this.selection) this.selection.syncCopies();
    // Copies carry the row's HTMX controls (a standard's Enabled toggle): wire them up.
    if (window.htmx) this.body.querySelectorAll('[data-smart-copy]').forEach((copy) => window.htmx.process(copy));
    this.showChoice();
    this.writeAddress();
    // The copies are new rows: the filter search hides the ones that don't match, then we recount.
    if (this.filtered) this.scope.dispatchEvent(new CustomEvent('filter-search:refresh'));
    else this.recount();
  }

  // Ticks the menus and marks the header the table is sorted by.
  showChoice() {
    const sort = this.sorts.get(this.sort);
    const group = this.groupOptions.get(this.group);
    this.element.querySelectorAll('[data-smart-option]').forEach((option) => {
      const { smartOption: kind, value } = option.dataset;
      const ticked = (kind === 'group' && value === this.group)
        || (kind === 'sort' && value === this.sort)
        || (kind === 'dir' && value === (this.descending ? 'desc' : 'asc'))
        || (kind === 'column' && this.columns.shows(value));
      option.setAttribute('aria-checked', String(ticked));
    });
    const groupMenu = this.element.querySelector('[data-smart-menu="group"] [data-smart-menu-current]');
    if (groupMenu) groupMenu.textContent = group ? group.label : 'None';
    this.element.querySelector('[data-smart-menu="sort"] [data-smart-menu-current]').textContent = sort.label;
    this.element.querySelector('[data-smart-direction]').textContent = this.descending ? '↓' : '↑';
    this.table.querySelectorAll('th[data-smart-sort]').forEach((th) => {
      const current = th.dataset.smartSort === this.sort;
      if (current) th.setAttribute('aria-sort', this.descending ? 'descending' : 'ascending');
      else th.removeAttribute('aria-sort');
      const arrow = th.querySelector('.gg-smart-sort-arrow');
      if (arrow) arrow.textContent = current ? (this.descending ? '↓' : '↑') : '↕';
    });
  }

  // How many rows show (a row shown under two groups counts once), and each group's count.
  recount() {
    const visible = this.rows.filter((row) => !row.classList.contains('hidden')).length;
    const { noun, nounPlural } = this.config;
    const total = this.rows.length;
    const name = total === 1 ? noun : nounPlural;
    this.element.querySelector('[data-smart-count]').textContent =
      visible === total ? `${total} ${name}` : `${visible} of ${total} ${name}`;
    this.groups.recount();
  }
}
