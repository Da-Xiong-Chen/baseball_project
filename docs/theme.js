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
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const next = value === 'dark' ? 'light' : 'dark';
      const label = next === 'light' ? '淺色' : '深色';
      button.setAttribute('aria-label', `切換為${label}主題`);
      button.setAttribute('title', `切換為${label}主題`);
      button.querySelector('span').textContent = label;
      button.querySelector('use').setAttribute('href', next === 'light' ? '#theme-sun' : '#theme-moon');
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
    document.querySelectorAll('[data-theme-toggle]').forEach(button => button.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      apply(theme);
      try { localStorage.setItem(key, theme); } catch {}
    }));
  });
})();
