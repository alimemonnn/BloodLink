/* BloodLink chat: shows new messages by polling a small JSON endpoint, sends quick replies,
   and shares a location only after the person confirms.
   Works without JavaScript too: the form posts normally and the page reloads
   (only "Share my location" needs JavaScript, so it stays hidden without it). */
(function () {
  "use strict";
  var root = document.getElementById("chat");
  if (!root) return;

  var log = document.getElementById("chatLog");
  var empty = document.getElementById("chatEmpty");
  var errorBox = document.getElementById("chatError");
  var form = document.getElementById("chatForm");
  var area = document.getElementById("chatBody");
  var counter = document.getElementById("chatCount");
  var quick = document.getElementById("quickForm");
  var pollUrl = root.getAttribute("data-poll-url");
  var sendUrl = root.getAttribute("data-send-url");
  var locationUrl = root.getAttribute("data-location-url");
  var lastId = parseInt(root.getAttribute("data-last-id"), 10) || 0;
  var csrfField = document.querySelector("#chat [name=csrf_token], #quickForm [name=csrf_token]");
  var csrf = csrfField ? csrfField.value : "";
  var baseTitle = document.title, unseen = 0;
  var delay = 4000, MAX_DELAY = 30000, timer = null, busy = false;

  function showError(text) {
    if (!errorBox) return;
    errorBox.textContent = text || "";
    errorBox.hidden = !text;
  }

  function nearBottom() { return log.scrollHeight - log.scrollTop - log.clientHeight < 80; }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;       // textContent: never interpreted as HTML
    return n;
  }

  function link(href, text) {
    var a = el("a", "", text);
    a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }

  function timeEl(m) {
    var t = el("time", "", " " + m.at);
    t.setAttribute("datetime", m.iso);
    return t;
  }

  function buildMessage(m) {
    if (m.kind === "event") {
      var ev = el("div", "chat-event");
      ev.setAttribute("data-id", m.id);
      var icon = el("i", "fa-solid fa-circle-info"); icon.setAttribute("aria-hidden", "true");
      ev.appendChild(icon); ev.appendChild(document.createTextNode(" " + m.body)); ev.appendChild(timeEl(m));
      return ev;
    }
    var wrap = el("div", "chat-msg " + (m.mine ? "mine" : "theirs") + " role-" + m.role);
    wrap.setAttribute("data-id", m.id);
    var meta = el("div", "chat-meta");
    meta.appendChild(el("strong", "", m.name)); meta.appendChild(timeEl(m));
    wrap.appendChild(meta);
    if (m.kind === "location" && m.location) {
      var box = el("div", "chat-loc");
      var pin = el("i", "fa-solid fa-location-dot"); pin.setAttribute("aria-hidden", "true");
      box.appendChild(pin);
      box.appendChild(document.createTextNode(" "));
      box.appendChild(el("strong", "", "Shared a location"));
      if (m.location.accuracy) box.appendChild(document.createTextNode(" (about " + m.location.accuracy + " m)"));
      if (m.location.state === "ok") {
        var links = el("div", "chat-loc-links");
        links.appendChild(link(m.location.google, "Open in Google Maps"));
        links.appendChild(document.createTextNode(" \u00b7 "));
        links.appendChild(link(m.location.osm, "OpenStreetMap"));
        box.appendChild(links);
      } else {
        box.appendChild(el("div", "small", m.location.state === "admin"
          ? "Location hidden for administrators."
          : "Location no longer shown. Shared locations are hidden after " + m.location.hours + " hours."));
      }
      wrap.appendChild(box);
    } else {
      var body = el("div", "chat-body", m.body);
      body.setAttribute("dir", "auto");                 // right-to-left for Urdu and Sindhi
      wrap.appendChild(body);
    }
    return wrap;
  }

  function addMessage(m) {
    if (log.querySelector('[data-id="' + m.id + '"]')) return false;
    log.insertBefore(buildMessage(m), document.getElementById("end"));
    if (m.id > lastId) lastId = m.id;
    if (empty) empty.hidden = true;
    return true;
  }

  function updatePlan(plan) {
    if (!plan) return;
    var appt = document.getElementById("planAppt"), status = document.getElementById("planStatus");
    var ics = document.getElementById("planIcs");
    if (appt) appt.textContent = plan.appointment || "Not scheduled yet. The hospital will set a time.";
    if (status) status.textContent = plan.status;
    if (ics) ics.hidden = !plan.appointment;
  }

  function closeInputs(note) {
    var tools = root.querySelector(".chat-tools");
    if (tools) tools.remove();
    if (form) {
      var p = el("p", "alert alert-secondary small mb-0", note || "This conversation is read-only.");
      p.id = "chatClosed";
      form.replaceWith(p);
      form = null;
    }
  }

  function bumpTitle(count) {
    if (!document.hidden || !count) return;
    unseen += count;
    document.title = "(" + unseen + ") " + baseTitle;
  }

  function poll() {
    if (busy || document.hidden) { schedule(); return; }
    busy = true;
    fetch(pollUrl + "?after=" + lastId, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("poll " + r.status); return r.json(); })
      .then(function (data) {
        var stick = nearBottom(), added = false;
        data.messages.forEach(function (m) { added = addMessage(m) || added; });
        if (added && stick) log.scrollTop = log.scrollHeight;
        updatePlan(data.plan);
        if (data.can_post === false && form) closeInputs(data.note);
        delay = data.messages.length ? 4000 : Math.min(delay + 1000, 10000);
        showError("");
      })
      .catch(function () { delay = Math.min(delay * 2, MAX_DELAY); })
      .then(function () { busy = false; schedule(); });
  }

  function schedule() { clearTimeout(timer); timer = setTimeout(poll, delay); }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { unseen = 0; document.title = baseTitle; delay = 4000; clearTimeout(timer); poll(); }
  });

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); });
  }

  function sendText(text, done) {
    postJson(sendUrl, { body: text }).then(function (res) {
      if (!res.ok) { showError(res.data.error || "Your message could not be sent."); return; }
      showError("");
      addMessage(res.data.message);
      log.scrollTop = log.scrollHeight;
      delay = 4000;
      if (done) done();
    }).catch(function () { showError("No connection. Your message was not sent."); });
  }

  /* ---- typing area ---- */
  if (form && area) {
    area.addEventListener("input", function () { if (counter) counter.textContent = area.value.length; });
    area.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = area.value.trim();
      if (!text) return;
      var btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      sendText(text, function () { area.value = ""; if (counter) counter.textContent = "0"; });
      setTimeout(function () { btn.disabled = false; area.focus(); }, 400);
    });
  }

  /* ---- quick replies: one tap sends the text ---- */
  if (quick) {
    quick.addEventListener("click", function (e) {
      var b = e.target.closest("button[name=body]");
      if (!b) return;
      e.preventDefault();
      b.disabled = true;
      sendText(b.value, function () { b.disabled = false; });
      setTimeout(function () { b.disabled = false; }, 800);
    });
  }

  /* ---- share my location (asks first, sends one position, never tracks) ---- */
  var locBtn = document.getElementById("locBtn");
  var locConfirm = document.getElementById("locConfirm");
  var locStatus = document.getElementById("locStatus");
  function locSay(text) { if (locStatus) { locStatus.textContent = text || ""; locStatus.hidden = !text; } }

  if (locBtn && locationUrl && "geolocation" in navigator) {
    locBtn.hidden = false;
    locBtn.addEventListener("click", function () { locSay(""); locConfirm.hidden = false; locBtn.hidden = true; });
    document.getElementById("locCancel").addEventListener("click", function () {
      locConfirm.hidden = true; locBtn.hidden = false; locSay("");
    });
    document.getElementById("locSend").addEventListener("click", function () {
      var secure = window.isSecureContext || /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
      if (!secure) { locSay("Location needs a secure (https) connection."); return; }
      var send = document.getElementById("locSend");
      send.disabled = true; locSay("Finding your position...");
      navigator.geolocation.getCurrentPosition(function (pos) {
        postJson(locationUrl, { lat: pos.coords.latitude, lng: pos.coords.longitude,
                                accuracy: pos.coords.accuracy }).then(function (res) {
          send.disabled = false;
          if (!res.ok) { locSay(res.data.error || "Your location could not be sent."); return; }
          addMessage(res.data.message);
          log.scrollTop = log.scrollHeight;
          locConfirm.hidden = true; locBtn.hidden = false; locSay("Location sent.");
        }).catch(function () { send.disabled = false; locSay("No connection. Your location was not sent."); });
      }, function (err) {
        send.disabled = false;
        locSay(err.code === 1 ? "Location permission was denied. Allow it for this site in your browser settings, then try again."
             : err.code === 3 ? "Finding your position took too long. Move to an open area and try again."
             : "Your position could not be found.");
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
    });
  }

  log.scrollTop = log.scrollHeight;
  schedule();
})();
