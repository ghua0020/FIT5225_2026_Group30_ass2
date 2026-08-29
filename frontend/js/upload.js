/**
 * Pacific BioArchive — 上传页逻辑（成员 A）
 * 流程：SHA-256 checksum → 调 /upload-url 拿 presigned URL（Lambda 内做去重检查）
 *       → PUT 直传 S3（支持大视频，无 API Gateway 10MB 限制）
 */
(function () {
  'use strict';

  const PENDING_UPLOADS_KEY = 'pba_pending_uploads';

  // 路由守卫：未登录跳注册页
  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const msg = $('msg');
  const list = $('fileList');

  // 导航栏用户信息
  const user = Auth.getCurrentUser();
  const UPLOAD_STATE_KEY = 'pba_upload_page_state:' + String((user && (user.sub || user.email)) || 'anonymous');
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    sessionStorage.removeItem(UPLOAD_STATE_KEY);
    Auth.logout();
    window.location.href = './index.html';
  });

  function show(text, cls) {
    msg.className = 'msg ' + (cls || 'info');
    msg.textContent = text;
    saveUploadState();
  }

  function readUploadState() {
    try {
      return JSON.parse(sessionStorage.getItem(UPLOAD_STATE_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function saveUploadState() {
    try {
      sessionStorage.setItem(UPLOAD_STATE_KEY, JSON.stringify({
        message: msg.textContent,
        messageClass: msg.className,
        listHtml: list.innerHTML,
        showGalleryLink: !$('galleryLink').classList.contains('hidden')
      }));
    } catch (error) {
      // The upload flow remains functional if browser storage is unavailable.
    }
  }

  /** SHA-256（crypto.subtle 需要 secure context：localhost 或 https 均可） */
  async function sha256(file) {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
  }

  /** 上传单个文件 */
  async function uploadFile(file) {
    show('Computing checksum of ' + file.name + ' ...', 'info');
    const checksum = await sha256(file);

    // 1. 请求 presigned URL（Lambda 内根据 checksum 去重）
    const contentType = file.type || 'application/octet-stream';
    const data = await Auth.apiGet('upload-url', {
      filename: file.name,
      content_type: contentType,
      checksum: checksum
    });

    if (data.duplicate) {
      show('Duplicate detected (same checksum): "' + file.name + '" was skipped.', 'success');
      addLine(file.name, 'duplicate');
      return;
    }

    // 2. PUT 直传 S3（Content-Type 必须与 presigned URL 一致）
    show('Uploading ' + file.name + ' ...', 'info');
    const putResp = await fetch(data.uploadUrl, {
      method: 'PUT',
      headers: data.uploadHeaders || { 'Content-Type': contentType },
      body: file
    });
    if (!putResp.ok) {
      // S3 的错误是 XML 格式，解析出 <Code>/<Message> 便于定位（如 SignatureDoesNotMatch / AccessDenied）
      let detail = '';
      try {
        const text = await putResp.text();
        const code = text.match(/<Code>([^<]+)<\/Code>/);
        const message = text.match(/<Message>([^<]+)<\/Message>/);
        detail = (code ? code[1] : '') + (message ? ': ' + message[1] : '');
      } catch (e) { /* 非 XML 响应时忽略 */ }
      throw new Error('S3 direct upload failed: HTTP ' + putResp.status + (detail ? ' — ' + detail : ''));
    }

    rememberPendingUpload({
      fileKey: data.fileKey,
      fileName: file.name,
      checksum: checksum,
      contentType: contentType,
      uploadedAt: Date.now()
    });
    show('Uploaded: ' + file.name + ' → ' + data.fileKey + '. Processing will start automatically.', 'success');
    addLine(file.name, 'uploaded', data.fileKey);
    $('galleryLink').classList.remove('hidden');
    saveUploadState();
  }

  /** Keep lightweight browser-side state until the Gallery API exposes the DB record. */
  function rememberPendingUpload(item) {
    let pending = [];
    try {
      pending = JSON.parse(localStorage.getItem(PENDING_UPLOADS_KEY)) || [];
    } catch (e) { pending = []; }
    pending = pending.filter(existing => existing.fileKey !== item.fileKey);
    pending.unshift(item);
    localStorage.setItem(PENDING_UPLOADS_KEY, JSON.stringify(pending.slice(0, 50)));
  }

  function createUploadRecord(name, status, fileKey) {
    const row = document.createElement('div');
    row.className = 'upload-record';

    const fileName = document.createElement('span');
    fileName.className = 'upload-record-name';
    fileName.textContent = name;

    const statusBadge = document.createElement('span');
    statusBadge.className = 'upload-record-status ' + (status === 'duplicate' ? 'duplicate' : 'uploaded');
    statusBadge.textContent = status === 'duplicate' ? 'Duplicate skipped' : 'Uploaded';

    row.append(fileName, statusBadge);
    if (fileKey) {
      const path = document.createElement('code');
      path.className = 'upload-record-path';
      path.textContent = fileKey;
      row.appendChild(path);
    }
    return row;
  }

  function addLine(name, status, fileKey) {
    list.appendChild(createUploadRecord(name, status, fileKey));
    saveUploadState();
  }

  function migrateLegacyUploadRecords() {
    Array.from(list.children).forEach(item => {
      if (item.classList.contains('upload-record')) return;
      const match = item.textContent.trim().match(/^•?\s*(.*?)\s+—\s+(.*)$/);
      if (!match) return;

      const uploaded = match[2].match(/^uploaded\s+\((.*)\)$/i);
      const replacement = uploaded
        ? createUploadRecord(match[1], 'uploaded', uploaded[1])
        : createUploadRecord(match[1], 'duplicate');
      item.replaceWith(replacement);
    });
  }

  $('btnUpload').addEventListener('click', async function () {
    const input = $('fileInput');
    if (!input.files || input.files.length === 0) {
      show('Please choose a file first.', 'error');
      return;
    }
    const btn = this;
    btn.disabled = true;
    try {
      for (const file of input.files) {
        await uploadFile(file);
      }
      input.value = '';
    } catch (err) {
      show('Upload failed: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  const uploadState = readUploadState();
  if (uploadState.message) {
    msg.textContent = uploadState.message;
    msg.className = uploadState.messageClass || 'msg info';
  }
  if (typeof uploadState.listHtml === 'string') {
    list.innerHTML = uploadState.listHtml;
    migrateLegacyUploadRecords();
  }
  if (uploadState.showGalleryLink) $('galleryLink').classList.remove('hidden');
  saveUploadState();
})();
