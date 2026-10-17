/* BloodLink front-end behaviour */
(function () {
  "use strict";
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Navbar: shrink and gain a shadow once the page scrolls
  var header = document.getElementById("siteHeader");
  function onScroll() { if (header) header.classList.toggle("is-scrolled", window.scrollY > 12); }
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  // Flash messages stay until dismissed (WCAG 2.2.1: people need time to read them)

  // Ask before destructive actions (delete / cancel)
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) { event.preventDefault(); }
    });
  });

  // Password and confirmation must match before submitting
  document.querySelectorAll("form[data-match-passwords]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var pwd = form.querySelector("[name='password'], [name='new_password']");
      var confirmField = form.querySelector("[name='confirm_password']");
      if (pwd && confirmField && pwd.value !== confirmField.value) {
        event.preventDefault();
        confirmField.classList.add("is-invalid");
        confirmField.focus();
      }
    });
  });

  // Show / hide password
  document.querySelectorAll("[data-toggle-password]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.querySelector(btn.getAttribute("data-toggle-password"));
      if (!input) return;
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.querySelector("i").className = show ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  // A last donation date in the future is never valid
  var today = new Date().toISOString().split("T")[0];
  document.querySelectorAll("input[name='last_donation_date']").forEach(function (input) {
    input.setAttribute("max", today);
  });

  // Reveal-on-scroll
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        io.unobserve(entry.target);
      });
    }, { threshold: 0.15 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("is-visible"); });
  }

  // Blood group tiles: light follows the cursor
  document.querySelectorAll(".type-tile").forEach(function (tile) {
    tile.addEventListener("pointermove", function (e) {
      var r = tile.getBoundingClientRect();
      tile.style.setProperty("--mx", (e.clientX - r.left) + "px");
      tile.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  // Home page: "who can give to whom" explainer
  var compat = document.getElementById("compat");
  if (compat) {
    var map = JSON.parse(compat.getAttribute("data-map"));   // donor group -> groups it can give to
    var link = compat.querySelector("[data-out='link']");
    function select(need) {
      compat.querySelectorAll(".pill").forEach(function (p) { p.classList.toggle("on", p.dataset.need === need); });
      compat.querySelectorAll("[data-out='need']").forEach(function (n) { n.textContent = need; });
      compat.querySelectorAll(".giver").forEach(function (g) {
        var ok = (map[g.dataset.give] || []).indexOf(need) !== -1;
        g.classList.toggle("yes", ok);
        g.classList.toggle("exact", ok && g.dataset.give === need);
      });
      link.href = link.dataset.base + "?blood_group=" + encodeURIComponent(need);
    }
    compat.querySelectorAll(".pill").forEach(function (p) {
      p.addEventListener("click", function () { select(p.dataset.need); });
    });
    select("A+");
  }
})();
