function showLoadingOverlay() {
  var overlay = document.getElementById('loading-overlay');
  var bar = document.getElementById('loading-bar');
  overlay.style.display = 'flex';
  bar.getBoundingClientRect();
  bar.style.transition = 'width 20s linear';
  bar.style.width = '100%';
}
