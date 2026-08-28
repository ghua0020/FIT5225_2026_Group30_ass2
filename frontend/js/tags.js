/**
 * Pacific BioArchive — 标签管理页逻辑（成员 C）
 * 覆盖 §4.3 查询⑤(批量增删标签 operation=1/0)、查询⑥(删除文件)。
 */
(function () {
  'use strict';

  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const resultEl = $('result');

  const user = Auth.getCurrentUser();
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    Auth.logout();
    window.location.href = './index.html';
  });

  function lines(id) {
    return $(id).value
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean);
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function showResult(html) {
    resultEl.innerHTML = html;
  }

  function showError(err) {
    resultEl.innerHTML = '<p class="msg error" style="margin-top:12px;">' +
      escapeHtml(err.message || err) + '</p>';
  }

  /* ---------- 查询⑤ 批量增删标签 ---------- */
  $('btnBulk').addEventListener('click', function () {
    const urls = lines('mgmtUrls');
    const tags = $('mgmtTags').value.split(',').map(s => s.trim()).filter(Boolean);
    const operation = parseInt(document.querySelector('input[name="op"]:checked').value, 10);

    if (!urls.length) { showError({ message: 'Please enter at least one file URL.' }); return; }
    if (!tags.length) { showError({ message: 'Please enter at least one tag.' }); return; }

    showResult('<p class="msg info">Applying...</p>');
    Api.post('tags/bulk', { urls: urls, tags: tags, operation: operation })
      .then(r => {
        const rows = r.results.map(item =>
          '<li><code>' + escapeHtml(item.file_id) + '</code> → changed: ' +
          (item.changed.length ? escapeHtml(item.changed.join(', ')) : '(none)') +
          ' · tags now: ' + escapeHtml(item.tags.join(', ')) + '</li>'
        ).join('');
        showResult('<h3>Updated ' + r.count + ' file(s)</h3><ul style="margin-left:20px;">' + rows + '</ul>');
      })
      .catch(showError);
  });

  /* ---------- 查询⑥ 删除文件 ---------- */
  $('btnDelete').addEventListener('click', function () {
    const urls = lines('delUrls');
    if (!urls.length) { showError({ message: 'Please enter at least one file URL.' }); return; }

    if (!confirm('Permanently delete these ' + urls.length + ' file(s) and their thumbnails?')) return;

    showResult('<p class="msg info">Deleting...</p>');
    Api.post('files/delete', { urls: urls })
      .then(r => {
        const head = '<h3>Deleted ' + r.count + ' file(s)</h3>';
        const list = r.deleted.length
          ? '<ul style="margin-left:20px;">' + r.deleted.map(d =>
              '<li><code>' + escapeHtml(d.full_url) + '</code></li>').join('') + '</ul>'
          : '';
        const missing = r.not_found && r.not_found.length
          ? '<p class="subtitle">No record for: ' + r.not_found.map(escapeHtml).join('; ') + '</p>'
          : '';
        showResult(head + list + missing);
      })
      .catch(showError);
  });
})();