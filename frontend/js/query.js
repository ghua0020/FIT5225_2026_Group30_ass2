/**
 * Pacific BioArchive — 查询页逻辑（成员 C）
 * 覆盖 §4.3 查询①(标签+计数)、②(物种)、③(缩略图反查原图)、④(按文件查询)。
 * 结果：图片缩略图网格（点击经 /search/thumbnail 解析为原图后新窗口打开）+ 视频链接。
 */
(function () {
  'use strict';

  const MAX_QUERY_FILE_BYTES = 4 * 1024 * 1024;

  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const resultsEl = $('results');
  const resultCountEl = $('resultCount');
  const user = Auth.getCurrentUser();
  const SEARCH_STATE_KEY = 'pba_search_page_state:' + String((user && (user.sub || user.email)) || 'anonymous');
  let restoringState = false;
  let lastResult = null;

  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }

  function readSearchState() {
    try {
      return JSON.parse(sessionStorage.getItem(SEARCH_STATE_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function saveSearchState() {
    if (restoringState) return;
    const activeTab = document.querySelector('[data-query-tab].active');
    const advanced = document.querySelector('.search-advanced');
    try {
      sessionStorage.setItem(SEARCH_STATE_KEY, JSON.stringify({
        species: $('qSpecies').value,
        tagCounts: $('qTags').value,
        thumbnailUrl: $('qThumb').value,
        activeTab: activeTab ? activeTab.dataset.queryTab : 'tags',
        advancedOpen: Boolean(advanced && advanced.open),
        result: lastResult
      }));
    } catch (error) {
      // The page remains functional if browser storage is unavailable or full.
    }
  }

  /* ---------- 查询方式切换 ---------- */
  const tabs = Array.from(document.querySelectorAll('[data-query-tab]'));
  const panels = Array.from(document.querySelectorAll('[data-query-panel]'));

  function activateTab(name) {
    tabs.forEach(tab => {
      const active = tab.dataset.queryTab === name;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach(panel => {
      const active = panel.dataset.queryPanel === name;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    saveSearchState();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.queryTab));
    tab.addEventListener('keydown', event => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const target = tabs[(index + direction + tabs.length) % tabs.length];
      activateTab(target.dataset.queryTab);
      target.focus();
    });
  });

  document.querySelectorAll('[data-species]').forEach(button => {
    button.addEventListener('click', () => {
      $('qSpecies').value = button.dataset.species;
      $('btnBySpecies').click();
    });
  });

  // 导航栏登出
  $('btnLogout').addEventListener('click', function () {
    sessionStorage.removeItem(SEARCH_STATE_KEY);
    Auth.logout();
    window.location.href = './index.html';
  });

  /* ---------- 结果渲染 ---------- */
  function renderResults(data) {
    const thumbnails = data.thumbnails || [];
    const thumbnailSources = data.thumbnail_sources || thumbnails;
    const fullImages = data.full_images || [];
    const videos = data.videos || [];
    const total = (data.count !== undefined) ? data.count : thumbnails.length + videos.length;
    const detected = Array.isArray(data.detected) ? data.detected : [];

    resultCountEl.textContent = total + (total === 1 ? ' match' : ' matches');
    let html = '';
    if (detected.length) {
      html += '<div class="search-detected"><strong>Detected</strong>' +
        detected.map(tag => '<span class="tag-chip">' + escapeHtml(tag) + '</span>').join('') +
        '</div>';
    }
    if (total === 0) {
      html += '<div class="search-empty-state"><span aria-hidden="true">⌕</span>' +
        '<h3>No matching media</h3><p>Try another species, reduce the required tag counts, or use a different reference image.</p></div>';
    }
    if (thumbnails.length) {
      html += '<div class="search-result-section"><h3>Images</h3><div class="search-result-grid">';
      thumbnails.forEach((t, index) => {
        if (!t) return;
        const source = thumbnailSources[index] || t;
        const fullImage = fullImages[index] || '';
        html += '<a class="search-result-card" href="#" data-thumb="' + encodeURIComponent(source) +
          '" data-full="' + encodeURIComponent(fullImage) + '" title="' +
          escapeHtml(t) + '"><img src="' + escapeHtml(t) +
          '" alt="Wildlife search result"><span class="label">Open original <span aria-hidden="true">↗</span></span></a>';
      });
      html += '</div></div>';
    }
    if (videos.length) {
      html += '<div class="search-result-section"><h3>Videos</h3><div class="search-video-list">';
      videos.forEach((video, index) => {
        if (video) html += '<a class="search-video-link" href="' + escapeHtml(video) +
          '" target="_blank" rel="noopener"><span aria-hidden="true">▶</span>Open video ' +
          (index + 1) + '</a>';
      });
      html += '</div></div>';
    }
    resultsEl.innerHTML = html;

    resultsEl.querySelectorAll('.search-result-card img').forEach(image => {
      image.addEventListener('error', function () {
        const fallback = document.createElement('div');
        fallback.className = 'search-thumbnail-fallback';
        fallback.textContent = 'Thumbnail unavailable';
        this.replaceWith(fallback);
      }, { once: true });
    });

    // 点击缩略图 → 通过查询③反查原图 → 新窗口打开（演示缩略图 URL→原图）
    resultsEl.querySelectorAll('a[data-thumb]').forEach(a => {
      a.addEventListener('click', async function (e) {
        e.preventDefault();
        const thumbUrl = decodeURIComponent(this.getAttribute('data-thumb'));
        const fullUrl = decodeURIComponent(this.getAttribute('data-full') || '');
        this.querySelector('.label').textContent = 'loading...';
        try {
          if (fullUrl) {
            window.open(fullUrl, '_blank', 'noopener');
          } else {
            const r = await Api.get('search/thumbnail?url=' + encodeURIComponent(thumbUrl));
            if (r && r.full_url) window.open(r.full_url, '_blank', 'noopener');
            else alert('Full image not found.');
          }
        } catch (err) {
          alert(err.message);
        } finally {
          const label = this.querySelector('.label');
          if (label) label.innerHTML = 'Open original <span aria-hidden="true">↗</span>';
        }
      });
    });
    lastResult = { kind: 'results', payload: data };
    saveSearchState();
  }

  function renderOriginalResult(data) {
    const url = data && data.full_url ? String(data.full_url) : '';
    if (!url) {
      renderResults({ count: 0, thumbnails: [], videos: [] });
      return;
    }
    resultCountEl.textContent = '1 match';
    resultsEl.innerHTML = '<div class="search-result-section"><h3>Original image</h3>' +
      '<a class="search-original-link" href="' + escapeHtml(url) +
      '" target="_blank" rel="noopener"><span aria-hidden="true">↗</span>Open the full-size image</a></div>';
    lastResult = { kind: 'original', payload: data };
    saveSearchState();
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function showError(err) {
    const message = String(err.message || err);
    resultCountEl.textContent = 'Error';
    resultsEl.innerHTML = '<div class="search-alert error"><strong>Search failed.</strong><br>' +
      escapeHtml(message) + '</div>';
    lastResult = { kind: 'error', payload: message };
    saveSearchState();
  }

  async function run(fn, button, renderer = renderResults, loadingText = 'Searching archive…') {
    saveSearchState();
    resultCountEl.textContent = 'Searching';
    resultsEl.innerHTML = '<div class="search-loading"><span class="search-spinner" aria-hidden="true"></span>' +
      '<span>' + escapeHtml(loadingText) + '</span></div>';
    if (button) button.disabled = true;
    try {
      renderer(await fn());
    } catch (error) {
      showError(error);
    } finally {
      if (button) button.disabled = false;
    }
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
    run(() => Api.post('search/by-tags', criteria), $('btnByTags'));
  });

  /* ---------- 查询② 物种 ---------- */
  $('btnBySpecies').addEventListener('click', function () {
    const species = $('qSpecies').value.trim();
    if (!species) { showError({ message: 'Please enter a species name.' }); return; }
    run(
      () => Api.get('search/by-species?species=' + encodeURIComponent(species)),
      $('btnBySpecies')
    );
  });

  /* ---------- 查询③ 缩略图→原图 ---------- */
  $('btnThumb').addEventListener('click', function () {
    const url = $('qThumb').value.trim();
    if (!url) { showError({ message: 'Please paste a thumbnail URL.' }); return; }
    run(
      () => Api.get('search/thumbnail?url=' + encodeURIComponent(url)),
      $('btnThumb'),
      renderOriginalResult,
      'Resolving original image…'
    );
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

  $('qFile').addEventListener('change', function () {
    const file = this.files && this.files[0];
    $('qFileMeta').textContent = file
      ? file.name + ' · ' + formatFileSize(file.size)
      : 'No image selected';
  });

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KiB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MiB';
  }

  $('btnByFile').addEventListener('click', function () {
    const file = $('qFile').files && $('qFile').files[0];
    if (!file) { showError({ message: 'Please choose an image file first.' }); return; }
    if (!file.type || !file.type.startsWith('image/')) {
      showError({ message: 'Query files must be images.' });
      return;
    }
    if (file.size > MAX_QUERY_FILE_BYTES) {
      showError({ message: 'Query images must be 4 MiB or smaller.' });
      return;
    }
    fileToBase64(file)
      .then(b64 => run(
        () => Api.post('search/by-file', { base64: b64 }),
        $('btnByFile'),
        renderResults,
        'Detecting species and finding matches…'
      ))
      .catch(err => showError(err.message || err));
  });

  $('qSpecies').addEventListener('keydown', event => {
    if (event.key === 'Enter') $('btnBySpecies').click();
  });
  $('qThumb').addEventListener('keydown', event => {
    if (event.key === 'Enter') $('btnThumb').click();
  });
  $('qTags').addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') $('btnByTags').click();
  });

  ['qSpecies', 'qTags', 'qThumb'].forEach(id => {
    $(id).addEventListener('input', saveSearchState);
  });
  document.querySelector('.search-advanced').addEventListener('toggle', saveSearchState);

  function restoreSearchState() {
    const state = readSearchState();
    restoringState = true;
    if (typeof state.species === 'string') $('qSpecies').value = state.species;
    if (typeof state.tagCounts === 'string') $('qTags').value = state.tagCounts;
    if (typeof state.thumbnailUrl === 'string') $('qThumb').value = state.thumbnailUrl;
    document.querySelector('.search-advanced').open = Boolean(state.advancedOpen);
    activateTab(state.activeTab || 'tags');
    restoringState = false;

    if (state.result && state.result.kind === 'results') {
      renderResults(state.result.payload || {});
    } else if (state.result && state.result.kind === 'original') {
      renderOriginalResult(state.result.payload || {});
    } else if (state.result && state.result.kind === 'error') {
      showError({ message: state.result.payload || 'Search failed.' });
    } else {
      saveSearchState();
    }
  }

  restoreSearchState();
})();
