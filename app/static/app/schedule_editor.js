// The standards table's "Runs" editor (partials/schedule_editor.html).
//
// A cron expression is built the way the filter search builds a query: type
// it (the box suggests values for the field the caret is in, and names that
// field), or tick values in each field's menu, or start from a preset. The
// server reads the result back in words with its next times
// (schedule_preview), so nobody has to guess what a "*" means.
//
// Opened for one row (its chip) or the selected rows (the bulk "Runs"
// action); Apply writes each row's trigger-/schedule-/schedule_tz- fields and
// its chip. The table's Save saves them.
(function () {
  if (window.openScheduleEditor) return;

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var DEFAULT_CRON = '0 9 * * *';

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function range(a, b) { var out = []; for (var i = a; i <= b; i++) out.push(i); return out; }

  // The five fields, in cron order: what each accepts, its menu, and what the
  // box suggests while the caret is in it.
  var FIELDS = [
    {
      label: 'Minute', any: 'every minute', hint: '0–59', min: 0, max: 59,
      name: function (n) { return ':' + pad(n); },
      every: 'Every minute',
      steps: [[5, 'Every 5 min'], [10, 'Every 10 min'], [15, 'Every 15 min'], [30, 'Every 30 min']],
      values: range(0, 11).map(function (i) { return i * 5; }),
      suggest: [['0', 'on the hour'], ['30', 'at half past'], ['*/15', 'every 15 minutes'], ['*/5', 'every 5 minutes'], ['*', 'every minute']],
    },
    {
      label: 'Hour', any: 'every hour', hint: '0–23', min: 0, max: 23,
      name: function (n) { return pad(n) + ':00'; },
      every: 'Every hour',
      steps: [[2, 'Every 2h'], [3, 'Every 3h'], [6, 'Every 6h'], [12, 'Every 12h']],
      values: range(0, 23),
      suggest: [['9', '09:00'], ['0', 'midnight'], ['12', 'noon'], ['9-17', '09:00 through 17:00'], ['*/6', 'every 6 hours'], ['*', 'every hour']],
    },
    {
      label: 'Day of month', any: 'every day', hint: '1–31', min: 1, max: 31,
      name: function (n) { return String(n); },
      every: 'Every day',
      steps: [[2, 'Every 2 days'], [7, 'Every 7 days']],
      values: range(1, 31),
      suggest: [['*', 'every day'], ['1', 'on the 1st'], ['15', 'on the 15th'], ['1,15', 'on the 1st and 15th'], ['*/2', 'every 2 days']],
    },
    {
      label: 'Month', any: 'every month', hint: '1–12 or JAN–DEC', min: 1, max: 12,
      name: function (n) { return MONTHS[n - 1]; },
      every: 'Every month',
      steps: [[3, 'Every 3 months'], [6, 'Every 6 months']],
      values: range(1, 12),
      suggest: [['*', 'every month'], ['*/3', 'every quarter'], ['1', 'January'], ['1-6', 'January through June']],
    },
    {
      label: 'Day of week', any: 'any day', hint: '0–6 (Sun–Sat) or MON–SUN', min: 0, max: 6,
      name: function (n) { return DAYS[n % 7]; },
      every: 'Any day',
      steps: [],
      shortcuts: [['1-5', 'Weekdays'], ['0,6', 'Weekends']],
      values: [1, 2, 3, 4, 5, 6, 0],
      suggest: [['*', 'any day of the week'], ['1-5', 'Monday to Friday'], ['0,6', 'weekends'], ['1', 'Monday'], ['5', 'Friday']],
    },
  ];

  var PRESETS = {
    hourly: function (m) { return m.minute + ' * * * *'; },
    daily: function (m) { return m.minute + ' ' + m.hour + ' * * *'; },
    weekdays: function (m) { return m.minute + ' ' + m.hour + ' * * 1-5'; },
    weekly: function (m) { return m.minute + ' ' + m.hour + ' * * 1'; },
    monthly: function (m) { return m.minute + ' ' + m.hour + ' 1 * *'; },
  };

  // --- reading a field ------------------------------------------------------

  var NAMES = {};
  MONTHS.forEach(function (m, i) { NAMES[m.toLowerCase()] = i + 1; });
  DAYS.forEach(function (d, i) { NAMES[d.toLowerCase()] = i; });

  function number(token) {
    var lower = token.toLowerCase();
    return lower in NAMES ? NAMES[lower] : parseInt(token, 10);
  }

  // The plain values a field lists (1,3,5 / 1-5), or null for steps and "*".
  function listedValues(field, text) {
    if (!text || text === '*' || text.indexOf('/') >= 0) return null;
    var values = [];
    var ok = text.split(',').every(function (item) {
      var parts = item.split('-');
      if (parts.length === 1 && !isNaN(number(parts[0]))) { values.push(number(parts[0]) % (field.max === 6 ? 7 : 1000)); return true; }
      if (parts.length === 2 && !isNaN(number(parts[0])) && !isNaN(number(parts[1]))) {
        range(number(parts[0]), number(parts[1])).forEach(function (v) { values.push(v % (field.max === 6 ? 7 : 1000)); });
        return true;
      }
      return false;
    });
    return ok ? values : null;
  }

  // Values back into a field: runs of three or more become ranges (1-5).
  function compress(values) {
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    var out = [], i = 0;
    while (i < sorted.length) {
      var j = i;
      while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
      if (j - i >= 2) out.push(sorted[i] + '-' + sorted[j]);
      else for (var k = i; k <= j; k++) out.push(String(sorted[k]));
      i = j + 1;
    }
    return out.join(',') || '*';
  }

  // A field in a few words, for its menu button.
  function fieldWords(index, text) {
    var field = FIELDS[index];
    if (!text) return '—';
    if (text === '*') return field.any;
    var step = text.match(/^\*\/(\d+)$/);
    if (step) return 'every ' + step[1];
    if (index === 4 && text === '1-5') return 'weekdays';
    if (index === 4 && (text === '0,6' || text === '6,0')) return 'weekends';
    var values = listedValues(field, text);
    if (!values) return text;
    if (values.length > 4) return values.length + ' picked';
    return values.map(field.name).join(', ');
  }

  // --- the editor -----------------------------------------------------------

  function Editor(dialog) {
    this.dialog = dialog;
    this.input = dialog.querySelector('[data-cron-input]');
    this.suggestions = dialog.querySelector('[data-cron-suggestions]');
    this.caretField = dialog.querySelector('[data-cron-caret-field]');
    this.fieldsBox = dialog.querySelector('[data-cron-fields]');
    this.applyButton = dialog.querySelector('[data-schedule-apply]');
    this.rows = [];
    this.timeZone = 'UTC';
    this.valid = false;
    this.lastPreview = null;
    this.active = -1;
    this.buildFields();
    this.bind();
  }

  Editor.prototype.fields = function () {
    var parts = this.input.value.trim().split(/\s+/);
    while (parts.length < 5) parts.push('');
    return parts;
  };

  Editor.prototype.setField = function (index, value) {
    var parts = this.fields();
    parts[index] = value;
    this.input.value = parts.slice(0, Math.max(5, parts.length)).join(' ').trim();
    this.changed();
  };

  Editor.prototype.trigger = function () {
    var picked = this.dialog.querySelector('[data-trigger-choice]:checked');
    return picked ? picked.value : 'changes';
  };

  // Which field the caret is in: the number of spaces before it.
  Editor.prototype.caretIndex = function () {
    var before = this.input.value.slice(0, this.input.selectionStart || 0);
    var index = before.replace(/^\s+/, '').split(/\s+/).length - 1;
    return Math.min(Math.max(index, 0), 4);
  };

  Editor.prototype.buildFields = function () {
    var self = this;
    this.fieldsBox.innerHTML = '';
    FIELDS.forEach(function (field, index) {
      var wrap = document.createElement('div');
      wrap.className = 'relative';
      wrap.dataset.cronField = index;
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'gg-cron-field';
      button.setAttribute('aria-haspopup', 'true');
      button.setAttribute('aria-expanded', 'false');
      button.innerHTML = '<span class="gg-cron-field-label"></span><span class="gg-cron-field-value" data-value></span><span class="gg-cron-field-words" data-words></span>';
      button.querySelector('.gg-cron-field-label').textContent = field.label;
      button.addEventListener('click', function () { self.toggleMenu(index); });
      var menu = document.createElement('div');
      menu.className = 'gg-filter-menu gg-cron-menu hidden';
      menu.setAttribute('role', 'menu');
      menu.setAttribute('aria-label', field.label);
      wrap.appendChild(button);
      wrap.appendChild(menu);
      self.fieldsBox.appendChild(wrap);
    });
  };

  // A field's menu: "every", its steps and shortcuts (each replaces the
  // field), then its values to tick (several make a list).
  Editor.prototype.fillMenu = function (index) {
    var self = this, field = FIELDS[index];
    var menu = this.fieldsBox.querySelectorAll('.gg-cron-menu')[index];
    var current = this.fields()[index];
    var ticked = listedValues(field, current) || [];
    menu.innerHTML = '';
    function title(text) {
      var p = document.createElement('p');
      p.className = 'gg-filter-menu-title';
      p.textContent = text;
      menu.appendChild(p);
    }
    title(field.label + ' · ' + field.hint);
    // "Every", shortcuts and steps replace the field: compact pills.
    var pills = document.createElement('div');
    pills.className = 'gg-cron-pills';
    menu.appendChild(pills);
    function pill(text, value) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'gg-cron-pill';
      b.setAttribute('role', 'menuitemradio');
      b.setAttribute('aria-checked', current === value ? 'true' : 'false');
      b.textContent = text;
      b.addEventListener('click', function () { self.setField(index, value); self.closeMenus(); });
      pills.appendChild(b);
    }
    pill(field.every, '*');
    (field.shortcuts || []).forEach(function (s) { pill(s[1], s[0]); });
    field.steps.forEach(function (s) { pill(s[1], '*/' + s[0]); });
    title('Or pick ' + (index === 4 ? 'days' : field.label.toLowerCase() + 's'));
    var grid = document.createElement('div');
    grid.className = 'gg-cron-values';
    menu.appendChild(grid);
    field.values.forEach(function (v) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'gg-cron-value';
      b.setAttribute('role', 'menuitemcheckbox');
      b.setAttribute('aria-checked', ticked.indexOf(v) >= 0 ? 'true' : 'false');
      b.textContent = field.name(v);
      b.addEventListener('click', function () {
        var now = listedValues(field, self.fields()[index]) || [];
        var at = now.indexOf(v);
        if (at >= 0) now.splice(at, 1); else now.push(v);
        self.setField(index, compress(now));
        self.fillMenu(index);
      });
      grid.appendChild(b);
    });
  };

  Editor.prototype.toggleMenu = function (index) {
    var wraps = this.fieldsBox.querySelectorAll('[data-cron-field]');
    var menu = wraps[index].querySelector('.gg-cron-menu');
    var open = menu.classList.contains('hidden');
    this.closeMenus();
    if (open) {
      this.fillMenu(index);
      menu.classList.remove('hidden');
      wraps[index].querySelector('button').setAttribute('aria-expanded', 'true');
    }
  };

  Editor.prototype.closeMenus = function () {
    this.fieldsBox.querySelectorAll('.gg-cron-menu').forEach(function (m) { m.classList.add('hidden'); });
    this.fieldsBox.querySelectorAll('.gg-cron-field').forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
  };

  // The field buttons say each field's value and words; the one the caret
  // is in is marked, and named at the end of the box.
  Editor.prototype.syncFields = function () {
    var parts = this.fields();
    var caret = document.activeElement === this.input ? this.caretIndex() : -1;
    this.fieldsBox.querySelectorAll('[data-cron-field]').forEach(function (wrap, i) {
      wrap.querySelector('[data-value]').textContent = parts[i] || '·';
      wrap.querySelector('[data-words]').textContent = fieldWords(i, parts[i]);
      wrap.querySelector('.gg-cron-field').classList.toggle('is-caret', i === caret);
    });
    this.caretField.textContent = caret >= 0 ? FIELDS[caret].label.toLowerCase() + ' · ' + FIELDS[caret].hint : '';
  };

  // Suggestions for the field the caret is in, those starting with what is
  // typed there first.
  Editor.prototype.suggest = function () {
    var self = this, index = this.caretIndex(), typed = this.fields()[index] || '';
    var list = FIELDS[index].suggest.slice();
    if (typed) {
      list.sort(function (a, b) {
        return (b[0].indexOf(typed) === 0) - (a[0].indexOf(typed) === 0);
      });
    }
    this.suggestions.innerHTML = '';
    var head = document.createElement('li');
    head.className = 'gg-filter-menu-title';
    head.textContent = FIELDS[index].label + ' · ' + FIELDS[index].hint;
    this.suggestions.appendChild(head);
    list.forEach(function (item, i) {
      var li = document.createElement('li');
      li.className = 'gg-filter-suggestion';
      li.setAttribute('role', 'option');
      li.dataset.value = item[0];
      li.innerHTML = '<span class="font-mono"></span><span class="gg-filter-suggestion-hint"></span>';
      li.children[0].textContent = item[0];
      li.children[1].textContent = item[1];
      li.addEventListener('mousedown', function (e) { e.preventDefault(); self.pickSuggestion(index, item[0]); });
      self.suggestions.appendChild(li);
    });
    this.active = -1;
    this.suggestions.classList.remove('hidden');
    this.input.setAttribute('aria-expanded', 'true');
  };

  Editor.prototype.hideSuggestions = function () {
    this.suggestions.classList.add('hidden');
    this.input.setAttribute('aria-expanded', 'false');
    this.active = -1;
  };

  Editor.prototype.pickSuggestion = function (index, value) {
    this.setField(index, value);
    // Move to the next field, so a schedule can be typed field by field.
    var parts = this.fields(), at = 0;
    for (var i = 0; i <= index; i++) at += parts[i].length + (i < index ? 1 : 0);
    var next = Math.min(at + 1, this.input.value.length);
    this.input.setSelectionRange(next, next);
    this.syncFields();
    this.suggest();
  };

  Editor.prototype.moveActive = function (delta) {
    var items = this.suggestions.querySelectorAll('.gg-filter-suggestion');
    if (!items.length) return;
    this.active = (this.active + delta + items.length) % items.length;
    items.forEach(function (li, i) { li.setAttribute('aria-selected', i === this.active ? 'true' : 'false'); }, this);
  };

  Editor.prototype.changed = function () {
    this.syncFields();
    this.valid = false; // until the server reads the new text
    this.syncApply();
    var self = this;
    clearTimeout(this.timer);
    this.timer = setTimeout(function () { self.preview(); }, 150);
  };

  // The server reads the schedule: in words, its next times, or the error.
  Editor.prototype.preview = function () {
    var self = this, cron = this.input.value.trim();
    var url = this.dialog.dataset.previewUrl + '?cron=' + encodeURIComponent(cron) + '&tz=' + encodeURIComponent(this.timeZone);
    var asked = cron;
    fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (self.input.value.trim() !== asked) return; // typed on since
        self.lastPreview = data;
        self.valid = !!data.valid;
        var q = function (s) { return self.dialog.querySelector(s); };
        q('[data-cron-error]').textContent = data.valid ? '' : data.error;
        q('[data-cron-error]').classList.toggle('hidden', !!data.valid);
        q('[data-cron-text]').textContent = data.valid ? data.text : 'Not a schedule yet';
        q('[data-cron-text]').classList.toggle('opacity-50', !data.valid);
        q('[data-cron-next-line]').classList.toggle('invisible', !data.valid);
        q('[data-cron-next]').textContent = data.valid ? data.next_runs.join(' · ') : '';
        q('[data-cron-warning]').textContent = data.warning || '';
        q('[data-cron-warning]').classList.toggle('hidden', !data.warning);
        self.syncApply();
      });
  };

  Editor.prototype.syncApply = function () {
    var scheduled = this.trigger() !== 'changes';
    this.dialog.querySelector('[data-schedule-builder]').classList.toggle('gg-schedule-off', !scheduled);
    this.dialog.querySelector('[data-schedule-only-note]').classList.toggle('hidden', this.trigger() !== 'schedule');
    this.applyButton.disabled = scheduled && !this.valid;
  };

  Editor.prototype.bind = function () {
    var self = this;
    ['input', 'click', 'keyup', 'focus'].forEach(function (type) {
      self.input.addEventListener(type, function (e) {
        if (type === 'keyup' && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].indexOf(e.key) >= 0) return;
        self.closeMenus();
        if (type === 'input') self.changed(); else self.syncFields();
        self.suggest();
      });
    });
    this.input.addEventListener('blur', function () { self.hideSuggestions(); self.syncFields(); });
    this.input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); self.moveActive(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); self.moveActive(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault(); // never submits the table's form
        var items = self.suggestions.querySelectorAll('.gg-filter-suggestion');
        if (self.active >= 0 && items[self.active]) self.pickSuggestion(self.caretIndex(), items[self.active].dataset.value);
        else if (!self.applyButton.disabled) self.apply();
      } else if (e.key === 'Escape' && !self.suggestions.classList.contains('hidden')) {
        e.preventDefault(); e.stopPropagation(); self.hideSuggestions();
      }
    });
    this.dialog.querySelectorAll('[data-trigger-choice]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        if (radio.value !== 'changes' && !self.input.value.trim()) { self.input.value = DEFAULT_CRON; self.changed(); }
        self.syncApply();
      });
    });
    this.dialog.querySelectorAll('[data-preset]').forEach(function (button) {
      button.addEventListener('click', function () {
        // Keep the time of day already chosen, when it is one.
        var parts = self.fields();
        var keep = {
          minute: /^\d+$/.test(parts[0]) ? parts[0] : '0',
          hour: /^\d+$/.test(parts[1]) ? parts[1] : '9',
        };
        self.input.value = PRESETS[button.dataset.preset](keep);
        self.changed();
        if (self.trigger() === 'changes') {
          self.dialog.querySelector('[data-trigger-choice][value="schedule"]').checked = true;
          self.syncApply();
        }
      });
    });
    this.dialog.querySelectorAll('[data-schedule-cancel]').forEach(function (b) {
      b.addEventListener('click', function () { self.dialog.close(); });
    });
    this.applyButton.addEventListener('click', function () { self.apply(); });
    this.dialog.addEventListener('click', function (e) {
      // A ticked value redraws its menu, so the button clicked is gone by
      // now: that is a click inside the menu, not outside it.
      if (e.target.isConnected && !e.target.closest('[data-cron-field]')) self.closeMenus();
    });
    this.dialog.addEventListener('close', function () { self.closeMenus(); self.hideSuggestions(); });
  };

  Editor.prototype.open = function (rows, forText) {
    this.rows = rows;
    var first = rows[0];
    var trigger = first.querySelector('[data-trigger-field]').value || 'changes';
    var cron = first.querySelector('[data-schedule-field]').value;
    this.timeZone = first.querySelector('[data-schedule-tz-field]').value || 'UTC';
    this.dialog.querySelector('[data-schedule-for]').textContent = forText;
    this.dialog.querySelector('[data-cron-tz]').textContent = this.timeZone;
    this.dialog.querySelector('[data-trigger-choice][value="' + trigger + '"]').checked = true;
    this.input.value = cron || DEFAULT_CRON;
    this.valid = false;
    this.syncFields();
    this.syncApply();
    this.preview();
    this.dialog.showModal();
    (trigger === 'changes' ? this.dialog.querySelector('[data-trigger-choice]:checked') : this.input).focus();
  };

  Editor.prototype.apply = function () {
    var trigger = this.trigger();
    var data = this.lastPreview || {};
    var cron = trigger === 'changes' ? '' : (data.cron || this.input.value.trim());
    var label = 'On every change';
    if (trigger !== 'changes') {
      label = trigger === 'both' ? 'Changes + ' + data.text.charAt(0).toLowerCase() + data.text.slice(1) : data.text;
    }
    var timeZone = this.timeZone;
    this.rows.forEach(function (row) {
      row.querySelector('[data-trigger-field]').value = trigger;
      row.querySelector('[data-schedule-field]').value = cron;
      row.querySelector('[data-schedule-tz-field]').value = timeZone;
      var chip = row.querySelector('[data-schedule]');
      chip.dataset.trigger = trigger;
      chip.querySelector('[data-schedule-label]').textContent = label;
      chip.title = cron ? cron + ' (' + timeZone + ')' : 'Runs on each matching push and pull request';
      row.dataset.filterRuns = trigger;
    });
    this.dialog.close();
    var picker = this.rows[0] && this.rows[0].closest('.standard-picker');
    if (picker && window.updateStandardPickerCounts) window.updateStandardPickerCounts(picker);
  };

  function editorFor(element) {
    var picker = element.closest('.standard-picker') || document;
    var dialog = picker.querySelector('[data-schedule-editor]');
    if (!dialog._editor) dialog._editor = new Editor(dialog);
    return dialog._editor;
  }

  // A row's chip: edit that standard.
  window.openScheduleEditor = function (chip) {
    var row = chip.closest('tr');
    editorFor(chip).open([row], row.querySelector('[data-standard-name]').textContent.trim());
  };

  // The bulk "Runs" action: edit every selected row.
  window.openScheduleEditorForSelected = function (button) {
    var picker = button.closest('.standard-picker');
    var rows = Array.prototype.filter.call(picker.querySelectorAll('.standard-picker-row'), function (row) {
      return row.querySelector('[data-row-select]').checked;
    });
    if (!rows.length) return;
    editorFor(button).open(rows, rows.length === 1
      ? rows[0].querySelector('[data-standard-name]').textContent.trim()
      : rows.length + ' standards');
  };
})();
