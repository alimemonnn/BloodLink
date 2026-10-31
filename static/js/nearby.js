/* Hospital "donors near me" page: read the device's GPS position and reload the page with it.
   The position goes only to this site (in the address of the page) and is not stored unless the
   hospital presses "Save as hospital location". */
(function () {
  "use strict";
  var box = document.getElementById("gpsBox");
  var btn = document.getElementById("gpsUse");
  var note = document.getElementById("gpsNote");
  if (!box || !btn) return;

  function say(text) { if (note) note.textContent = text; }

  function go(pos) {
    var url = new URL(window.location.href);
    url.searchParams.set("lat", pos.coords.latitude.toFixed(5));
    url.searchParams.set("lng", pos.coords.longitude.toFixed(5));
    window.location.href = url.toString();
  }

  function locate(auto) {
    if (!navigator.geolocation) { say("This browser cannot give a GPS location."); return; }
    btn.disabled = true;
    say("Finding your location...");
    navigator.geolocation.getCurrentPosition(go, function (err) {
      btn.disabled = false;
      say(err && err.code === 1
        ? "Location permission was refused, so the city centre is used. Allow location in the browser to use GPS."
        : "Could not get your location. The city centre is used instead.");
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
  }

  btn.addEventListener("click", function () { locate(false); });

  // Ask once automatically when no position is known yet, so the page opens with real distances.
  if (box.getAttribute("data-autolocate") === "1") {
    var key = "bl-" + box.getAttribute("data-key"), done = false;
    try { done = window.sessionStorage.getItem(key) === "1"; window.sessionStorage.setItem(key, "1"); } catch (e) { done = false; }
    if (!done) locate(true);
  }
})();
