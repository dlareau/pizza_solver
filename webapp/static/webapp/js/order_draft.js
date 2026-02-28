document.addEventListener('htmx:beforeSwap', function (e) {
  if (e.detail.target.id === 'people-tags') {
    var state = {};
    e.detail.target.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
      state[cb.value] = cb.checked;
    });
    window._savedPeopleState = state;
  }
});

document.addEventListener('htmx:afterSwap', function (e) {
  if (e.detail.target.id === 'people-tags') {
    var saved = window._savedPeopleState || {};
    e.detail.target.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
      if (cb.value in saved) {
        cb.checked = saved[cb.value];
      }
      // new people not in saved → keep server default (checked, since they're in order.people)
    });
    initPeopleTags();
  }
});

document.getElementById('order-form').addEventListener('submit', function () {
  showLoadingOverlay();
});

(function () {
  var qrDiv   = document.getElementById('qr-canvas');
  var section = document.getElementById('qr-section');
  var linkEl  = document.getElementById('invite-link');
  var url     = linkEl && linkEl.value;
  if (!qrDiv || !url) return;
  section.style.display = 'block';
  new QRCode(qrDiv, { text: url, width: 128, height: 128, correctLevel: QRCode.CorrectLevel.L });
}());
