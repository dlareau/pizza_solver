function showLoadingOverlay() {
  var overlay = document.getElementById('loading-overlay');
  var bar = document.getElementById('loading-bar');
  bar.style.transition = 'none';
  bar.style.width = '0%';
  overlay.style.display = 'flex';
  bar.getBoundingClientRect();
  bar.style.transition = 'width 20s linear';
  bar.style.width = '100%';
}

window.addEventListener('pageshow', function (e) {
  if (e.persisted) {
    var overlay = document.getElementById('loading-overlay');
    if (overlay) {
      overlay.style.display = 'none';
    }
  }
});
