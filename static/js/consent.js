/* Cookie notice. BloodLink sets only strictly necessary cookies, so this
   records the visitor's choice and exposes BloodLinkConsent.allowed() for any
   future optional category: nothing optional loads unless it returns true. */
(function () {
  "use strict";
  var NAME = "bl_consent", DAYS = 180;
  var banner = document.getElementById("cookieBanner");

  function read() {
    var m = document.cookie.match(new RegExp("(?:^|; )" + NAME + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : null;
  }
  function write(value) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    var d = new Date(); d.setTime(d.getTime() + DAYS * 864e5);
    document.cookie = NAME + "=" + encodeURIComponent(value) + "; expires=" + d.toUTCString() +
      "; path=/; SameSite=Lax" + secure;
  }
  window.BloodLinkConsent = {
    // Optional categories are off unless the visitor opted in. None exist today.
    allowed: function (category) { return category === "necessary"; }
  };
  if (!banner) return;

  var opener = null;
  function show(focus) {
    banner.hidden = false;
    if (focus) { var b = banner.querySelector("button"); if (b) b.focus(); }
  }
  function hide() {
    banner.hidden = true;
    if (opener && document.contains(opener)) { opener.focus(); }
    opener = null;
  }
  banner.querySelector("[data-cookie-accept]").addEventListener("click", function () { write("necessary"); hide(); });
  banner.querySelector("[data-cookie-reject]").addEventListener("click", function () { write("necessary"); hide(); });
  banner.addEventListener("keydown", function (e) { if (e.key === "Escape" && read()) hide(); });
  document.querySelectorAll("[data-cookie-settings]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      opener = btn;
      var d = document.getElementById("cookieDetails"); if (d) d.open = true;
      show(true);
    });
  });
  if (!read()) show(false);
})();
