(() => {
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const button = document.querySelector('#toggle-theme');
    if (button) {
      const dark = theme === 'cinema';
      button.textContent = dark ? '浅色主题' : '黑红主题';
      button.setAttribute('aria-pressed', String(dark));
    }
  }
  let saved = 'light';
  try { saved = localStorage.getItem('memo-theme') || saved; } catch {}
  applyTheme(saved === 'cinema' ? 'cinema' : 'light');
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(document.documentElement.dataset.theme);
    document.querySelector('#toggle-theme')?.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'cinema' ? 'light' : 'cinema';
      applyTheme(next);
      try { localStorage.setItem('memo-theme', next); } catch {}
    });
  });
})();
