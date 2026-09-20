document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.matches('.composer') && !form.elements.body.value.trim() && !form.elements.attachment.files.length) {
      event.preventDefault();
      form.elements.body.setCustomValidity('写点内容或添加一个附件。');
      form.elements.body.reportValidity();
      return;
    }
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

const composer = document.querySelector('.composer');
if (composer) {
  const attachment = composer.elements.attachment;
  const body = composer.elements.body;
  const preview = composer.querySelector('.entry-preview');
  const image = preview.querySelector('img');
  const feedback = document.querySelector('#attachment-feedback');
  let previewUrl;
  function updateAttachment() {
    body.setCustomValidity('');
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    image.removeAttribute('src');
    image.hidden = true;
    preview.hidden = true;
    feedback.hidden = true;
    const file = attachment.files[0];
    if (!file) return;
    const extension = file.name.split('.').pop().toLowerCase();
    const isImage = ['jpg', 'jpeg', 'png', 'webp'].includes(extension);
    const limit = (isImage ? 20 : 200) * 1024 * 1024;
    if ((!isImage && !['mp3', 'mp4'].includes(extension)) || !file.size || file.size > limit) {
      feedback.textContent = '请选择有效附件：图片最大 20 MB，MP3 / MP4 最大 200 MB。';
      feedback.hidden = false;
      attachment.value = '';
      return;
    }
    if (isImage) {
      previewUrl = URL.createObjectURL(file);
      image.src = previewUrl;
      image.hidden = false;
    }
    preview.querySelector('.attachment-name').textContent = file.name;
    preview.hidden = false;
  }
  attachment.addEventListener('change', updateAttachment);
  body.addEventListener('input', () => body.setCustomValidity(''));
  composer.querySelector('[data-remove-attachment]').addEventListener('click', () => {
    attachment.value = '';
    updateAttachment();
  });
}
// Keep playback intentional: no autoplay, and only one player active at a time.
document.querySelectorAll('.entry-media audio, .entry-media video').forEach(player => {
  player.addEventListener('play', () => {
    document.querySelectorAll('.entry-media audio, .entry-media video').forEach(other => {
      if (other !== player) other.pause();
    });
  });
  player.addEventListener('error', () => {
    player.closest('.entry-media').querySelector('.media-error').hidden = false;
  });
});
