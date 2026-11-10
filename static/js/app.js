/* Small progressive enhancements shared by every page. */
(function () {
  "use strict";
  var THEME_KEY = "partly-theme";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function readPref() { try { return localStorage.getItem(THEME_KEY) || "auto"; } catch (e) { return "auto"; } }
  function writePref(v) { try { localStorage.setItem(THEME_KEY, v); } catch (e) {} }

  function applyTheme(pref) {
    var dark = pref === "dark" || (pref === "auto" && media && media.matches);
    root.setAttribute("data-bs-theme", dark ? "dark" : "light");
    root.setAttribute("data-theme-pref", pref);
    document.querySelectorAll("[data-theme-switch] [data-theme-value]").forEach(function (btn) {
      btn.setAttribute("aria-checked", String(btn.dataset.themeValue === pref));
    });
  }

  if (media && media.addEventListener) {
    media.addEventListener("change", function () { if (readPref() === "auto") applyTheme("auto"); });
  }

  document.addEventListener("click", function (e) {
    var themeBtn = e.target.closest("[data-theme-switch] [data-theme-value]");
    if (themeBtn) {
      writePref(themeBtn.dataset.themeValue);
      applyTheme(themeBtn.dataset.themeValue);
      return;
    }
    var close = e.target.closest("[data-dismiss-flash]");
    if (close) close.closest(".flash").remove();
  });

  // <button data-reload> reloads the page (used by the offline page).
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-reload]")) location.reload();
  });

  // A checkbox with data-hides="#selector" hides that element while it is checked.
  function syncHides(box) {
    var target = document.querySelector(box.dataset.hides);
    if (target) target.hidden = box.checked;
  }
  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-hides]")) syncHides(e.target);
  });

  // <form data-confirm="Question?"> asks before submitting.
  document.addEventListener("submit", function (e) {
    var msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(readPref());
    document.querySelectorAll("[data-hides]").forEach(syncHides);
    // Calm, auto-fading flash messages.
    setTimeout(function () {
      document.querySelectorAll(".flash").forEach(function (el) { el.classList.add("flash--fade"); });
    }, 5000);
  });
})();
