// Show every time in the viewer's own timezone.
// The server renders times in UTC inside <time datetime="ISO" data-local-time>;
// this rewrites the text in the browser's zone. [data-local-title="ISO"] does the same for a hover title. The format
// comes from the nearest [data-time-format]: "time", "date", "log", "full"
// (date + time + zone name: hover titles, the run "When" field), or the
// default "datetime". htmx:load fires on page load and on each swapped-in
// piece, so content loaded later is covered too.
(function () {
  // The year only when it is not this year, to keep time columns narrow.
  var DATETIME = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };
  var FORMATS = {
    time: { hour: "2-digit", minute: "2-digit" },
    date: { day: "numeric", month: "short", year: "numeric" },
    log: {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      fractionalSecondDigits: 3, timeZoneName: "short",
    },
    full: {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZoneName: "short",
    },
  };

  function format(date, kind) {
    if (FORMATS[kind]) return date.toLocaleString(undefined, FORMATS[kind]);
    var opts = date.getFullYear() === new Date().getFullYear()
      ? DATETIME : Object.assign({ year: "numeric" }, DATETIME);
    return date.toLocaleString(undefined, opts);
  }

  function kindOf(el) {
    var scope = el.closest("[data-time-format]");
    return scope ? scope.dataset.timeFormat : "datetime";
  }

  function formatTimes(root) {
    if (!root.querySelectorAll) return;
    var times = Array.prototype.slice.call(root.querySelectorAll("[data-local-time]"));
    var titles = Array.prototype.slice.call(root.querySelectorAll("[data-local-title]"));
    if (root.matches && root.matches("[data-local-time]")) times.push(root);
    if (root.matches && root.matches("[data-local-title]")) titles.push(root);
    times.forEach(function (el) {
      var date = new Date(el.getAttribute("datetime"));
      if (!isNaN(date)) el.textContent = format(date, kindOf(el));
    });
    titles.forEach(function (el) {
      var date = new Date(el.dataset.localTitle);
      if (!isNaN(date)) el.title = format(date, "full");
    });
  }

  document.addEventListener("htmx:load", function (e) { formatTimes(e.detail.elt); });
  document.addEventListener("DOMContentLoaded", function () { formatTimes(document); });
})();
