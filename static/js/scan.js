/* Camera scan of the donor's QR code. Uses the browser's built-in BarcodeDetector (Chrome/Edge/Android).
   Where it is missing the button stays hidden and the short code can be typed instead. */
(function () {
  "use strict";
  var btn = document.getElementById("scanBtn");
  if (!btn || !("BarcodeDetector" in window) || !navigator.mediaDevices) return;
  btn.hidden = false;
  var box = document.getElementById("scanBox"), video = document.getElementById("scanVideo");
  var note = document.getElementById("scanNote"), input = document.getElementById("code");
  var stream = null, timer = null;
  function stop() { clearInterval(timer); if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; box.hidden = true; }
  btn.addEventListener("click", function () {
    var detector = new BarcodeDetector({ formats: ["qr_code"] });
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (s) {
      stream = s; video.srcObject = s; box.hidden = false; note.textContent = "Point the camera at the donor's code."; video.play();
      timer = setInterval(function () {
        detector.detect(video).then(function (codes) {
          if (!codes.length) return;
          var raw = codes[0].rawValue || "", m = raw.match(/code=([0-9A-Za-z-]+)/);
          input.value = m ? m[1] : raw; stop(); input.form.submit();
        }).catch(function () {});
      }, 400);
    }).catch(function () { note.textContent = "The camera could not be opened. Type the short code instead."; box.hidden = false; });
  });
  window.addEventListener("pagehide", stop);
})();
