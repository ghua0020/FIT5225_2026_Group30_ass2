/**
 * Pacific BioArchive — 查询页逻辑（成员 C）
 * 覆盖 §4.3 查询①(标签+计数)、②(物种)、③(缩略图反查原图)、④(按文件查询)。
 * 结果：图片缩略图网格（点击经 /search/thumbnail 解析为原图后新窗口打开）+ 视频链接。
 */
(function () {
  'use strict';

  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const resultsEl = $('results');

  // 导航栏用户信息 + 登出
  const user = Auth.getCurrentUser();
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    Auth.logout();
    window.location.href = './index.html';
  });

  /* ---------- 结果渲染 ---------- */
  function renderResults(data) {
    const thumbnails = data.thumbnails || [];
    const videos = data.videos || [];
    const total = (data.count !== undefined) ? data.count : thumbnails.length + videos.length;

    let html = '<h3>Results (' + total + ')</h3>';
    if (total === 0) {
      html += '<p class="subtitle">No matching files.</p>';
    }
    if (thumbnails.length) {
      html += '<h4>Images</h4><div class="grid">';
      thumbnails.forEach(t => {
        if (!t) return;
        html += '<a href="#" data-thumb="' + encodeURIComponent(t) + '" title="' +
          escapeHtml(t) + '"><img src="' + escapeHtml(t) +
          '" alt="thumbnail"><span class="label">view full image</span></a>';
      });
      html += '</div>';
    }
    if (videos.length) {
      html += '<h4>Videos</h4><div class="videos">';
      videos.forEach(v => {
        if (v) html += '<a href="' + escapeHtml(v) + '" target="_blank" rel="noopener">' + escapeHtml(v) + '</a>';
      });
      html += '</div>';
    }
    resultsEl.innerHTML = html;

    // 点击缩略图 → 通过查询③反查原图 → 新窗口打开（演示缩略图 URL→原图）
    resultsEl.querySelectorAll('a[data-thumb]').forEach(a => {
      a.addEventListener('click', async function (e) {
        e.preventDefault();
        const thumbUrl = decodeURIComponent(this.getAttribute('data-thumb'));
        this.querySelector('.label').textContent = 'loading...';
        try {
          const r = await Api.get('search/thumbnail?url=' + encodeURIComponent(thumbUrl));
          if (r && r.full_url) window.open(r.full_url, '_blank');
          else alert('Full image not found.');
        } catch (err) {
          alert(err.message);
        } finally {
          const label = this.querySelector('.label');
          if (label) label.textContent = 'view full image';
        }
      });
    });
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function showError(err) {
    resultsEl.innerHTML = '<p class="msg error" style="margin-top:12px;">' + escapeHtml(err.message || err) + '</p>';
  }

  function run(fn) {
    resultsEl.innerHTML = '<p class="subtitle">Searching...</p>';
    fn().then(renderResults).catch(showError);
  }

  /* ---------- 查询① 标签+计数 ---------- */
  $('btnByTags').addEventListener('click', function () {
    let criteria;
    try {
      criteria = JSON.parse($('qTags').value);
    } catch (e) {
      showError({ message: 'Invalid JSON in tag counts field.' });
      return;
    }
    if (typeof criteria !== 'object' || criteria === null) {
      showError({ message: 'Tag counts must be an object like {"koala": 2}.' });
      return;
    }
    run(() => Api.post('search/by-tags', criteria));
  });

  /* ---------- 查询② 物种 ---------- */
  $('btnBySpecies').addEventListener('click', function () {
    const species = $('qSpecies').value.trim();
    if (!species) { showError({ message: 'Please enter a species name.' }); return; }
    run(() => Api.get('search/by-species?species=' + encodeURIComponent(species)));
  });

  /* ---------- 查询③ 缩略图→原图 ---------- */
  $('btnThumb').addEventListener('click', function () {
    const url = $('qThumb').value.trim();
    if (!url) { showError({ message: 'Please paste a thumbnail URL.' }); return; }
    resultsEl.innerHTML = '<p class="subtitle">Resolving...</p>';
    Api.get('search/thumbnail?url=' + encodeURIComponent(url))
      .then(r => {
        resultsEl.innerHTML =
          '<h3>Result</h3><p class="videos">Full image: <a href="' + escapeHtml(r.full_url) +
          '" target="_blank" rel="noopener">' + escapeHtml(r.full_url) + '</a></p>';
      })
      .catch(showError);
  });

  /* ---------- 查询④ 按文件 ---------- */
  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  $('btnByFile').addEventListener('click', function () {
    const file = $('qFile').files && $('qFile').files[0];
    if (!file) { showError({ message: 'Please choose an image file first.' }); return; }
    fileToBase64(file)
      .then(b64 => run(() => Api.post('search/by-file', { base64: b64 })))
      .catch(err => showError(err.message || err));
  });
})();