(function () {
  var csrf = document.querySelector('meta[name="csrf-token"]').content;
  var input = document.getElementById('codeInput'), result = document.getElementById('result');
  var video = document.getElementById('video'), camBtn = document.getElementById('camBtn'), camMsg = document.getElementById('camMsg');
  var stream = null, scanning = false, current = null;

  function post(url, body) {
    return fetch(url, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { j._status = r.status; return j; }); });
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  function toast(msg, ok) {
    var c = document.querySelector('.toast-container');
    var el = document.createElement('div'); el.className = 'toast align-items-center text-bg-' + (ok ? 'success' : 'danger') + ' border-0';
    el.innerHTML = '<div class="d-flex"><div class="toast-body">' + esc(msg) + '</div><button class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    c.appendChild(el); new bootstrap.Toast(el, {delay: 4500}).show();
  }
  function render(d) {
    current = d;
    var h = '<div class="card"><div class="card-body"><div class="d-flex gap-3">';
    if (d.photo) h += '<img src="' + esc(d.photo) + '" class="rounded" style="width:90px;height:90px;object-fit:cover" alt="Visitor photo">';
    h += '<div><h5 class="mb-0">' + esc(d.visitor) + '</h5><div class="text-muted small">' + esc(d.company) + ' · ' + esc(d.category) + '</div>' +
      '<div class="small mt-1"><b>' + esc(d.pass_no) + '</b> · ' + esc(d.request_no) + '</div></div></div><hr>' +
      '<div class="row small g-2"><div class="col-6"><span class="text-muted">Host</span><br>' + esc(d.host) + ' (' + esc(d.department) + ')</div>' +
      '<div class="col-6"><span class="text-muted">Visit</span><br>' + esc(d.visit_date) + ' ' + esc(d.window) + '</div>' +
      '<div class="col-6"><span class="text-muted">Companions</span><br>' + esc(d.companions) + '</div>' +
      '<div class="col-6"><span class="text-muted">Vehicle</span><br>' + esc(d.vehicle) + '</div></div>';
    d.warnings.forEach(function (w) {
      h += '<div class="alert alert-warning mt-3 mb-0 py-2 small"><b>' + esc(w.level.toUpperCase()) + ' alert:</b> ' + esc(w.note) +
        (w.reason ? '<br>Reason: ' + esc(w.reason) : '') + '</div>';
    });
    if (d.warnings.length && d.action === 'checkin')
      h += '<textarea id="ackNote" class="form-control mt-2" rows="2" placeholder="Identity verified / override note (required)"></textarea>';
    h += '<div class="mt-3">';
    if (d.action === 'checkin') h += '<div class="alert alert-success py-2">Valid pass - ready for entry</div><button class="btn btn-primary" id="doIn"><i class="bi bi-box-arrow-in-right"></i> Check in</button>';
    else if (d.action === 'checkout') h += '<div class="alert alert-info py-2">Visitor is inside</div><button class="btn btn-primary" id="doOut"><i class="bi bi-box-arrow-right"></i> Check out</button>';
    else h += '<div class="alert alert-danger py-2 mb-0"><b>Access denied:</b> ' + esc(d.reason || 'Invalid') + '</div>';
    h += '</div></div></div>';
    result.innerHTML = h;
    var bi = document.getElementById('doIn'), bo = document.getElementById('doOut');
    if (bi) bi.onclick = function () {
      var n = document.getElementById('ackNote');
      act('/gate/checkin', {pass_no: d.pass_no, ack_note: n ? n.value : ''});
    };
    if (bo) bo.onclick = function () { act('/gate/checkout', {pass_no: d.pass_no}); };
  }
  function act(url, body) {
    post(url, body).then(function (r) {
      toast(r.message, r.ok);
      if (r.ok) { result.innerHTML = ''; input.value = ''; input.focus(); }
      else if (r.code !== 'ack_required') lookup(body.pass_no);
    });
  }
  function lookup(code) {
    code = (code || input.value).trim(); if (!code) return;
    post('/gate/lookup', {code: code}).then(function (d) {
      if (!d.ok) { result.innerHTML = '<div class="alert alert-danger"><b>' + esc(d.message || 'Not found') + '</b></div>'; return; }
      render(d);
    }).catch(function () { toast('Lookup failed', false); });
  }
  document.getElementById('lookupForm').addEventListener('submit', function (e) { e.preventDefault(); lookup(); });

  // ---- camera scanning (BarcodeDetector, fallback jsQR) ----
  var detector = ('BarcodeDetector' in window) ? new BarcodeDetector({formats: ['qr_code']}) : null;
  var canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
  function stop() { scanning = false; if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; video.parentElement.classList.add('d-none'); camBtn.textContent = 'Start camera scan'; }
  function loop() {
    if (!scanning) return;
    var p;
    if (detector) p = detector.detect(video).then(function (c) { return c.length ? c[0].rawValue : null; });
    else if (window.jsQR && video.videoWidth) {
      canvas.width = video.videoWidth; canvas.height = video.videoHeight; ctx.drawImage(video, 0, 0);
      var img = ctx.getImageData(0, 0, canvas.width, canvas.height), c = jsQR(img.data, img.width, img.height);
      p = Promise.resolve(c ? c.data : null);
    } else p = Promise.resolve(null);
    p.then(function (val) { if (val) { input.value = val; stop(); lookup(val); } else setTimeout(loop, 250); }).catch(function () { setTimeout(loop, 400); });
  }
  camBtn.addEventListener('click', function () {
    if (scanning) return stop();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { camMsg.textContent = 'Camera is not supported (HTTPS required). Use manual entry.'; return; }
    navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}}).then(function (s) {
      stream = s; video.srcObject = s; video.play(); video.parentElement.classList.remove('d-none');
      scanning = true; camBtn.textContent = 'Stop camera'; camMsg.textContent = ''; loop();
    }).catch(function () { camMsg.textContent = 'Camera permission denied or unavailable. Use manual entry.'; });
  });
  input.focus();
})();
