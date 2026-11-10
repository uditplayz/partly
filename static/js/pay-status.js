/* Payment return page: while the order is still open, poll its status and reload
   when it changes. Polling only reads; the webhook is what publishes the event. */
(function () {
  "use strict";
  var box = document.querySelector("[data-status-url]");
  if (!box || box.dataset.status !== "CREATED") return;
  var tries = 0;
  var MAX_TRIES = 90; // about three minutes

  function again(delay) {
    tries += 1;
    if (tries < MAX_TRIES) setTimeout(poll, delay);
  }

  function poll() {
    fetch(box.dataset.statusUrl, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(res.status); })
      .then(function (data) {
        if (data.status !== "CREATED") { window.location.reload(); return; }
        again(2000);
      })
      .catch(function () { again(4000); });
  }

  setTimeout(poll, 1500);
})();
