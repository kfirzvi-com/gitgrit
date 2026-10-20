// Smart search for the standards picker table (partials/standard_picker.html).
//
// Pure functions, no DOM: `category:value` terms search one column, anything
// else is plain text. Also loadable from node for unit tests (module.exports).
(function (root) {
  // category (as typed) -> canonical category
  var CATEGORIES = {
    name: 'name',
    description: 'description', desc: 'description',
    label: 'label', labels: 'label', tag: 'label', tags: 'label',
    status: 'status',
    level: 'level',
    connected: 'connected', attached: 'connected'
  };

  // Splits on whitespace; double quotes keep spaces together and are dropped:
  // `name:"my std"` and `"name:my std"` both give one token `name:my std`.
  function tokenize(text) {
    var tokens = [], cur = '', quoted = false, has = false;
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (ch === '"') { quoted = !quoted; has = true; continue; }
      if (!quoted && /\s/.test(ch)) {
        if (has) tokens.push(cur);
        cur = ''; has = false;
        continue;
      }
      cur += ch; has = true;
    }
    if (has) tokens.push(cur);
    return tokens;
  }

  // -> {fields: [{category, value}], text}. `text` is what is left over, joined
  // by spaces (an unknown category such as `foo:bar` stays in it as plain text).
  // With no recognised category the whole trimmed query is the text, as before.
  function parseStandardSearch(query) {
    var q = (query || '').trim().toLowerCase();
    var fields = [], rest = [];
    tokenize(q).forEach(function (token) {
      var idx = token.indexOf(':');
      var category = idx > 0 ? CATEGORIES[token.slice(0, idx)] : null;
      var value = idx > 0 ? token.slice(idx + 1).trim() : '';
      if (category && value) fields.push({category: category, value: value});
      else rest.push(token);
    });
    if (!fields.length) return {fields: [], text: q};
    return {fields: fields, text: rest.join(' ')};
  }

  var YES = ['yes', 'true', '1', 'y'], NO = ['no', 'false', '0', 'n'];
  function yesNo(value) {
    if (YES.indexOf(value) !== -1) return true;
    if (NO.indexOf(value) !== -1) return false;
    return null;
  }

  // row: {search, name, description, labels: [..], status, level, connected}
  // (strings lowercased, level a value such as 'critical', connected a
  // boolean). All terms must match.
  function matchStandardRow(parsed, row) {
    if (parsed.text && row.search.indexOf(parsed.text) === -1) return false;
    return parsed.fields.every(function (f) {
      switch (f.category) {
        case 'name': return row.name.indexOf(f.value) !== -1;
        case 'description': return row.description.indexOf(f.value) !== -1;
        case 'label': return row.labels.some(function (l) { return l.indexOf(f.value) !== -1; });
        case 'status': return row.status === f.value;
        case 'level': return row.level === f.value;
        case 'connected': { var k = yesNo(f.value); return k === null ? false : row.connected === k; }
      }
      return false;
    });
  }

  // The search-box text a label chip click should set.
  function labelSearchQuery(label) {
    return /\s/.test(label) ? 'label:"' + label + '"' : 'label:' + label;
  }

  var api = {
    parseStandardSearch: parseStandardSearch,
    matchStandardRow: matchStandardRow,
    labelSearchQuery: labelSearchQuery
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.StandardSearch = api;
})(typeof window !== 'undefined' ? window : this);
