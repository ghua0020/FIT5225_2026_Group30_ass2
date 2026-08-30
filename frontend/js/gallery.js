/**
 * Member B Gallery UI.
 *
 * Protected query API contract (GET APP_CONFIG.endpoints.gallery):
 *   { items: [{ file_id, checksum, file_type, tags, tag_counts,
 *               full_url, thumb_url, full_url_source, thumb_url_source,
 *               created_at }], next_cursor: string|null }
 *
 * The API may use `files`, `results`, `data`, or a bare array instead of
 * `items`. Returned object URLs must be temporary browser-readable URLs; the
 * browser never receives DynamoDB credentials or direct database access.
 */
(function () {
  'use strict';

  if (!Auth.requireAuth()) return;

  const PENDING_UPLOADS_KEY = 'pba_pending_uploads';
  const PENDING_RETENTION_MS = 24 * 60 * 60 * 1000;
  const SLOW_PROCESSING_MS = 15 * 60 * 1000;
  const AUTO_REFRESH_MS = 15000;

  const $ = id => document.getElementById(id);
  const grid = $('galleryGrid');
  const message = $('galleryMessage');
  const empty = $('emptyGallery');
  const refreshButton = $('btnRefresh');
  let processedItems = [];
  let pendingItems = [];
  let refreshTimer = null;

  const user = Auth.getCurrentUser();
  const GALLERY_STATE_KEY = 'pba_gallery_page_state:' + String((user && (user.sub || user.email)) || 'anonymous');
  if (user) {
    $('userInfo').textContent = displayName(user);
  }
  const galleryState = readGalleryState();
  if (typeof galleryState.search === 'string') $('gallerySearch').value = galleryState.search;
  if (['all', 'image', 'video'].includes(galleryState.mediaType)) {
    $('mediaTypeFilter').value = galleryState.mediaType;
  }

  $('btnLogout').addEventListener('click', function () {
    sessionStorage.removeItem(GALLERY_STATE_KEY);
    Auth.signOut();
  });
  refreshButton.addEventListener('click', loadGallery);
  $('gallerySearch').addEventListener('input', function () {
    saveGalleryState();
    renderGallery();
  });
  $('mediaTypeFilter').addEventListener('change', function () {
    saveGalleryState();
    renderGallery();
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) loadGallery();
  });

  function displayName(currentUser) {
    const name = [currentUser.firstName, currentUser.lastName].filter(Boolean).join(' ');
    return name ? name + ' (' + currentUser.email + ')' : currentUser.email;
  }

  function setMessage(text, type) {
    message.textContent = text;
    message.className = 'gallery-message ' + (type || 'info');
    message.classList.toggle('hidden', !text);
  }

  function readPendingUploads() {
    try {
      const parsed = JSON.parse(localStorage.getItem(PENDING_UPLOADS_KEY)) || [];
      const now = Date.now();
      return parsed.filter(item => item && item.fileKey && now - Number(item.uploadedAt || 0) < PENDING_RETENTION_MS);
    } catch (e) {
      return [];
    }
  }

  function writePendingUploads(items) {
    localStorage.setItem(PENDING_UPLOADS_KEY, JSON.stringify(items));
  }

  function normaliseApiItems(payload) {
    if (!payload) return [];
    if (typeof payload.body === 'string') {
      try { return normaliseApiItems(JSON.parse(payload.body)); } catch (e) { return []; }
    }
    const candidates = Array.isArray(payload)
      ? payload
      : (payload.items || payload.files || payload.results || payload.data || []);
    return Array.isArray(candidates) ? candidates.map(normaliseRecord).filter(Boolean) : [];
  }

  function dynamoValue(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
    if (Object.prototype.hasOwnProperty.call(value, 'S')) return value.S;
    if (Object.prototype.hasOwnProperty.call(value, 'N')) return Number(value.N);
    if (Object.prototype.hasOwnProperty.call(value, 'BOOL')) return value.BOOL;
    if (Object.prototype.hasOwnProperty.call(value, 'L')) return value.L.map(dynamoValue);
    if (Object.prototype.hasOwnProperty.call(value, 'M')) return mapValues(value.M);
    return value;
  }

  function mapValues(record) {
    return Object.fromEntries(Object.entries(record || {}).map(([key, value]) => [key, dynamoValue(value)]));
  }

  function normaliseRecord(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const item = mapValues(raw);
    const fullUrl = item.full_url || item.fullUrl || item.url || '';
    const thumbUrl = item.thumb_url || item.thumbUrl || item.thumbnail_url || item.thumbnailUrl || '';
    const fullUrlSource = item.full_url_source || item.fullUrlSource || '';
    const thumbUrlSource = item.thumb_url_source || item.thumbUrlSource || '';
    const tags = normaliseTags(item.tags, item.tag_counts || item.tagCounts);
    return {
      fileId: String(item.file_id || item.fileId || fullUrl || ''),
      checksum: String(item.checksum || '').toLowerCase(),
      fileType: String(item.file_type || item.fileType || inferMediaType(fullUrl)).toLowerCase(),
      fileName: String(item.file_name || item.fileName || fileNameFromUrl(fullUrl) || 'Processed media'),
      fullUrl: String(fullUrl),
      thumbUrl: String(thumbUrl),
      fullUrlSource: String(fullUrlSource),
      thumbUrlSource: String(thumbUrlSource),
      tags: tags,
      createdAt: Number(item.created_at || item.createdAt || 0),
      status: 'processed'
    };
  }

  function normaliseTags(tags, counts) {
    const countMap = counts && typeof counts === 'object' ? mapValues(counts) : {};
    if (!Array.isArray(tags)) return [];
    return tags.map(tag => {
      if (typeof tag === 'string') return { name: tag, count: Number(countMap[tag] || 1) };
      const value = mapValues(tag || {});
      return { name: String(value.name || value.tag || ''), count: Number(value.count || countMap[value.name] || 1) };
    }).filter(tag => tag.name);
  }

  function inferMediaType(url) {
    const path = String(url).split('?')[0].toLowerCase();
    return /\.(mp4|mov|avi|mkv|webm|m4v)$/.test(path) ? 'video' : 'image';
  }

  function fileNameFromUrl(url) {
    try {
      const path = new URL(url).pathname;
      return decodeURIComponent(path.substring(path.lastIndexOf('/') + 1));
    } catch (e) {
      const plain = String(url).split('?')[0];
      return decodeURIComponent(plain.substring(plain.lastIndexOf('/') + 1));
    }
  }

  function readGalleryState() {
    try {
      return JSON.parse(sessionStorage.getItem(GALLERY_STATE_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function saveGalleryState() {
    try {
      sessionStorage.setItem(GALLERY_STATE_KEY, JSON.stringify({
        search: $('gallerySearch').value,
        mediaType: $('mediaTypeFilter').value
      }));
    } catch (error) {
      // The Gallery remains functional if browser storage is unavailable.
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const field = document.createElement('textarea');
    field.value = text;
    field.readOnly = true;
    field.style.position = 'fixed';
    field.style.opacity = '0';
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand('copy');
    field.remove();
    if (!copied) throw new Error('Clipboard access was denied.');
  }

  function pendingMatchesRecord(pending, record) {
    if (pending.checksum && record.checksum && pending.checksum.toLowerCase() === record.checksum) return true;
    try {
      return decodeURIComponent(new URL(record.fullUrl).pathname).endsWith('/' + pending.fileKey);
    } catch (e) {
      return record.fullUrl.includes(pending.fileKey);
    }
  }

  function reconcilePending() {
    pendingItems = pendingItems.filter(pending => !processedItems.some(record => pendingMatchesRecord(pending, record)));
    writePendingUploads(pendingItems);
  }

  async function fetchProcessedItems(endpoint) {
    const items = [];
    let cursor = '';
    let pageCount = 0;
    do {
      const path = cursor
        ? endpoint + '?cursor=' + encodeURIComponent(cursor)
        : endpoint;
      const payload = await Api.get(path);
      items.push(...normaliseApiItems(payload));
      cursor = payload && payload.next_cursor ? String(payload.next_cursor) : '';
      pageCount += 1;
      if (pageCount > 1000) throw new Error('Gallery pagination did not terminate.');
    } while (cursor);
    return items;
  }

  async function loadGallery() {
    if (refreshButton.disabled) return;
    refreshButton.disabled = true;
    refreshButton.textContent = 'Refreshing…';
    pendingItems = readPendingUploads();
    renderGallery();
    setMessage('Loading processed media…', 'info');

    try {
      const endpoint = (APP_CONFIG.endpoints && APP_CONFIG.endpoints.gallery) || 'files';
      processedItems = (await fetchProcessedItems(endpoint))
        .sort((a, b) => b.createdAt - a.createdAt);
      reconcilePending();
      setMessage('Gallery is up to date. New uploads are checked automatically.', 'success');
    } catch (error) {
      setMessage('Unable to load processed media: ' + error.message, 'error');
    } finally {
      refreshButton.disabled = false;
      refreshButton.textContent = 'Refresh';
      renderGallery();
      scheduleRefresh();
    }
  }

  function scheduleRefresh() {
    if (refreshTimer) window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(loadGallery, AUTO_REFRESH_MS);
  }

  function filteredItems() {
    const query = $('gallerySearch').value.trim().toLowerCase();
    const type = $('mediaTypeFilter').value;
    const pending = pendingItems.map(item => ({
      fileId: item.fileKey,
      checksum: item.checksum || '',
      fileType: String(item.contentType || '').startsWith('video/') ? 'video' : 'image',
      fileName: item.fileName || fileNameFromUrl(item.fileKey),
      fullUrl: '',
      thumbUrl: '',
      fullUrlSource: '',
      thumbUrlSource: '',
      tags: [],
      createdAt: Number(item.uploadedAt || 0),
      status: 'processing',
      fileKey: item.fileKey
    }));
    return pending.concat(processedItems).filter(item => {
      const typeMatches = type === 'all' || item.fileType === type;
      const searchable = [item.fileName].concat(item.tags.map(tag => tag.name)).join(' ').toLowerCase();
      return typeMatches && (!query || searchable.includes(query));
    });
  }

  function renderGallery() {
    grid.replaceChildren();
    const items = filteredItems();
    items.forEach(item => grid.appendChild(createCard(item)));
    grid.classList.toggle('hidden', items.length === 0);
    empty.classList.toggle('hidden', items.length !== 0);
    updateSummary();
  }

  function updateSummary() {
    $('processedCount').textContent = String(processedItems.length);
    $('pendingCount').textContent = String(pendingItems.length);
    const species = new Set();
    processedItems.forEach(item => item.tags.forEach(tag => species.add(tag.name)));
    $('speciesCount').textContent = String(species.size);
  }

  function createCard(item) {
    const article = document.createElement('article');
    article.className = 'media-card ' + (item.status === 'processing' ? 'is-processing' : '');

    const preview = document.createElement(item.fullUrl ? 'a' : 'div');
    preview.className = 'media-preview';
    if (item.fullUrl) {
      preview.href = item.fullUrl;
      preview.target = '_blank';
      preview.rel = 'noopener noreferrer';
      preview.setAttribute('aria-label', 'Open full-size ' + item.fileName);
    }

    if (item.status === 'processing') {
      preview.appendChild(iconPlaceholder(item.fileType === 'video' ? '▶' : '◫', 'Processing'));
      const pulse = document.createElement('span');
      pulse.className = 'processing-pulse';
      preview.appendChild(pulse);
    } else if (item.fileType === 'image' && item.thumbUrl) {
      const image = document.createElement('img');
      image.src = item.thumbUrl;
      image.alt = 'Thumbnail of ' + item.fileName;
      image.loading = 'lazy';
      image.addEventListener('error', function () {
        image.replaceWith(iconPlaceholder('!', 'Thumbnail unavailable'));
      }, { once: true });
      preview.appendChild(image);
    } else {
      preview.appendChild(iconPlaceholder(item.fileType === 'video' ? '▶' : '◫', item.fileType === 'video' ? 'Video' : 'Image'));
    }

    const body = document.createElement('div');
    body.className = 'media-card-body';
    const status = document.createElement('span');
    status.className = 'status-badge ' + item.status;
    status.textContent = statusText(item);

    const title = document.createElement('h2');
    title.textContent = item.fileName;
    title.title = item.fileName;

    const meta = document.createElement('div');
    meta.className = 'media-meta';
    meta.textContent = mediaLabel(item.fileType) + ' · ' + formatDate(item.createdAt);

    const tags = document.createElement('div');
    tags.className = 'tag-list';
    if (item.tags.length) {
      item.tags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = tag.name + (tag.count > 1 ? ' ×' + tag.count : '');
        tags.appendChild(chip);
      });
    } else {
      const noTags = document.createElement('span');
      noTags.className = 'no-tags';
      noTags.textContent = item.status === 'processing' ? 'Species detection in progress' : 'No species detected';
      tags.appendChild(noTags);
    }

    body.append(status, title, meta, tags);
    if (item.status === 'processed' && item.fileType === 'image' && (item.thumbUrlSource || item.fullUrlSource)) {
      const actions = document.createElement('div');
      actions.className = 'media-card-actions';
      if (item.thumbUrlSource) {
        actions.appendChild(copyUrlButton('Copy thumbnail URL', item.thumbUrlSource));
      }
      if (item.fullUrlSource) {
        actions.appendChild(copyUrlButton('Copy original URL', item.fullUrlSource));
      }
      body.appendChild(actions);
    }
    article.append(preview, body);
    return article;
  }

  function copyUrlButton(label, url) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy-url-button';
    button.textContent = label;
    button.title = label + ' stored in DynamoDB';
    button.addEventListener('click', async function () {
      button.disabled = true;
      try {
        await copyText(url);
        button.textContent = 'Copied';
      } catch (error) {
        button.textContent = 'Copy failed';
      }
      window.setTimeout(() => {
        if (!button.isConnected) return;
        button.textContent = label;
        button.disabled = false;
      }, 1800);
    });
    return button;
  }

  function iconPlaceholder(symbol, label) {
    const box = document.createElement('div');
    box.className = 'preview-placeholder';
    const icon = document.createElement('span');
    icon.className = 'preview-icon';
    icon.textContent = symbol;
    const text = document.createElement('span');
    text.textContent = label;
    box.append(icon, text);
    return box;
  }

  function statusText(item) {
    if (item.status !== 'processing') return 'Processed';
    return Date.now() - item.createdAt > SLOW_PROCESSING_MS ? 'Taking longer' : 'Processing';
  }

  function mediaLabel(type) {
    return type === 'video' ? 'Video' : 'Image';
  }

  function formatDate(epoch) {
    if (!epoch) return 'Date unavailable';
    const value = epoch < 100000000000 ? epoch * 1000 : epoch;
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium', timeStyle: 'short'
      }).format(new Date(value));
    } catch (e) {
      return new Date(value).toLocaleString();
    }
  }

  loadGallery();
})();
