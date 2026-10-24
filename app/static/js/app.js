(function () {
  document.querySelectorAll('.toast').forEach(function (el) { new bootstrap.Toast(el, {delay: 5000}).show(); });
  var toggle = document.getElementById('sidebarToggle');
  if (toggle) toggle.addEventListener('click', function () { document.getElementById('sidebar').classList.toggle('open'); });
  // confirmation modal for forms/buttons carrying data-confirm
  var modalEl = document.getElementById('confirmModal'), pending = null;
  if (modalEl) {
    var modal = new bootstrap.Modal(modalEl);
    document.addEventListener('submit', function (e) {
      var f = e.target;
      if (f.dataset && f.dataset.confirm && !f.dataset.ok) {
        e.preventDefault(); pending = f;
        document.getElementById('confirmText').textContent = f.dataset.confirm; modal.show();
      }
    });
    document.getElementById('confirmYes').addEventListener('click', function () {
      if (pending) { pending.dataset.ok = '1'; modal.hide(); pending.requestSubmit ? pending.requestSubmit() : pending.submit(); }
    });
  }
  // live-refresh notification count
  var badge = document.getElementById('notifBadge');
  if (badge) setInterval(function () {
    fetch('/api/notifications/count', {credentials: 'same-origin'}).then(function (r) { return r.json(); }).then(function (d) {
      badge.textContent = d.count; badge.classList.toggle('d-none', !d.count);
    }).catch(function () {});
  }, 60000);
  // client-side table filter
  document.querySelectorAll('[data-table-filter]').forEach(function (inp) {
    inp.addEventListener('input', function () {
      var t = document.querySelector(inp.dataset.tableFilter), q = inp.value.toLowerCase();
      t.querySelectorAll('tbody tr').forEach(function (tr) { tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    });
  });
})();
