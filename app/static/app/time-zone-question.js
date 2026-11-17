// The time zone question's placeholder (base.html): only the browser knows
// the device's zone, so send it to the server, which decides whether there
// is anything to ask (app.domain.user_time_zone, rule 6) and answers with
// the question, or with nothing.
(function () {
  var box = document.getElementById('time-zone-question');
  if (!box || !window.htmx) return;
  var zone = '';
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch (e) {
    // No zone to send: the server has nothing to suggest.
  }
  htmx.ajax('POST', box.dataset.url, {
    source: box,
    target: box,
    swap: 'outerHTML',
    values: { device_time_zone: zone },
  });
})();
