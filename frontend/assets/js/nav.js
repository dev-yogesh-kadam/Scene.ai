// Page addresses: /library, /canvas and so on, not #/library. `go` moves to one without reloading the page and tells
// whoever is listening (the router) with a "scene:route" event; the back and forward buttons do the same.

export const here = () => location.pathname.replace(/\/+$/, '') || '/';

export function go(path, { replace = false } = {}) {
  if (path === location.pathname + location.search) return;
  history[replace ? 'replaceState' : 'pushState'](null, '', path);
  window.dispatchEvent(new Event('scene:route'));
}

// Links inside the studio are plain <a href="/library">: a click on one (not with a modifier key, not to a file or the
// API) is a move within the page, not a new load.
export function linkClicks() {
  window.addEventListener('popstate', () => window.dispatchEvent(new Event('scene:route')));
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const link = e.target.closest && e.target.closest('a[href]');
    if (!link || link.target || link.hasAttribute('download')) return;
    const href = link.getAttribute('href');
    if (!href.startsWith('/') || href.startsWith('//') || /^\/(api|assets|v)\//.test(href) || /\.[a-z0-9]+$/i.test(href.split('?')[0])) return;
    e.preventDefault();
    go(href);
  });
}

// An address from before (/#/library) is moved to the new one (/library).
export function oldAddress() {
  if (location.hash.startsWith('#/')) history.replaceState(null, '', location.hash.slice(1));
}
