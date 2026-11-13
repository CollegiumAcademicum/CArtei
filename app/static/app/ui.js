// Small UI behaviors declared with data-* attributes instead of inline on*=
// handlers, which the CSP blocks. Listeners sit on document, so they keep
// working on content swapped in by the AJAX form handler in base.html.
(function () {
  "use strict";

  // data-autosubmit on an input/select: submit its form on change (native submit).
  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
  });

  document.addEventListener("click", function (e) {
    var el;
    // data-toggle-hidden="id": show/hide the element with that id.
    if ((el = e.target.closest("[data-toggle-hidden]"))) {
      var target = document.getElementById(el.dataset.toggleHidden);
      target.hidden = !target.hidden;
    }
    // data-show-modal="id": open that <dialog>.
    if ((el = e.target.closest("[data-show-modal]"))) {
      document.getElementById(el.dataset.showModal).showModal();
    }
    // data-close-dialog: close the enclosing <dialog>.
    if ((el = e.target.closest("[data-close-dialog]"))) {
      el.closest("dialog").close();
    }
    // data-toggle-password="id": reveal/hide a password input.
    if ((el = e.target.closest("[data-toggle-password]"))) {
      var input = document.getElementById(el.dataset.togglePassword);
      input.type = input.type === "password" ? "text" : "password";
    }
  });
})();
