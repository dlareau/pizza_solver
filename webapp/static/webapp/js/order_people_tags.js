function updateCount() {
  var countEl = document.getElementById('people-count');
  var n = document.querySelectorAll('#people-tags input[type="checkbox"]:checked').length;
  countEl.textContent = n + ' ' + (n === 1 ? 'person' : 'people') + ' selected';
}

function initPeopleTags() {
  document.querySelectorAll('#people-tags label').forEach(function (lbl) {
    var cb = lbl.querySelector('input[type="checkbox"]');
    var tag = lbl.querySelector('.person-tag');
    if (!cb || !tag) return;
    if (cb.checked) {
      tag.classList.replace('is-light', 'is-link');
    } else {
      tag.classList.replace('is-link', 'is-light');
    }
    lbl.addEventListener('click', function (e) {
      e.preventDefault();
      cb.checked = !cb.checked;
      if (cb.checked) {
        tag.classList.replace('is-light', 'is-link');
      } else {
        tag.classList.replace('is-link', 'is-light');
      }
      updateCount();
    });
  });
  updateCount();
}

document.addEventListener('DOMContentLoaded', function () {
  initPeopleTags();
});
