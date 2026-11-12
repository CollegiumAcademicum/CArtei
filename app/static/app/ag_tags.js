// "Meine AGs" tag editor (dashboard): × leaves, the input joins. One change at a
// time; the chip list is only ever replaced by the server's LDAP re-read, never
// updated optimistically. Delegated on document and wired once: the AJAX
// .ca-main swap re-runs this script.
(function() {
  if (window.caAgTagsWired) return;
  window.caAgTagsWired = true;

  var UNEXPECTED = 'Unerwarteter Fehler, Seite neu laden';
  var available = null; // [{cn, description}], fetched on first focus
  var loading = false;

  function block() { return document.getElementById('ag-tags'); }

  function showError(msg) {
    var p = block().querySelector('.ag-tags-error');
    p.textContent = msg;
    p.hidden = false;
  }

  function setBusy(on) {
    var b = block();
    b.querySelectorAll('button, input:not([type=hidden])').forEach(function(el) { el.disabled = on; });
    b.classList.toggle('ag-tags-busy', on);
  }

  function current() {
    return Array.from(block().querySelectorAll('.ag-chip'), function(c) { return c.dataset.cn; });
  }

  function fillOptions() {
    var dl = document.getElementById('ag-tags-options');
    if (!dl || !available) return;
    var mine = current();
    dl.replaceChildren.apply(dl, available.filter(function(g) { return mine.indexOf(g.cn) < 0; }).map(function(g) {
      var o = document.createElement('option');
      o.value = g.cn;
      if (g.description) o.label = g.description + ' · ' + g.cn;
      return o;
    }));
  }

  function json(r) {
    return r.json().catch(function() { return { ok: false, error: UNEXPECTED + ' (HTTP ' + r.status + ')' }; });
  }

  function send(cn, action) {
    var b = block();
    b.querySelector('.ag-tags-error').hidden = true;
    var body = new FormData();
    body.append('csrfmiddlewaretoken', b.querySelector('[name=csrfmiddlewaretoken]').value);
    body.append('group', cn);
    body.append('action', action);
    setBusy(true);
    fetch(b.dataset.url, { method: 'POST', body: body })
      .then(json)
      .then(function(d) {
        if (!d.ok) { setBusy(false); showError(d.error || UNEXPECTED); return; }
        block().outerHTML = d.html;
        fillOptions();
      })
      .catch(function() { setBusy(false); showError(UNEXPECTED); });
  }

  function tryJoin(input) {
    var cn = input.value.trim();
    var known = available && available.some(function(g) { return g.cn === cn; });
    if (known && current().indexOf(cn) < 0) send(cn, 'join');
  }

  document.addEventListener('focusin', function(e) {
    if (available || loading || !e.target.matches('#ag-tags input[name=group]')) return;
    loading = true;
    fetch(block().dataset.availableUrl)
      .then(json)
      .then(function(d) {
        if (!d.groups) throw new Error(d.error || UNEXPECTED);
        available = d.groups;
        fillOptions();
      })
      .catch(function(err) {
        block().querySelector('input[name=group]').disabled = true;
        showError('Gruppenliste nicht ladbar: ' + err.message);
      })
      .finally(function() { loading = false; });
  });

  // Enter in the input.
  document.addEventListener('submit', function(e) {
    if (!e.target.matches('#ag-tags form')) return;
    e.preventDefault();
    tryJoin(e.target.querySelector('input[name=group]'));
  });

  // Picking a datalist suggestion (no inputType, or insertReplacementText).
  document.addEventListener('input', function(e) {
    if (!e.target.matches('#ag-tags input[name=group]')) return;
    if (!e.inputType || e.inputType === 'insertReplacementText') tryJoin(e.target);
  });

  document.addEventListener('click', function(e) {
    var x = e.target.closest('#ag-tags .ag-chip-x');
    if (x) send(x.dataset.cn, 'leave');
  });
})();
