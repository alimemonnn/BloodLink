/* Runs before first paint (a file, so the Content-Security-Policy can forbid inline scripts):
   marks the page as JS-enabled and applies the saved theme without a flash. */
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var themes = { aurora: "light", night: "dark", classic: "light" }, saved = null;
  try { saved = localStorage.getItem("bl-theme"); } catch (e) { /* storage blocked: use the default */ }
  if (!themes[saved]) {
    saved = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "aurora";
  }
  root.setAttribute("data-theme", saved);
  root.setAttribute("data-bs-theme", themes[saved]);
})();
