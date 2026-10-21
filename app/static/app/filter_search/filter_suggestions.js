import { FilterQuery } from './filter_query.js';

// What to suggest for the token at the caret: the fields while a key is
// being typed (`imp` → `importance:`), then that field's values
// (`importance:r` → `required`), leaving out values already listed.
//
// A suggestion: { text, hint, insert, start, end, opensValues } — `insert`
// replaces the text between `start` and `end`; a field's (`opensValues`)
// leads on to its values, a value ends the token.
export class FilterSuggestions {
  constructor(fields, limit = 8) {
    this.fields = fields;
    this.limit = limit;
  }

  at(text, caret) {
    const { start, end } = FilterSuggestions.tokenAround(text, caret);
    const typed = text.slice(start, caret);
    const negated = typed.startsWith('-');
    const body = negated ? typed.slice(1) : typed;
    const colon = body.indexOf(':');
    if (colon < 0) return this.forKey(body.toLowerCase(), negated, start, end);
    const field = this.fields.find((f) => f.key === body.slice(0, colon).toLowerCase());
    if (!field) return [];
    const valueStart = start + (negated ? 1 : 0) + colon + 1;
    return this.forValue(field, text.slice(valueStart, caret), valueStart, end);
  }

  // The whole token the caret is in (or an empty one at the caret).
  static tokenAround(text, caret) {
    for (const match of text.matchAll(FilterQuery.TOKEN)) {
      const start = match.index;
      const end = start + match[0].length;
      if (start <= caret && caret <= end) return { start, end };
    }
    return { start: caret, end: caret };
  }

  forKey(prefix, negated, start, end) {
    const sign = negated ? '-' : '';
    return this.fields
      .filter((f) => f.key.startsWith(prefix) || f.label.toLowerCase().startsWith(prefix))
      .map((f) => ({
        text: `${sign}${f.key}:`,
        hint: f.hint ? `${f.label}, ${f.hint}` : f.label,
        insert: `${sign}${f.key}:`,
        start,
        end,
        opensValues: true,
      }))
      .slice(0, this.limit);
  }

  // `typed` is what follows the colon up to the caret: earlier values, then
  // the one being typed after the last comma.
  forValue(field, typed, valueStart, end) {
    const lastComma = typed.lastIndexOf(',');
    const listed = new Set(FilterQuery.values(typed.slice(0, lastComma + 1)));
    const prefix = FilterQuery.unquote(typed.slice(lastComma + 1)).trim().toLowerCase();
    const replaceFrom = valueStart + lastComma + 1;
    return field.values
      .filter((v) => !listed.has(v.value))
      .filter((v) => !prefix || v.value.includes(prefix) || v.label.toLowerCase().includes(prefix))
      .sort((a, b) => FilterSuggestions.rank(a, prefix) - FilterSuggestions.rank(b, prefix))
      .slice(0, this.limit)
      .map((v) => ({
        text: v.label,
        hint: field.label,
        insert: FilterQuery.written(v.value),
        start: replaceFrom,
        end,
        opensValues: false,
      }));
  }

  // Values that start with what was typed come first.
  static rank(value, prefix) {
    return value.value.startsWith(prefix) || value.label.toLowerCase().startsWith(prefix) ? 0 : 1;
  }
}
