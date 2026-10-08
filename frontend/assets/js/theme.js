// Apply the saved theme before the page paints. A file of its own, not inline: the page allows no inline script.
try { var t = localStorage.getItem('scene.theme'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch (e) {}
