// Minimal JS for VNT-RPTR WebUI
// Most interactivity is handled by HTMX

document.addEventListener('htmx:responseError', function(evt) {
  console.error('HTMX error:', evt.detail);
});

// Auto-scroll terminal outputs to bottom
const observer = new MutationObserver(function(mutations) {
  mutations.forEach(function(mutation) {
    const target = mutation.target;
    if (target.classList && target.classList.contains('terminal')) {
      target.scrollTop = target.scrollHeight;
    }
  });
});

document.querySelectorAll('.terminal').forEach(function(el) {
  observer.observe(el, { childList: true, subtree: true, characterData: true });
});

// Re-observe terminals after HTMX swaps
document.addEventListener('htmx:afterSwap', function(evt) {
  document.querySelectorAll('.terminal').forEach(function(el) {
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    el.scrollTop = el.scrollHeight;
  });
});
