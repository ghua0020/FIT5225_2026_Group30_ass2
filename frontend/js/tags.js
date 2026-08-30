/**
 * Pacific BioArchive — 标签管理页逻辑（成员 C）
 * 覆盖 §4.3 查询⑤(批量增删标签 operation=1/0)、查询⑥(删除文件)。
 */
(function () {
  'use strict';

  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const resultEl = $('result');
  const resultStatusEl = $('resultStatus');

  const user = Auth.getCurrentUser();
  const TAGS_STATE_KEY = 'pba_tags_page_state:' + String((user && (user.sub || user.email)) || 'anonymous');
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    sessionStorage.removeItem(TAGS_STATE_KEY);
    Auth.signOut();
  });

  function bulkUrlValues(includeEmpty) {
    const values = Array.from(document.querySelectorAll('.bulk-url-input'))
      .map(input => input.value.trim());
    return includeEmpty ? values : values.filter(Boolean);
  }

  function updateBulkUrlRows() {
    const rows = Array.from(document.querySelectorAll('.bulk-url-row'));
    rows.forEach((row, index) => {
      const input = row.querySelector('.bulk-url-input');
      const removeButton = row.querySelector('.bulk-url-remove');
      const position = index + 1;
      input.setAttribute('aria-label', 'File URL ' + position);
      removeButton.setAttribute('aria-label', 'Remove file URL ' + position);
      removeButton.hidden = rows.length === 1;
    });
  }

  function addBulkUrlRow(value) {
    const row = document.createElement('div');
    row.className = 'bulk-url-row';

    const input = document.createElement('input');
    input.type = 'url';
    input.className = 'bulk-url-input';
    input.placeholder = 'Paste an original or thumbnail URL copied from Gallery';
    input.value = value || '';

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'secondary bulk-url-remove';
    removeButton.textContent = 'Remove';

    row.append(input, removeButton);
    $('mgmtUrlList').appendChild(row);
    updateBulkUrlRows();
    return input;
  }

  function deleteUrlValues(includeEmpty) {
    const values = Array.from(document.querySelectorAll('.delete-url-input'))
      .map(input => input.value.trim());
    return includeEmpty ? values : values.filter(Boolean);
  }

  function updateDeleteUrlRows() {
    const rows = Array.from(document.querySelectorAll('.delete-url-row'));
    rows.forEach((row, index) => {
      const input = row.querySelector('.delete-url-input');
      const removeButton = row.querySelector('.delete-url-remove');
      const position = index + 1;
      input.setAttribute('aria-label', 'File URL ' + position);
      removeButton.setAttribute('aria-label', 'Remove file URL ' + position);
      removeButton.hidden = rows.length === 1;
    });
  }

  function addDeleteUrlRow(value) {
    const row = document.createElement('div');
    row.className = 'delete-url-row';

    const input = document.createElement('input');
    input.type = 'url';
    input.className = 'delete-url-input';
    input.placeholder = 'Paste an original or thumbnail URL copied from Gallery';
    input.value = value || '';

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'secondary delete-url-remove';
    removeButton.textContent = 'Remove';

    row.append(input, removeButton);
    $('delUrlList').appendChild(row);
    updateDeleteUrlRows();
    return input;
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function readTagsState() {
    try {
      return JSON.parse(sessionStorage.getItem(TAGS_STATE_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function saveTagsState() {
    const selectedOperation = document.querySelector('input[name="op"]:checked');
    try {
      sessionStorage.setItem(TAGS_STATE_KEY, JSON.stringify({
        managementUrls: bulkUrlValues(true),
        tags: $('mgmtTags').value,
        operation: selectedOperation ? selectedOperation.value : '1',
        deleteUrls: deleteUrlValues(true),
        resultHtml: resultEl.innerHTML,
        resultStatus: resultStatusEl.textContent
      }));
    } catch (error) {
      // The page remains functional if browser storage is unavailable or full.
    }
  }

  function removeTemporaryActivity() {
    const working = resultEl.querySelector('.management-working');
    if (working) working.remove();
  }

  function removeEmptyActivity() {
    const empty = resultEl.querySelector('.management-empty-state');
    if (empty) empty.remove();
  }

  function showWorking(message) {
    removeTemporaryActivity();
    removeEmptyActivity();
    const working = document.createElement('p');
    working.className = 'msg info management-working';
    working.textContent = message;
    resultEl.appendChild(working);
    resultStatusEl.textContent = 'Working';
    saveTagsState();
  }

  function appendActivity(title, html, status) {
    removeTemporaryActivity();
    removeEmptyActivity();

    const item = document.createElement('article');
    item.className = 'management-activity-item' + (status === 'error' ? ' error' : '');

    const header = document.createElement('div');
    header.className = 'management-activity-header';
    const heading = document.createElement('strong');
    heading.textContent = title;
    const time = document.createElement('time');
    time.dateTime = new Date().toISOString();
    time.textContent = new Date().toLocaleString();
    header.append(heading, time);

    const body = document.createElement('div');
    body.className = 'management-activity-body';
    body.innerHTML = html;
    item.append(header, body);
    resultEl.appendChild(item);
    resultEl.scrollTop = resultEl.scrollHeight;

    resultStatusEl.textContent = status === 'error' ? 'Error' : 'Complete';
    saveTagsState();
  }

  function appendLegacyActivity(html) {
    removeTemporaryActivity();
    removeEmptyActivity();
    const item = document.createElement('article');
    item.className = 'management-activity-item';
    const body = document.createElement('div');
    body.className = 'management-activity-body';
    body.innerHTML = html;
    item.appendChild(body);
    resultEl.appendChild(item);
  }

  function removePreviousActivityLabels() {
    resultEl.querySelectorAll('.management-activity-item').forEach(item => {
      const header = item.querySelector(':scope > .management-activity-header');
      const heading = header && header.querySelector('strong');
      if (heading && heading.textContent.trim() === 'Previous activity') header.remove();
    });
  }

  function showError(err) {
    appendActivity(
      'Request failed',
      '<p class="msg error">' + escapeHtml(err.message || err) + '</p>',
      'error'
    );
  }

  /* ---------- 查询⑤ 批量增删标签 ---------- */
  $('btnBulk').addEventListener('click', function () {
    const urls = bulkUrlValues(false);
    const tags = $('mgmtTags').value.split(',').map(s => s.trim()).filter(Boolean);
    const operation = parseInt(document.querySelector('input[name="op"]:checked').value, 10);

    if (!urls.length) { showError({ message: 'Please enter at least one file URL.' }); return; }
    if (!tags.length) { showError({ message: 'Please enter at least one tag.' }); return; }

    showWorking('Applying tag changes...');
    Api.post('tags/bulk', { urls: urls, tags: tags, operation: operation })
      .then(r => {
        const rows = r.results.map(item =>
          '<li><code>' + escapeHtml(item.file_id) + '</code> → changed: ' +
          (item.changed.length ? escapeHtml(item.changed.join(', ')) : '(none)') +
          ' · tags now: ' + escapeHtml(item.tags.join(', ')) + '</li>'
        ).join('');
        appendActivity(
          operation === 1 ? 'Tags added' : 'Tags removed',
          '<h3>Updated ' + r.count + ' file(s)</h3><ul class="management-result-list">' + rows + '</ul>'
        );
      })
      .catch(showError);
  });

  /* ---------- 查询⑥ 删除文件 ---------- */
  $('btnDelete').addEventListener('click', function () {
    const urls = deleteUrlValues(false);
    if (!urls.length) { showError({ message: 'Please enter at least one file URL.' }); return; }

    if (!confirm('Permanently delete these ' + urls.length + ' file(s) and their thumbnails?')) return;

    showWorking('Deleting files and database records...');
    Api.post('files/delete', { urls: urls })
      .then(r => {
        const head = '<h3>Deleted ' + r.count + ' file(s)</h3>';
        const list = r.deleted.length
          ? '<ul class="management-result-list">' + r.deleted.map(d =>
              '<li><code>' + escapeHtml(d.full_url) + '</code></li>').join('') + '</ul>'
          : '';
        const missing = r.not_found && r.not_found.length
          ? '<p class="subtitle">No record for: ' + r.not_found.map(escapeHtml).join('; ') + '</p>'
          : '';
        appendActivity('Files deleted', head + list + missing);
      })
      .catch(showError);
  });

  $('btnAddMgmtUrl').addEventListener('click', function () {
    const input = addBulkUrlRow('');
    input.focus();
    saveTagsState();
  });

  $('mgmtUrlList').addEventListener('click', function (event) {
    const removeButton = event.target.closest('.bulk-url-remove');
    if (!removeButton) return;
    removeButton.closest('.bulk-url-row').remove();
    if (!document.querySelector('.bulk-url-row')) addBulkUrlRow('');
    updateBulkUrlRows();
    saveTagsState();
  });

  $('mgmtUrlList').addEventListener('input', saveTagsState);

  $('btnAddDeleteUrl').addEventListener('click', function () {
    const input = addDeleteUrlRow('');
    input.focus();
    saveTagsState();
  });

  $('delUrlList').addEventListener('click', function (event) {
    const removeButton = event.target.closest('.delete-url-remove');
    if (!removeButton) return;
    removeButton.closest('.delete-url-row').remove();
    if (!document.querySelector('.delete-url-row')) addDeleteUrlRow('');
    updateDeleteUrlRows();
    saveTagsState();
  });

  $('delUrlList').addEventListener('input', saveTagsState);

  $('mgmtTags').addEventListener('input', saveTagsState);
  document.querySelectorAll('input[name="op"]').forEach(input => {
    input.addEventListener('change', saveTagsState);
  });

  function restoreTagsState() {
    const state = readTagsState();
    const savedManagementUrls = Array.isArray(state.managementUrls)
      ? state.managementUrls
      : (typeof state.managementUrls === 'string' ? state.managementUrls.split('\n') : []);
    $('mgmtUrlList').innerHTML = '';
    (savedManagementUrls.length ? savedManagementUrls : ['']).forEach(addBulkUrlRow);
    if (typeof state.tags === 'string') $('mgmtTags').value = state.tags;
    const savedDeleteUrls = Array.isArray(state.deleteUrls)
      ? state.deleteUrls
      : (typeof state.deleteUrls === 'string' ? state.deleteUrls.split('\n') : []);
    $('delUrlList').innerHTML = '';
    (savedDeleteUrls.length ? savedDeleteUrls : ['']).forEach(addDeleteUrlRow);
    const operation = document.querySelector('input[name="op"][value="' + (state.operation === '0' ? '0' : '1') + '"]');
    if (operation) operation.checked = true;
    if (typeof state.resultHtml === 'string' && state.resultHtml) {
      resultEl.innerHTML = state.resultHtml;
      resultStatusEl.textContent = state.resultStatus || 'Complete';
      removeTemporaryActivity();
      removePreviousActivityLabels();

      if (!resultEl.querySelector('.management-empty-state') &&
          !resultEl.querySelector('.management-activity-item') &&
          resultEl.childNodes.length) {
        const legacyContent = document.createElement('div');
        while (resultEl.firstChild) legacyContent.appendChild(resultEl.firstChild);
        appendLegacyActivity(legacyContent.innerHTML);
      } else if (!resultEl.children.length) {
        resultEl.innerHTML = '<div class="management-empty-state">' +
          '<span aria-hidden="true">✓</span><h3>No changes yet</h3>' +
          '<p>Completed tag edits and deletions will be reported here.</p></div>';
        resultStatusEl.textContent = 'Ready';
      }
    }
    saveTagsState();
  }

  restoreTagsState();
})();
