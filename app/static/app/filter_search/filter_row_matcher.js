// Whether a row matches a FilterQuery. A row says its values in
// `data-filter-<key>` attributes, several joined by `|`
// (`data-filter-label="ci|security"`), all lower case.
export class FilterRowMatcher {
  static SEPARATOR = '|';

  constructor(fields) {
    this.fields = new Map(fields.map((f) => [f.key, f]));
    this.searchedKeys = fields.filter((f) => f.searchedByWords).map((f) => f.key);
  }

  static datasetName(key) {
    return `filter${key.charAt(0).toUpperCase()}${key.slice(1)}`;
  }

  valuesOf(row, key) {
    const raw = row.dataset[FilterRowMatcher.datasetName(key)] || '';
    return raw ? raw.split(FilterRowMatcher.SEPARATOR) : [];
  }

  matches(row, query) {
    return query.tokens.every((token) =>
      token.kind === 'word' ? this.hasWord(row, token.word) : this.meetsQualifier(row, token));
  }

  hasWord(row, word) {
    return this.searchedKeys.some((key) => this.valuesOf(row, key).some((v) => v.includes(word)));
  }

  // Any of the qualifier's values matches; a negated one matches none. A
  // qualifier still being typed (`label:`) filters nothing yet, and its last
  // value, while typed (`lastValueTyped`), matches the values it starts.
  meetsQualifier(row, token) {
    if (!token.values.length) return true;
    const field = this.fields.get(token.key);
    const rowValues = this.valuesOf(row, token.key);
    const last = token.values.length - 1;
    const hit = token.values.some((wanted, i) => rowValues.some((value) => {
      if (field.matchesPart) return value.includes(wanted);
      if (token.lastValueTyped && i === last) return value.startsWith(wanted);
      return value === wanted;
    }));
    return token.negated ? !hit : hit;
  }
}
