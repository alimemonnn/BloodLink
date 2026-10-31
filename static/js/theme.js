/* Theme picker (Light / Dark / Classic). The choice stays in this browser only. */
(function () {
  "use strict";
  var themes = { aurora: "light", night: "dark", classic: "light" };
  var colour = { aurora: "#10203b", night: "#0c1322", classic: "#c8102e" };
  var root = document.documentElement;
  function mark() {
    var now = root.getAttribute("data-theme");
    document.querySelectorAll("[data-theme-choice]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-theme-choice") === now ? "true" : "false");
    });
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta && colour[now]) meta.setAttribute("content", colour[now]);
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-choice]");
    if (!b) return;
    var t = b.getAttribute("data-theme-choice");
    if (!themes[t]) return;
    root.setAttribute("data-theme", t);
    root.setAttribute("data-bs-theme", themes[t]);
    try { localStorage.setItem("bl-theme", t); } catch (err) { /* private mode: still applies for this visit */ }
    mark();
  });
  mark();
})();
