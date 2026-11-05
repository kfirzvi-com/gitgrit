// Rewrites every <time data-localize> (the local_time tag, app/templatetags/
// time_tags.py) from UTC into the browser's own time zone, in the template's
// own Django format (data-format; the letters j d m M N F Y y H i P).
(function () {
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var MONTHS_AP = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  // Django's "P": "4 p.m.", "4:30 a.m.", "midnight", "noon".
  function ampm(d) {
    var h = d.getHours(), m = d.getMinutes();
    if (!m && h === 0) return "midnight";
    if (!m && h === 12) return "noon";
    return (h % 12 || 12) + (m ? ":" + pad(m) : "") + (h < 12 ? " a.m." : " p.m.");
  }
  var LETTERS = {
    j: function (d) { return d.getDate(); },
    d: function (d) { return pad(d.getDate()); },
    m: function (d) { return pad(d.getMonth() + 1); },
    M: function (d) { return MONTHS[d.getMonth()].slice(0, 3); },
    N: function (d) { return MONTHS_AP[d.getMonth()]; },
    F: function (d) { return MONTHS[d.getMonth()]; },
    Y: function (d) { return d.getFullYear(); },
    y: function (d) { return String(d.getFullYear()).slice(-2); },
    H: function (d) { return pad(d.getHours()); },
    i: function (d) { return pad(d.getMinutes()); },
    P: ampm
  };
  function django(d, format) {
    var out = "";
    for (var k = 0; k < format.length; k++) {
      var c = format[k];
      if (c === "\\") out += format[++k] || "";
      else out += LETTERS[c] ? LETTERS[c](d) : c;
    }
    return out;
  }

  var SELECTOR = "time[data-localize]:not([data-localized])";
  function localize(root) {
    var els = Array.prototype.slice.call(root.querySelectorAll(SELECTOR));
    if (root.matches && root.matches(SELECTOR)) els.push(root);
    els.forEach(function (el) {
      var d = new Date(el.dateTime);
      if (isNaN(d)) return;
      el.textContent = django(d, el.dataset.format);
      el.dataset.localized = "1";
    });
  }
  document.addEventListener("DOMContentLoaded", function () { localize(document); });
  document.addEventListener("htmx:load", function (e) { localize(e.detail.elt); });
})();
