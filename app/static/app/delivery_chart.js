// Delivery charts (partials/delivery_week_chart.html): hovering or focusing a
// week shows its numbers in the chart's tooltip, lights its bar and dims the
// others, and marks its point on the line. Listens on the document once, so
// charts HTMX swaps in later work too (a module runs once however often the
// partial includes it).
const DIM = '0.35';

function activate(bar) {
  const chart = bar.closest('[data-week-chart]');
  if (!chart) return;
  const index = bar.dataset.weekBar;
  chart.querySelectorAll('[data-week-bar]').forEach((other) => {
    other.firstElementChild.style.opacity = other === bar ? '' : DIM;
  });
  chart.querySelectorAll('[data-week-dot]').forEach((dot) => { dot.hidden = dot.dataset.weekDot !== index; });
  const tip = chart.querySelector('[data-week-tip]');
  tip.textContent = bar.dataset.tip;
  tip.hidden = false;
  // Centred over the bar, kept inside the chart.
  const half = tip.offsetWidth / 2;
  const centre = bar.offsetLeft + bar.offsetWidth / 2;
  tip.style.left = `${Math.min(Math.max(centre, half), chart.clientWidth - half)}px`;
}

function reset(chart) {
  if (!chart) return;
  chart.querySelectorAll('[data-week-bar]').forEach((bar) => { bar.firstElementChild.style.opacity = ''; });
  chart.querySelectorAll('[data-week-dot]').forEach((dot) => { dot.hidden = true; });
  chart.querySelector('[data-week-tip]').hidden = true;
}

function leaving(event) {
  const chart = event.target.closest && event.target.closest('[data-week-chart]');
  if (chart && !chart.contains(event.relatedTarget)) reset(chart);
}

document.addEventListener('mouseover', (event) => {
  const bar = event.target.closest && event.target.closest('[data-week-bar]');
  if (bar) activate(bar);
});
document.addEventListener('focusin', (event) => {
  const bar = event.target.closest && event.target.closest('[data-week-bar]');
  if (bar) activate(bar);
});
document.addEventListener('mouseout', leaving);
document.addEventListener('focusout', leaving);
// Arrow keys move along the weeks.
document.addEventListener('keydown', (event) => {
  const bar = event.target.closest && event.target.closest('[data-week-bar]');
  if (!bar || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
  const next = event.key === 'ArrowLeft' ? bar.previousElementSibling : bar.nextElementSibling;
  if (next) { event.preventDefault(); next.focus(); }
});
