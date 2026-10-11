// "Needs attention" Show all / Show less (components/attention_list.html).
// Delegated, so it covers every list on the page (the dashboard card and the
// notifications pane) and lists swapped in later by HTMX.
document.addEventListener("click", function (e) {
  var toggle = e.target.closest("[data-attention-toggle]");
  if (!toggle) return;
  var list = toggle.closest("[data-attention]");
  var extras = list.querySelectorAll("[data-attention-extra]");
  var expand = extras.length > 0 && extras[0].classList.contains("hidden");
  extras.forEach(function (row) { row.classList.toggle("hidden", !expand); });
  toggle.textContent = expand ? "Show less" : "Show all " + toggle.dataset.total;
});
