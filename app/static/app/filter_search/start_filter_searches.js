import { FilterSearch } from './filter_search.js';

// Starts every filter search box on the page, and those HTMX swaps in later
// (a project's Standards tab loads when first opened).
function start(root) {
  root.querySelectorAll('[data-filter-search]:not([data-filter-search-started])').forEach((element) => {
    element.dataset.filterSearchStarted = '1';
    new FilterSearch(element);
  });
}

start(document);
document.addEventListener('htmx:load', (event) => start(event.detail.elt));
