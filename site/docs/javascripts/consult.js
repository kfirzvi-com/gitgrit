/* Book-a-consult popup: open/close + submit.
   Front-end only for now — submit shows the thank-you state locally. The POST
   to the app endpoint (app.gitgrit.dev) is wired in a later step. */
(function () {
  "use strict";

  function init() {
    var overlay = document.getElementById("gg-consult");
    if (!overlay) return;

    var formWrap = overlay.querySelector("[data-consult-form]");
    var thanks = overlay.querySelector("[data-consult-thanks]");
    var form = overlay.querySelector("#gg-consult-form");
    var lastFocused = null;

    function open() {
      lastFocused = document.activeElement;
      overlay.hidden = false;
      document.body.style.overflow = "hidden";
      var first = overlay.querySelector("input, textarea");
      if (first) first.focus();
    }

    function close() {
      overlay.hidden = true;
      document.body.style.overflow = "";
      formWrap.hidden = false;
      thanks.hidden = true;
      if (form) form.reset();
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    document.addEventListener("click", function (e) {
      var opener = e.target.closest && e.target.closest("[data-consult-open]");
      if (opener) { e.preventDefault(); open(); return; }
      if (e.target.closest && e.target.closest("[data-consult-close]")) { e.preventDefault(); close(); return; }
      if (e.target === overlay) { close(); }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !overlay.hidden) close();
    });

    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();

        // Honeypot: a filled hidden field means a bot. Silently close.
        var hp = form.querySelector('[name="website"]');
        if (hp && hp.value) { close(); return; }

        if (!form.checkValidity()) { form.reportValidity(); return; }

        var nameField = form.querySelector('[name="name"]');
        var emailField = form.querySelector('[name="email"]');
        var first = ((nameField && nameField.value) || "").trim().split(/\s+/)[0] || "there";
        var email = ((emailField && emailField.value) || "").trim();

        overlay.querySelector("[data-consult-name]").textContent = first;
        overlay.querySelector("[data-consult-email]").textContent = email;

        // TODO(step 3): POST the form to the app endpoint before showing thanks.
        formWrap.hidden = true;
        thanks.hidden = false;
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
