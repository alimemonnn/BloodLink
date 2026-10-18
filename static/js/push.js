/* "Alerts on this device": asks permission only when the person presses the button. */
(function () {
  "use strict";
  var box = document.getElementById("pushBox");
  if (!box) return;
  var btn = document.getElementById("pushToggle"), note = document.getElementById("pushNote");
  var csrf = box.getAttribute("data-csrf");
  function say(t) { note.textContent = t; }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    say("This browser does not support push notifications."); btn.disabled = true; return;
  }
  function b64ToBytes(s) {
    var pad = "=".repeat((4 - s.length % 4) % 4), raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }
  function post(url, body) {
    return fetch(url, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body || {}) });
  }
  function refresh(sub) { btn.textContent = sub ? "Turn off alerts on this device" : "Turn on alerts on this device"; btn.dataset.on = sub ? "1" : ""; }
  navigator.serviceWorker.register("/sw.js").then(function (reg) {
    return reg.pushManager.getSubscription().then(function (sub) {
      refresh(sub);
      btn.addEventListener("click", function () {
        btn.disabled = true;
        if (btn.dataset.on) {
          reg.pushManager.getSubscription().then(function (s) {
            if (!s) return null;
            return post("/push/unsubscribe", { endpoint: s.endpoint }).then(function () { return s.unsubscribe(); });
          }).then(function () { refresh(null); say("Alerts are off on this device."); }).finally(function () { btn.disabled = false; });
          return;
        }
        fetch("/push/key", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (k) {
          if (!k.key) { say("Push alerts are not set up on this server yet."); return null; }
          return Notification.requestPermission().then(function (perm) {
            if (perm !== "granted") { say("Permission was not given, so no alerts will be sent."); return null; }
            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(k.key) })
              .then(function (s) { return post("/push/subscribe", s.toJSON()).then(function () { refresh(s); say("Alerts are on for this device."); }); });
          });
        }).catch(function () { say("Could not change the setting. Please try again."); }).finally(function () { btn.disabled = false; });
      });
    });
  }).catch(function () { say("Could not start the notification service."); });
})();
