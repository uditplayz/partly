/* Host door scanner: read a guest's QR pass with the camera, ask the server, and show
   a big result badge with a beep and a buzz. Needs html5-qrcode loaded first. */
(function () {
  "use strict";
  var root = document.querySelector("[data-scanner]");
  if (!root) return;

  var startBtn = root.querySelector("[data-scanner-start]");
  var hint = root.querySelector("[data-scanner-hint]");
  var badge = root.querySelector("[data-badge]");
  var badgeTitle = root.querySelector("[data-badge-title]");
  var badgeDetail = root.querySelector("[data-badge-detail]");
  var RESULT_HOLD_MS = 1500;

  var RESULTS = {
    verified: { tone: "ok", title: "Verified" },
    already_checked_in: { tone: "warn", title: "Already checked in" },
    not_confirmed: { tone: "bad", title: "Not confirmed" },
    wrong_event: { tone: "bad", title: "Pass is for another event" },
    invalid: { tone: "bad", title: "Invalid ticket" },
  };

  var scanner = null;
  var busy = false;
  var audio = null;

  function beep(tone) {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      var notes = tone === "ok" ? [[880, 0], [1320, 0.11]] : tone === "warn" ? [[660, 0], [660, 0.16]] : [[220, 0]];
      notes.forEach(function (note) {
        var osc = audio.createOscillator();
        var gain = audio.createGain();
        osc.frequency.value = note[0];
        osc.connect(gain);
        gain.connect(audio.destination);
        var t = audio.currentTime + note[1];
        gain.gain.setValueAtTime(0.18, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + (tone === "bad" ? 0.4 : 0.1));
        osc.start(t);
        osc.stop(t + (tone === "bad" ? 0.42 : 0.12));
      });
    } catch (e) { /* sound is a nicety */ }
    if (navigator.vibrate) navigator.vibrate(tone === "ok" ? 80 : tone === "warn" ? [60, 60, 60] : 300);
  }

  function setStats(stats) {
    if (!stats) return;
    Object.keys(stats).forEach(function (key) {
      var el = root.querySelector('[data-stat="' + key + '"]');
      if (el) el.textContent = stats[key];
    });
  }

  function show(code, guest) {
    var info = RESULTS[code] || RESULTS.invalid;
    badge.dataset.tone = info.tone;
    badgeTitle.textContent = info.title;
    var detail = "";
    if (guest) {
      detail = guest.name + (guest.plus_ones ? " +" + guest.plus_ones : "");
      if (code === "already_checked_in" && guest.checked_in_at) detail += " · in at " + guest.checked_in_at;
    }
    badgeDetail.textContent = detail;
    badge.hidden = false;
    beep(info.tone);
  }

  function resume() {
    badge.hidden = true;
    busy = false;
    try { if (scanner) scanner.resume(); } catch (e) { /* not paused */ }
  }

  function onScan(text) {
    if (busy) return;
    busy = true;
    try { scanner.pause(true); } catch (e) { /* keep going */ }
    fetch(root.dataset.checkinUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf },
      body: JSON.stringify({ payload: text }),
    })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(res.status); })
      .then(function (data) {
        setStats(data.stats);
        show(data.result, data.guest);
      })
      .catch(function () {
        badge.dataset.tone = "bad";
        badgeTitle.textContent = "Couldn't reach the server";
        badgeDetail.textContent = "Check your connection and scan again.";
        badge.hidden = false;
        beep("bad");
      })
      .finally(function () { setTimeout(resume, RESULT_HOLD_MS); });
  }

  function start() {
    if (typeof Html5Qrcode === "undefined") {
      hint.textContent = "The scanner couldn't load. Reload the page.";
      return;
    }
    startBtn.disabled = true;
    hint.textContent = "Starting the camera…";
    try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { /* no audio */ }
    scanner = new Html5Qrcode("scanner-reader");
    scanner
      .start({ facingMode: "environment" }, { fps: 10, qrbox: { width: 240, height: 240 } }, onScan, function () {})
      .then(function () {
        startBtn.hidden = true;
        hint.textContent = "Point the camera at a guest's pass.";
      })
      .catch(function () {
        startBtn.disabled = false;
        hint.textContent = "Camera unavailable. Allow camera access (it needs HTTPS or localhost), or check guests in from the guest list.";
      });
  }

  startBtn.addEventListener("click", start);

  // Keep the counters fresh when a second phone is also scanning.
  setInterval(function () {
    if (document.hidden) return;
    fetch(root.dataset.statsUrl, { credentials: "same-origin" })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) { if (data) setStats(data.stats); })
      .catch(function () {});
  }, 10000);
})();
