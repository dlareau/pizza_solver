document.getElementById('order-form').addEventListener('submit', function (e) {
  document.querySelectorAll('[data-client-error]').forEach(function (el) { el.remove(); });

  function showError(anchorEl, message) {
    var p = document.createElement('p');
    p.className = 'help is-danger';
    p.setAttribute('data-client-error', '');
    p.textContent = message;
    anchorEl.insertAdjacentElement('afterend', p);
    return p;
  }

  var firstError = null;
  var restaurantSelect = document.querySelector('select[name="restaurant"]');
  if (!restaurantSelect.value) {
    firstError = showError(restaurantSelect.closest('.control'), 'Please select a restaurant.');
  }

  if (firstError) {
    e.preventDefault();
    firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  if (!e.submitter || e.submitter.name !== 'invite_guests') {
    showLoadingOverlay();
  }
});
