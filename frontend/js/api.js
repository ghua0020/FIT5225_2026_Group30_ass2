/**
 * Pacific BioArchive — API 客户端（成员 C）
 * 复用 Auth.authHeaders()（成员 A 输出），提供 GET/POST 封装。
 * 注意：Auth.apiGet 仅支持 GET；本文件补齐 POST 场景（查询/增删标签等）。
 * 401 时自动登出并跳转注册页。
 *
 * 用法：
 *   const r = await Api.get('search/by-species?species=koala');
 *   const r = await Api.post('search/by-tags', { koala: 3 });
 */
(function (global) {
  'use strict';

  const CFG = global.APP_CONFIG;

  function baseUrl() {
    if (!CFG.queryApiBaseUrl) {
      throw new Error('queryApiBaseUrl is not configured in js/config.js');
    }
    return CFG.queryApiBaseUrl;
  }

  async function request(method, path, body) {
    const opts = { method: method, headers: Auth.authHeaders() };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(baseUrl() + path, opts);
    if (resp.status === 401) {
      Auth.logout();
      window.location.href = './signup.html';
      throw new Error('Session expired, please sign in again.');
    }
    let data = null;
    try { data = await resp.json(); } catch (e) { /* 非 JSON 响应仍走状态码判断 */ }
    if (!resp.ok) {
      throw new Error((data && data.error) ? data.error : ('HTTP ' + resp.status));
    }
    return data;
  }

  global.Api = {
    get: function (path) { return request('GET', path); },
    post: function (path, body) { return request('POST', path, body); }
  };
})(window);