/* Registers the root-scoped service worker. For signed-in users it also keeps a fresh
   copy of My Tickets in the offline cache, so a QR pass works with no signal. */
(function () {
  "use strict";
  if (!("serviceWorker" in navigator)) return;
  var script = document.currentScript;
  var swUrl = (script && script.dataset.swUrl) || "/serviceworker.js";
  var warmUrl = script && script.dataset.warmUrl;

  function warm() {
    if (!warmUrl || window.location.pathname === warmUrl) return;
    // Once per browser session, and again on event pages, where an RSVP may just have changed.
    var seen = false;
    try { seen = sessionStorage.getItem("partly-warmed") === "1"; } catch (e) {}
    if (seen && window.location.pathname.indexOf("/events/") !== 0) return;
    navigator.serviceWorker.ready.then(function () {
      return fetch(warmUrl, { credentials: "same-origin" });
    }).then(function () {
      try { sessionStorage.setItem("partly-warmed", "1"); } catch (e) {}
    }).catch(function () {});
  }

  window.addEventListener("load", function () {
    navigator.serviceWorker.register(swUrl, { scope: "/" }).then(warm).catch(function (err) {
      console.warn("[partly] service worker registration failed", err);
    });
  });
})();
