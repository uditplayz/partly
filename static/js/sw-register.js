/* Registers the root-scoped service worker. */
(function () {
  "use strict";
  if (!("serviceWorker" in navigator)) return;
  var script = document.currentScript;
  var swUrl = (script && script.dataset.swUrl) || "/serviceworker.js";
  window.addEventListener("load", function () {
    navigator.serviceWorker.register(swUrl, { scope: "/" }).catch(function (err) {
      console.warn("[partly] service worker registration failed", err);
    });
  });
})();
