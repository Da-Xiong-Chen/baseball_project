/* Apply before CSS is painted; storage failures must not block the application. */
(() => {
  const key = 'matchup-theme';
  let theme = 'dark';
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') theme = saved; } catch {}
  const apply = value => {
    document.documentElement.dataset.theme = value;
    document.documentElement.style.colorScheme = value;
    document.querySelectorAll('[data-set-theme]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.setTheme === value));
      button.classList.toggle('on', button.dataset.setTheme === value);
    });
  };
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    apply(theme);
    document.querySelectorAll('[data-set-theme]').forEach(button => button.addEventListener('click', () => {
      theme = button.dataset.setTheme;
      apply(theme);
      try { localStorage.setItem(key, theme); } catch {}
    }));
  });
})();
