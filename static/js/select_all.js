/* "Select all" for a group of check-boxes: <input type="checkbox" data-select-all> inside a <fieldset>.
   Ticking it ticks every other box in the same fieldset; it follows the others when they change. */
(function () {
  "use strict";
  document.querySelectorAll("[data-select-all]").forEach(function (master) {
    var group = master.closest("fieldset");
    if (!group) return;
    function boxes() {
      return Array.prototype.filter.call(group.querySelectorAll('input[type="checkbox"]'),
        function (b) { return b !== master; });
    }
    function sync() {
      var all = boxes();
      master.checked = all.length > 0 && all.every(function (b) { return b.checked; });
    }
    master.addEventListener("change", function () {
      boxes().forEach(function (b) { b.checked = master.checked; });
    });
    group.addEventListener("change", function (e) { if (e.target !== master) sync(); });
    sync();
  });
})();
