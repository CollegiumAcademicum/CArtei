// Confidentiality clearance grant (#65): "Prüfen" opens the VE in a
// picture-in-picture window; the grant dialog only submits once the exact name
// is typed (no paste/drop). Delegated on document and wired once: the AJAX
// .ca-main swap re-runs this script on every in-place form submit.
(function() {
  if (window.caClearanceWired) return;
  window.caClearanceWired = true;

  function dialog() { return document.getElementById('clearance-dialog'); }

  function reset(dlg) {
    var input = dlg.querySelector('#clearance-confirm');
    input.value = '';
    dlg.querySelector('#clearance-submit').disabled = true;
  }

  function review(src, kind) {
    if (!('documentPictureInPicture' in window)) {
      window.open(src, 'clearance-review', 'popup,width=520,height=720');
      return;
    }
    documentPictureInPicture.requestWindow({width: 520, height: 720}).then(function(pip) {
      var el = pip.document.createElement(kind === 'pdf' ? 'iframe' : 'img');
      el.src = src;
      el.style.cssText = 'width:100%;height:100%;border:0;object-fit:contain;display:block;';
      pip.document.body.style.margin = '0';
      pip.document.body.append(el);
    });
  }

  document.addEventListener('click', function(e) {
    var pipBtn = e.target.closest('[data-pip-src]');
    if (pipBtn) { review(pipBtn.dataset.pipSrc, pipBtn.dataset.pipKind); return; }
    var grantBtn = e.target.closest('[data-clearance-grant]');
    var dlg = dialog();
    if (grantBtn && dlg) {
      reset(dlg);
      dlg.querySelector('form').action = grantBtn.dataset.clearanceGrant;
      dlg.showModal();
      return;
    }
    if (e.target.closest('[data-clearance-cancel]') && dlg) dlg.close();
  });

  document.addEventListener('input', function(e) {
    if (e.target.id !== 'clearance-confirm') return;
    var dlg = dialog();
    dlg.querySelector('#clearance-submit').disabled = e.target.value.trim() !== dlg.dataset.name;
  });

  ['paste', 'drop', 'dragover'].forEach(function(type) {
    document.addEventListener(type, function(e) {
      if (e.target.id === 'clearance-confirm') e.preventDefault();
    });
  });

  // 'close' doesn't bubble — listen in the capture phase.
  document.addEventListener('close', function(e) {
    if (e.target.id === 'clearance-dialog') reset(e.target);
  }, true);
})();
