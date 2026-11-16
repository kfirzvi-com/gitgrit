import { SmartTable } from './smart_table.js';

// Starts every smart table on the page, and those HTMX swaps in later.
function start(root) {
  root.querySelectorAll('[data-smart-table]:not([data-smart-table-started])').forEach((element) => {
    element.dataset.smartTableStarted = '1';
    new SmartTable(element);
  });
}

start(document);
document.addEventListener('htmx:load', (event) => start(event.detail.elt));
