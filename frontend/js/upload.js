/**
 * Pacific BioArchive — 上传页逻辑（成员 A）
 * 流程：SHA-256 checksum → 调 /upload-url 拿 presigned URL（Lambda 内做去重检查）
 *       → PUT 直传 S3（支持大视频，无 API Gateway 10MB 限制）
 */
(function () {
  'use strict';

  // 路由守卫：未登录跳注册页
  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const msg = $('msg');
  const list = $('fileList');

  // 导航栏用户信息
  const user = Auth.getCurrentUser();
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    Auth.logout();
    window.location.href = './index.html';
  });

  function show(text, cls) {
    msg.className = 'msg ' + (cls || 'info');
    msg.textContent = text;
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
      addLine(file.name, 'skipped (duplicate)');
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

    show('Uploaded: ' + file.name + ' → ' + data.fileKey + '. Processing will start automatically.', 'success');
    addLine(file.name, 'uploaded (' + data.fileKey + ')');
  }

  function addLine(name, status) {
    const div = document.createElement('div');
    div.textContent = '• ' + name + ' — ' + status;
    list.appendChild(div);
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
})();
