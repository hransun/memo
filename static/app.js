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

function setListFilter(filter) {
  const favoritesOnly = filter === 'favorites';
  let visibleCount = 0;
  document.querySelectorAll('.sidebar-entry').forEach(entry => {
    entry.hidden = favoritesOnly && entry.dataset.favorite !== '1';
    if (!entry.hidden) visibleCount++;
  });
  document.querySelectorAll('[data-list-filter]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.listFilter === filter));
  });
  document.querySelector('#no-favorites').hidden = !favoritesOnly || visibleCount > 0;
  savePreference('memo-list-filter', favoritesOnly ? 'favorites' : 'all');
}
document.querySelectorAll('[data-list-filter]').forEach(button => {
  button.addEventListener('click', () => setListFilter(button.dataset.listFilter));
});
if (sidebar) setListFilter(readPreference('memo-list-filter', 'all'));
