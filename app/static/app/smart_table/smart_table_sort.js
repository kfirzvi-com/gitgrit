// The order a smart table's rows take: by `data-sort-<key>`, as numbers or
// text, one way or the other. A row with no value sorts last either way;
// rows that tie keep A to Z by `data-sort-name`.
export class SmartTableSort {
  constructor(option, descending) {
    this.option = option;
    this.descending = descending;
    this.datasetName = `sort${option.key.charAt(0).toUpperCase()}${option.key.slice(1)}`;
  }

  valueOf(row) {
    const raw = row.dataset[this.datasetName] ?? '';
    if (raw === '') return null;
    return this.option.numeric ? Number.parseFloat(raw) : raw;
  }

  compare(a, b) {
    const x = this.valueOf(a);
    const y = this.valueOf(b);
    if (x === null || y === null) return (x === null) - (y === null);
    const order = this.option.numeric ? x - y : x.localeCompare(y, undefined, { numeric: true, sensitivity: 'base' });
    return this.descending ? -order : order;
  }

  sorted(rows) {
    const byName = (a, b) => (a.dataset.sortName || '').localeCompare(b.dataset.sortName || '');
    return [...rows].sort((a, b) => this.compare(a, b) || byName(a, b));
  }
}
