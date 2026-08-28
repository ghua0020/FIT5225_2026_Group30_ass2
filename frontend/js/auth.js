/**
 * Pacific BioArchive — 共享认证工具（成员 A 输出，B/C 直接复用）
 *
 * 用法：
 *   - 登录/注册页：Auth.signUp / Auth.confirmSignUp / Auth.resendCode / Auth.login
 *   - 受保护页面：Auth.requireAuth()（未登录自动跳 signup.html）
 *   - 调后端 API：Auth.apiGet(path, params)（自动带 Bearer token，自动刷新过期 token）
 *   - 手写 header：Auth.authHeaders()
 *
 * 说明：前端直连 Cognito 公共端点（SignUp/ConfirmSignUp/InitiateAuth 无需签名），
 * 需要 App Client 启用 "ALLOW_USER_PASSWORD_AUTH"（见 AWS_SETUP_GUIDE.md Step 1）。
 */
(function (global) {
  'use strict';

  const CFG = global.APP_CONFIG;
  const COGNITO_ENDPOINT = 'https://cognito-idp.' + CFG.region + '.amazonaws.com/';
  const TOKEN_KEY = 'pba_tokens';
  const USER_KEY = 'pba_username';

  /* ---------- 底层：调用 Cognito API ---------- */
  /** SECRET_HASH = Base64(HMAC-SHA256(clientSecret, username + clientId))；
   *  未配置 client secret 时返回 undefined（JSON.stringify 自动省略该字段，Public client 不受影响） */
  async function computeSecretHash(username) {
    if (!CFG.cognitoClientSecret) return undefined;
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(CFG.cognitoClientSecret),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign']
    );
    const msg = new TextEncoder().encode(username + CFG.cognitoClientId);
    const sig = await crypto.subtle.sign('HMAC', key, msg);
    return btoa(String.fromCharCode(...new Uint8Array(sig)));
  }

  async function cognitoRequest(action, body) {
    const resp = await fetch(COGNITO_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.' + action
      },
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (!resp.ok) {
      const err = new Error(data.message || data.__type || ('Cognito error ' + resp.status));
      err.code = data.__type;
      throw err;
    }
    return data;
  }

  /* ---------- 会话管理 ---------- */
  function saveSession(authResult, username) {
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      idToken: authResult.IdToken,
      accessToken: authResult.AccessToken,
      refreshToken: authResult.RefreshToken,
      expiresAt: Date.now() + (authResult.ExpiresIn || 3600) * 1000
    }));
    if (username) localStorage.setItem(USER_KEY, username);
  }

  function getSession() {
    try { return JSON.parse(localStorage.getItem(TOKEN_KEY)); } catch (e) { return null; }
  }

  function isAuthenticated() {
    const s = getSession();
    return !!(s && s.idToken && s.expiresAt > Date.now());
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  /* ---------- 认证流程 ---------- */
  async function signUp(email, firstName, lastName, password) {
    const data = await cognitoRequest('SignUp', {
      ClientId: CFG.cognitoClientId,
      SecretHash: await computeSecretHash(email),
      Username: email,
      Password: password,
      UserAttributes: [
        { Name: 'email', Value: email },
        { Name: 'given_name', Value: firstName },
        { Name: 'family_name', Value: lastName }
      ]
    });
    return data; // { UserConfirmed: false, UserSub, ... }
  }

  async function confirmSignUp(username, code) {
    return cognitoRequest('ConfirmSignUp', {
      ClientId: CFG.cognitoClientId,
      SecretHash: await computeSecretHash(username),
      Username: username,
      ConfirmationCode: code
    });
  }

  async function resendCode(username) {
    return cognitoRequest('ResendConfirmationCode', {
      ClientId: CFG.cognitoClientId,
      SecretHash: await computeSecretHash(username),
      Username: username
    });
  }

  async function login(username, password) {
    const data = await cognitoRequest('InitiateAuth', {
      ClientId: CFG.cognitoClientId,
      AuthFlow: 'USER_PASSWORD_AUTH',
      AuthParameters: {
        USERNAME: username,
        PASSWORD: password,
        SECRET_HASH: await computeSecretHash(username)
      }
    });
    if (data.ChallengeName) {
      // 本作业配置下不应出现（NEW_PASSWORD_REQUIRED 等），出现则抛出便于排查
      throw new Error('Unexpected Cognito challenge: ' + data.ChallengeName);
    }
    saveSession(data.AuthenticationResult, username);
    return data.AuthenticationResult;
  }

  /** 用 refresh token 刷新会话（token 过期时自动调用）
   *  REFRESH_TOKEN_AUTH 的 SECRET_HASH 按 Cognito 官方 SDK 约定以 clientId 作为 username 计算 */
  async function refreshSession() {
    const s = getSession();
    if (!s || !s.refreshToken) return null;
    try {
      const data = await cognitoRequest('InitiateAuth', {
        ClientId: CFG.cognitoClientId,
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        AuthParameters: {
          REFRESH_TOKEN: s.refreshToken,
          SECRET_HASH: await computeSecretHash(CFG.cognitoClientId)
        }
      });
      saveSession(data.AuthenticationResult, localStorage.getItem(USER_KEY));
      return data.AuthenticationResult;
    } catch (e) {
      logout();
      return null;
    }
  }

  /* ---------- 工具 ---------- */
  function parseJwtPayload(token) {
    try {
      const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const binary = atob(payload);
      const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
      return JSON.parse(new TextDecoder().decode(bytes));
    } catch (e) { return {}; }
  }

  function getCurrentUser() {
    const s = getSession();
    if (!s) return null;
    const p = parseJwtPayload(s.idToken);
    return { email: p.email, firstName: p.given_name, lastName: p.family_name, sub: p.sub };
  }

  /** 带认证头的请求头（B/C 复用：手写 fetch 时展开） */
  function authHeaders() {
    const s = getSession();
    return s && s.idToken ? { Authorization: 'Bearer ' + s.idToken } : {};
  }

  /** 路由守卫：未登录跳注册页 */
  function requireAuth() {
    if (!isAuthenticated()) {
      window.location.href = './signup.html';
      return false;
    }
    return true;
  }

  /** 已登录用户访问登录/注册页时跳回首页 */
  function redirectIfAuthenticated() {
    if (isAuthenticated()) window.location.href = './index.html';
  }

  /** 通用 GET：自动刷新过期 token、自动带 Authorization、401 时登出 */
  async function apiGet(path, params) {
    if (!isAuthenticated() && !(await refreshSession())) {
      window.location.href = './signup.html';
      throw new Error('Not signed in.');
    }
    const url = new URL(CFG.apiBaseUrl + path, window.location.origin);
    if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.append(k, v));
    const resp = await fetch(url, { headers: authHeaders() });
    if (resp.status === 401) {
      logout();
      window.location.href = './signup.html';
      throw new Error('Session expired, please sign in again.');
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      data = null;
    }
    if (!resp.ok) {
      const message = data && (data.error || data.message);
      const err = new Error(message || ('API request failed: HTTP ' + resp.status));
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  /* ---------- 导出 ---------- */
  global.Auth = {
    signUp, confirmSignUp, resendCode, login, logout, refreshSession,
    isAuthenticated, requireAuth, redirectIfAuthenticated,
    getSession, getCurrentUser, authHeaders, apiGet
  };
})(window);
