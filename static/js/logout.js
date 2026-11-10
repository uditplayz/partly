/* Logout interstitial: ask the SW to drop user-scoped caches (cached tickets/QR passes),
   then continue. Falls back to redirecting after a short timeout. */
(function () {
  "use strict";
  var box = document.querySelector("[data-logout-redirect]");
  var next = (box && box.dataset.logoutRedirect) || "/";
  var done = false;
  function go() { if (!done) { done = true; window.location.replace(next); } }

  function clearViaWorker() {
    return new Promise(function (resolve) {
      if (!("serviceWorker" in navigator)) return resolve();
      navigator.serviceWorker.ready.then(function (reg) {
        var worker = navigator.serviceWorker.controller || reg.active;
        if (!worker) return resolve();
        var channel = new MessageChannel();
        channel.port1.onmessage = function () { resolve(); };
        worker.postMessage({ type: "CLEAR_USER_CACHE" }, [channel.port2]);
      }, resolve);
    });
  }

  // Belt and braces: also clear directly from the page (CacheStorage is shared per origin).
  function clearDirect() {
    if (!("caches" in window)) return Promise.resolve();
    return caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k.indexOf("partly-user-") === 0; })
        .map(function (k) { return caches.delete(k); }));
    }).catch(function () {});
  }

  Promise.all([clearViaWorker(), clearDirect()]).then(go, go);
  setTimeout(go, 1500);
})();
