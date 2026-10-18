/* Asks the browser for a position once, when the donor presses the button, and sends it rounded. */
(function () {
  "use strict";
  var btn = document.getElementById("areaBtn"), note = document.getElementById("areaNote");
  if (!btn || !("geolocation" in navigator)) return;
  btn.hidden = false;
  btn.addEventListener("click", function () {
    note.textContent = "Finding your area...";
    navigator.geolocation.getCurrentPosition(function (p) {
      document.getElementById("areaLat").value = p.coords.latitude.toFixed(2);
      document.getElementById("areaLng").value = p.coords.longitude.toFixed(2);
      document.getElementById("areaForm").submit();
    }, function (e) {
      note.textContent = e.code === 1 ? "Permission was denied, so nothing was saved." : "Your position could not be found.";
    }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 });
  });
})();
