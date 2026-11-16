// Bulk edit on a smart table, as on GitHub: a checkbox per row
// (`data-row-select`, its value the item's id), and while any is ticked the
// header row (`data-bulk-header`) gives way to the bulk bar
// (`data-bulk-bar`), whose controls post the change for the selected ids.
//
// A row shown under two groups is one item: ticking either copy ticks both,
// and it counts once. "Select all" ticks every row the filters and folded
// groups leave showing. The bar's HTMX requests get the ids added
// (`htmx:configRequest`); a `data-bulk-confirm` control's confirmation names
// how many it is about to change ("Delete {count}?").
export class SmartTableSelection {
  constructor(table) {
    this.table = table;
    this.element = table.element;
    this.header = this.element.querySelector('[data-bulk-header]');
    this.bar = this.element.querySelector('[data-bulk-bar]');
    this.listen();
    this.update();
  }

  boxes() {
    return [...this.element.querySelectorAll('[data-row-select]')];
  }

  selectedIds() {
    return [...new Set(this.boxes().filter((box) => box.checked).map((box) => box.value))];
  }

  shownBoxes() {
    return this.boxes().filter((box) => {
      const row = box.closest('tr');
      return !row.classList.contains('hidden') && !row.classList.contains('gg-smart-collapsed');
    });
  }

  listen() {
    this.element.addEventListener('change', (event) => {
      const box = event.target;
      if (box.matches('[data-row-select]')) this.tick(box.value, box.checked);
      else if (box.matches('[data-select-all]')) this.toggleAll();
    });
    this.element.addEventListener('click', (event) => {
      if (event.target.closest('[data-bulk-clear]')) this.clear();
    });
    if (this.table.scope) this.table.scope.addEventListener('filter-search:applied', () => this.update());
    document.addEventListener('htmx:configRequest', (event) => {
      if (!this.bar || !this.bar.contains(event.detail.elt)) return;
      const menu = event.detail.elt.closest('[popover]');
      if (menu && menu.hidePopover) menu.hidePopover();
      const ids = this.selectedIds();
      if (event.detail.formData) {
        event.detail.formData.delete('ids');
        ids.forEach((id) => event.detail.formData.append('ids', id));
      } else {
        event.detail.parameters.ids = ids;
      }
    });
    // Bulk menus are popovers (the top layer, never clipped by the table):
    // place each under its button as it opens.
    this.element.addEventListener('beforetoggle', (event) => {
      const menu = event.target;
      if (!menu.classList || !menu.classList.contains('gg-bulk-menu') || event.newState !== 'open') return;
      const opener = this.element.querySelector(`[popovertarget="${menu.id}"]`);
      if (!opener) return;
      const rect = opener.getBoundingClientRect();
      menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 300))}px`;
      menu.style.top = `${rect.bottom + 4}px`;
    }, true);
  }

  // Every copy of the item follows.
  tick(id, checked) {
    this.boxes().filter((box) => box.value === id).forEach((box) => { box.checked = checked; });
    this.update();
  }

  // Ticks every shown row, or unticks them when they all are.
  toggleAll() {
    const shown = [...new Set(this.shownBoxes().map((box) => box.value))];
    const selected = new Set(this.selectedIds());
    const all = shown.length > 0 && shown.every((id) => selected.has(id));
    shown.forEach((id) => this.boxes().filter((box) => box.value === id).forEach((box) => { box.checked = !all; }));
    this.update();
  }

  clear() {
    this.boxes().forEach((box) => { box.checked = false; });
    this.update();
  }

  // Keeps copies made by grouping in step with their row.
  syncCopies() {
    const selected = new Set(this.selectedIds());
    this.boxes().forEach((box) => { box.checked = selected.has(box.value); });
    this.update();
  }

  update() {
    if (!this.bar) return;
    const selected = this.selectedIds();
    const shown = [...new Set(this.shownBoxes().map((box) => box.value))];
    const chosen = new Set(selected);
    const shownSelected = shown.filter((id) => chosen.has(id)).length;
    this.header.classList.toggle('hidden', selected.length > 0);
    this.bar.classList.toggle('hidden', selected.length === 0);
    const { noun, nounPlural } = this.table.config;
    const count = `${selected.length} ${selected.length === 1 ? noun : nounPlural}`;
    this.bar.querySelectorAll('[data-selected-count]').forEach((el) => { el.textContent = count; });
    this.bar.querySelectorAll('[data-bulk-confirm]').forEach((el) => {
      el.setAttribute('hx-confirm', el.dataset.bulkConfirm.replace('{count}', count));
    });
    this.element.querySelectorAll('[data-select-all]').forEach((box) => {
      box.checked = shown.length > 0 && shownSelected === shown.length;
      box.indeterminate = shownSelected > 0 && shownSelected < shown.length;
    });
  }
}
