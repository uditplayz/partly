/* Live feed filtering + "Load more". The plain GET form still works without JS. */
(function () {
  "use strict";
  var form = document.querySelector("[data-feed-filters]");
  var results = document.getElementById("feed-results");
  if (!form || !results) return;

  var timer = null;
  var controller = null;

  function queryFromForm() {
    var params = new URLSearchParams(new FormData(form));
    // Drop empty and default values so URLs stay short and shareable.
    var clean = new URLSearchParams();
    params.forEach(function (value, key) {
      if (value === "" || (key === "when" && value === "upcoming")) return;
      clean.append(key, value);
    });
    return clean.toString();
  }

  function fetchPartial(url) {
    if (controller) controller.abort();
    controller = "AbortController" in window ? new AbortController() : null;
    results.setAttribute("aria-busy", "true");
    return fetch(url, {
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
      signal: controller ? controller.signal : undefined,
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.text();
    }).finally(function () {
      results.setAttribute("aria-busy", "false");
    });
  }

  function refresh() {
    var qs = queryFromForm();
    var pageUrl = form.action + (qs ? "?" + qs : "");
    fetchPartial(pageUrl).then(function (html) {
      results.innerHTML = html;
      try { history.replaceState(null, "", pageUrl); } catch (e) {}
    }).catch(function (err) {
      if (err && err.name === "AbortError") return;
      window.location.href = pageUrl; // fall back to a normal navigation
    });
  }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(refresh, delay);
  }

  form.addEventListener("change", function (e) {
    if (e.target.name === "area") return; // handled by input
    schedule(0);
  });
  form.addEventListener("input", function (e) {
    if (e.target.name === "area") schedule(250);
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    schedule(0);
  });

  results.addEventListener("click", function (e) {
    var clear = e.target.closest("[data-clear-filters]");
    if (clear) {
      e.preventDefault();
      form.reset();
      form.querySelectorAll("input[type=checkbox]").forEach(function (el) { el.checked = false; });
      var up = form.querySelector("input[name=when][value=upcoming]");
      if (up) up.checked = true;
      var area = form.querySelector("input[name=area]");
      if (area) area.value = "";
      schedule(0);
      return;
    }
    var more = e.target.closest("[data-load-more]");
    if (!more) return;
    e.preventDefault();
    more.classList.add("disabled");
    more.textContent = "Loading…";
    fetchPartial(more.href).then(function (html) {
      var tmp = document.createElement("div");
      tmp.innerHTML = html;
      var list = results.querySelector(".event-list");
      var incoming = tmp.querySelector(".event-list");
      if (list && incoming) {
        while (incoming.firstElementChild) list.appendChild(incoming.firstElementChild);
      }
      more.remove();
      var nextMore = tmp.querySelector("[data-load-more]");
      if (nextMore) results.appendChild(nextMore);
    }).catch(function () {
      window.location.href = more.href;
    });
  });
})();
