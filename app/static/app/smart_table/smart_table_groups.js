// A smart table's rows in groups, by `data-group-<key>` (`|` between
// several): a heading row per group, then its rows in their sorted order. A
// row in several groups shows under each, as a copy (`data-smart-copy`) after
// the first. The groups follow the option's `values` when it has them, else
// A to Z, with the rows that have none (`emptyLabel`) last. Without an
// option, the rows stay as they are.
const SEPARATOR = '|';
const TONES = [['failed', 'failed'], ['needs_attention', 'need attention'], ['healthy', 'healthy']];

export class SmartTableGroups {
  constructor(option, columns) {
    this.option = option;
    this.columns = columns;
    this.groups = [];
  }

  datasetName() {
    const { key } = this.option;
    return `group${key.charAt(0).toUpperCase()}${key.slice(1)}`;
  }

  arrange(rows) {
    if (!this.option) return rows;
    const members = new Map();
    rows.forEach((row) => {
      const values = (row.dataset[this.datasetName()] || '').split(SEPARATOR).filter(Boolean);
      (values.length ? values : ['']).forEach((value) => {
        if (!members.has(value)) members.set(value, []);
        members.get(value).push(row);
      });
    });
    const placed = new Set();
    const out = [];
    this.groups = this.order([...members.keys()]).map((value) => {
      const heading = this.heading(value);
      const groupRows = members.get(value).map((row) => {
        if (!placed.has(row)) { placed.add(row); return row; }
        const copy = row.cloneNode(true);
        copy.removeAttribute('data-smart-row');
        copy.setAttribute('data-smart-copy', '');
        copy.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
        return copy;
      });
      out.push(heading, ...groupRows);
      return { value, heading, rows: groupRows };
    });
    return out;
  }

  order(values) {
    const known = this.option.values.map((v) => v.value);
    const rank = (value) => {
      if (value === '') return [2, ''];
      const at = known.indexOf(value);
      return at >= 0 ? [0, at] : [1, value.toLowerCase()];
    };
    return values.sort((a, b) => {
      const [ra, ka] = rank(a);
      const [rb, kb] = rank(b);
      if (ra !== rb) return ra - rb;
      return typeof ka === 'number' ? ka - kb : ka.localeCompare(kb);
    });
  }

  labelOf(value) {
    if (value === '') return this.option.emptyLabel || `No ${this.option.label.toLowerCase()}`;
    const known = this.option.values.find((v) => v.value === value);
    return known ? known.label : value;
  }

  heading(value) {
    const row = document.createElement('tr');
    row.className = 'gg-smart-group';
    row.dataset.smartGroup = value;
    const cell = document.createElement('th');
    cell.colSpan = this.columns;
    cell.scope = 'colgroup';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'gg-smart-group-toggle';
    button.dataset.smartGroupToggle = value;
    button.setAttribute('aria-expanded', 'true');
    button.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="gg-smart-chevron" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M5.2 7.2a.75.75 0 0 1 1.06.04L10 11.17l3.74-3.93a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .04-1.06Z" clip-rule="evenodd"/></svg>';
    const label = document.createElement('span');
    label.className = 'gg-smart-group-label';
    label.textContent = this.labelOf(value);
    const count = document.createElement('span');
    count.className = 'gg-smart-group-count';
    count.dataset.smartGroupCount = '';
    const tones = document.createElement('span');
    tones.className = 'gg-smart-group-tones';
    tones.dataset.smartGroupTones = '';
    button.append(label, count, tones);
    cell.append(button);
    row.append(cell);
    return row;
  }

  collapse(collapsed) {
    this.groups.forEach(({ value, heading, rows }) => {
      const closed = collapsed.has(value);
      heading.querySelector('[data-smart-group-toggle]').setAttribute('aria-expanded', String(!closed));
      rows.forEach((row) => row.classList.toggle('gg-smart-collapsed', closed));
    });
  }

  // Each group's shown rows: its count, its rows' health when they have one,
  // and no heading at all when the filters hide every row.
  recount() {
    this.groups.forEach(({ heading, rows }) => {
      const shown = rows.filter((row) => !row.classList.contains('hidden'));
      heading.classList.toggle('hidden', !shown.length);
      heading.querySelector('[data-smart-group-count]').textContent = String(shown.length);
      const tones = heading.querySelector('[data-smart-group-tones]');
      const counted = TONES
        .map(([tone, words]) => [tone, words, shown.filter((row) => row.dataset.smartTone === tone).length])
        .filter(([, , n]) => n);
      tones.replaceChildren(...counted.map(([tone, words, n]) => {
        const part = document.createElement('span');
        part.className = 'gg-smart-group-tone';
        part.title = `${n} ${words}`;
        const dot = document.createElement('span');
        dot.className = `h-2 w-2 rounded-full gg-tone-bg-${tone}`;
        part.append(dot, String(n));
        return part;
      }));
    });
  }
}
