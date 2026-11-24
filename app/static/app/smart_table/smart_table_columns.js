// Which of a smart table's columns show (partials/smart_table_toolbar.html's
// Columns menu). A hidden column's key is listed in the table's
// `data-smart-hidden`, which the toolbar's CSS turns into hiding every cell
// marked `data-smart-column="<key>"` — headers, rows and their group copies
// alike. The server renders the columns' starting choice; the viewer's own
// is kept in this browser, per table.
export class SmartTableColumns {
  constructor(smartTable) {
    this.element = smartTable.element;
    this.columns = smartTable.config.columns || [];
    this.keys = new Set(this.columns.map((c) => c.key));
    this.storageKey = `gitgrit.smart-table.columns.${smartTable.config.nounPlural}`;
    this.hidden = this.read();
    this.apply();
  }

  get enabled() {
    return this.columns.length > 0;
  }

  shows(key) {
    return !this.hidden.has(key);
  }

  toggle(key) {
    if (!this.keys.has(key)) return;
    if (this.hidden.has(key)) this.hidden.delete(key);
    else this.hidden.add(key);
    this.apply();
    this.write();
  }

  apply() {
    if (this.enabled) this.element.dataset.smartHidden = [...this.hidden].join(' ');
  }

  read() {
    const starting = new Set(this.columns.filter((c) => !c.shown).map((c) => c.key));
    try {
      const saved = JSON.parse(window.localStorage.getItem(this.storageKey) || 'null');
      if (Array.isArray(saved)) return new Set(saved.filter((key) => this.keys.has(key)));
    } catch (error) {
      // No storage (a private window, blocked site data): the starting choice.
    }
    return starting;
  }

  write() {
    try {
      window.localStorage.setItem(this.storageKey, JSON.stringify([...this.hidden]));
    } catch (error) {
      // Kept for this page only.
    }
  }
}
