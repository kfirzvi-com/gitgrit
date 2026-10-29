// A filter query as GitHub writes one: free words and qualifiers.
//
//   is:attached label:ci,security -importance:minor "no secrets"
//
// A qualifier is `key:value` for a known field; commas list values (any of
// them matches), a leading `-` negates it, quotes keep spaces in a value.
// Anything else is a free word. Every token must match, so repeating a
// qualifier means all of them.
export class FilterQuery {
  // Words, with quoted parts kept whole (`label:"code quality"`).
  static TOKEN = /(?:[^\s"]+|"[^"]*"?)+/g;

  constructor(text, tokens) {
    this.text = text;
    this.tokens = tokens;
  }

  static parse(text, fieldKeys) {
    const keys = new Set(fieldKeys);
    const tokens = [];
    for (const match of text.matchAll(FilterQuery.TOKEN)) {
      tokens.push(FilterQuery.token(match[0], match.index, keys));
    }
    return new FilterQuery(text, tokens);
  }

  static token(raw, start, keys) {
    const negated = raw.startsWith('-') && raw.length > 1;
    const body = negated ? raw.slice(1) : raw;
    const colon = body.indexOf(':');
    const key = colon > 0 ? body.slice(0, colon).toLowerCase() : '';
    const place = { raw, start, end: start + raw.length };
    if (key && keys.has(key)) {
      return { ...place, kind: 'qualifier', negated, key, values: FilterQuery.values(body.slice(colon + 1)) };
    }
    return { ...place, kind: 'word', negated: false, word: FilterQuery.unquote(raw).toLowerCase() };
  }

  // `ci,"code quality"` → ['ci', 'code quality'] (lower case, empties dropped).
  static values(text) {
    const values = [];
    let current = '';
    let quoted = false;
    for (const char of text) {
      if (char === '"') quoted = !quoted;
      else if (char === ',' && !quoted) { values.push(current); current = ''; }
      else current += char;
    }
    values.push(current);
    return values.map((v) => v.trim().toLowerCase()).filter(Boolean);
  }

  static unquote(text) {
    return text.replace(/"/g, '');
  }

  // A value as the query writes it: quoted when it holds a space or a comma.
  static written(value) {
    return /[\s,"]/.test(value) ? `"${value.replace(/"/g, '')}"` : value;
  }

  qualifiers(key) {
    return this.tokens.filter((t) => t.kind === 'qualifier' && t.key === key);
  }

  // The values the query asks for (not negated) under `key`.
  chosenValues(key) {
    return new Set(this.qualifiers(key).filter((t) => !t.negated).flatMap((t) => t.values));
  }

  get isEmpty() {
    return this.text.trim() === '';
  }

  // The query's text with `value` ticked or unticked under `key`: added to
  // the first `key:` qualifier (any of its values matches), or as a new one.
  withValueToggled(key, value) {
    const positive = this.qualifiers(key).filter((t) => !t.negated);
    const holder = positive.find((t) => t.values.includes(value));
    if (holder) {
      const rest = holder.values.filter((v) => v !== value);
      return this.replacing(holder, rest.length ? FilterQuery.qualifier(key, rest) : '');
    }
    if (positive.length) {
      return this.replacing(positive[0], FilterQuery.qualifier(key, [...positive[0].values, value]));
    }
    return FilterQuery.tidy(`${this.text} ${FilterQuery.qualifier(key, [value])}`);
  }

  static qualifier(key, values) {
    return `${key}:${values.map(FilterQuery.written).join(',')}`;
  }

  replacing(token, replacement) {
    return FilterQuery.tidy(this.text.slice(0, token.start) + replacement + this.text.slice(token.end));
  }

  // Single spaces, and a trailing one so typing carries on with a new token.
  static tidy(text) {
    const tidied = text.replace(/\s+/g, ' ').trim();
    return tidied ? `${tidied} ` : '';
  }
}
