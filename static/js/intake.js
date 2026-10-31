/* Fills the request form from a pasted message. The server only looks for blood group, units, urgency,
   city, hospital name and a phone number. The person checks and edits everything before sending. */
(function () {
  "use strict";
  var box = document.getElementById("intakeBox");
  if (!box) return;
  var btn = document.getElementById("intakeBtn"), text = document.getElementById("intakeText"), note = document.getElementById("intakeNote");
  btn.addEventListener("click", function () {
    if (!text.value.trim()) { note.textContent = "Paste a message first."; return; }
    fetch(box.getAttribute("data-url"), { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": box.getAttribute("data-csrf") },
      body: JSON.stringify({ text: text.value }) })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var filled = [];
        Object.keys(data.fields || {}).forEach(function (name) {
          var field = document.getElementById(name);
          if (field) { field.value = data.fields[name]; filled.push(name.replace(/_/g, " ")); }
        });
        note.textContent = filled.length
          ? "Filled: " + filled.join(", ") + ". Please check every field and add the patient's name."
          : "Nothing recognisable was found. Please fill the form by hand.";
      }).catch(function () { note.textContent = "Could not read the message. Please fill the form by hand."; });
  });
})();
