document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault(); return;
    }
    if (form.method.toLowerCase() !== 'post') return;
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.dataset.originalText = button.textContent; button.disabled = true; button.textContent = '正在保存…'; }
  });
});
const currentUrl = new URL(window.location.href);
if (currentUrl.searchParams.get('saved') === '1') {
  currentUrl.searchParams.delete('saved');
  window.history.replaceState(null, '', currentUrl);
  const notice = document.querySelector('#notice');
  notice.textContent = '已保存到本机';
  notice.classList.add('show');
  setTimeout(() => notice.classList.remove('show'), 3000);
}
window.addEventListener('pageshow', () => {
  document.querySelectorAll('button:disabled').forEach(button => {
    button.disabled = false;
    if (button.dataset.originalText) button.textContent = button.dataset.originalText;
  });
});

// These are device-local display preferences; favorites themselves live in SQLite.
function readPreference(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}
function savePreference(key, value) {
  try { localStorage.setItem(key, value); } catch { /* Still work without storage. */ }
}
const sidebar = document.querySelector('#memo-sidebar');
const sidebarToggle = document.querySelector('#toggle-sidebar');
function setSidebarHidden(hidden) {
  sidebar.hidden = hidden;
  document.querySelector('.workspace').classList.toggle('sidebar-hidden', hidden);
  sidebarToggle.setAttribute('aria-expanded', String(!hidden));
  sidebarToggle.textContent = hidden ? '展开列表' : '收起列表';
  savePreference('memo-sidebar-hidden', String(hidden));
}
if (sidebar && sidebarToggle) {
  sidebarToggle.addEventListener('click', () => setSidebarHidden(!sidebar.hidden));
  setSidebarHidden(readPreference('memo-sidebar-hidden', 'false') === 'true');
}


document.querySelectorAll('[data-open-dialog]').forEach(button => {
  button.addEventListener('click', () => {
    document.getElementById(button.dataset.openDialog).showModal();
  });
});
document.querySelectorAll('[data-close-dialog]').forEach(button => {
  button.addEventListener('click', () => button.closest('dialog').close());
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelectorAll('.more-menu[open]').forEach(menu => menu.open = false);
});
document.addEventListener('click', event => {
  document.querySelectorAll('.more-menu[open]').forEach(menu => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
