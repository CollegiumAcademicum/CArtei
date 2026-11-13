// Drag-and-drop for all file uploads. Auto-discovers every file input on the
// page and turns its enclosing <form> into a drop zone. Dropping a file assigns
// it to the input and fires `change`, so existing data-autosubmit keeps
// working with zero template changes.
(function () {
  "use strict";

  function fillInput(input, files) {
    if (!files || !files.length) return;
    var dt = new DataTransfer();
    dt.items.add(files[0]); // single-file: every upload here takes one file
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function wireZone(zone) {
    if (zone.dataset.ddWired) return;
    var inputs = zone.querySelectorAll('input[type="file"]');
    // ponytail: skip zones with >1 file input rather than guess which to fill.
    // Upgrade path: route the drop to the file input nearest the cursor.
    if (inputs.length !== 1) return;
    var input = inputs[0];
    zone.dataset.ddWired = "1";

    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        zone.classList.add("ca-dragover");
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        if (ev === "dragleave" && zone.contains(e.relatedTarget)) return;
        zone.classList.remove("ca-dragover");
      });
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      fillInput(input, e.dataTransfer.files);
    });
  }

  // Idempotent (ddWired guard) — safe to re-run after an AJAX .ca-main swap.
  window.caWireDropZones = function () {
    document.querySelectorAll('input[type="file"]').forEach(function (input) {
      var zone = input.closest("form");
      if (zone) wireZone(zone);
    });
  };

  document.addEventListener("DOMContentLoaded", window.caWireDropZones);
})();
