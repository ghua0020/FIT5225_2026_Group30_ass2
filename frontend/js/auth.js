/**
 * Pacific BioArchive — 共享认证工具（成员 A 输出，B/C 直接复用）
 *
 * 用法：
 *   - 登录/注册页：Auth.signUp / Auth.confirmSignUp / Auth.resendCode / Auth.login
 *   - Google 登录：Auth.startGoogleLogin / Auth.handleOAuthCallback
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
  const OAUTH_STATE_KEY = 'pba_oauth_state';
  const OAUTH_VERIFIER_KEY = 'pba_oauth_verifier';
  const OAUTH_REDIRECT_KEY = 'pba_oauth_redirect_uri';

  /* ---------- 底层：调用 Cognito API ---------- */
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
  function saveSession(authResult, username, existingRefreshToken) {
    // Cognito normally omits RefreshToken from a refresh response. Keep the
    // original token so the session can be refreshed more than once.
    const current = getSession();
    const refreshToken = authResult.RefreshToken || existingRefreshToken ||
      (current && current.refreshToken) || null;
    localStorage.setItem(TOKEN_KEY, JSON.stringify({
      idToken: authResult.IdToken,
      accessToken: authResult.AccessToken,
      refreshToken: refreshToken,
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

  function clearOAuthTransaction() {
    try {
      sessionStorage.removeItem(OAUTH_STATE_KEY);
      sessionStorage.removeItem(OAUTH_VERIFIER_KEY);
      sessionStorage.removeItem(OAUTH_REDIRECT_KEY);
    } catch (e) {
      // Local sign-out must still succeed when browser storage is unavailable.
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    clearOAuthTransaction();
  }

  /** Clear the local session and the Cognito managed-login cookie. */
  function signOut() {
    logout();
    try {
      const logoutUri = new URL('./login.html', global.location.href).href;
      const url = new URL('/logout', oauthBaseUrl());
      url.searchParams.set('client_id', CFG.cognitoClientId);
      url.searchParams.set('logout_uri', logoutUri);
      global.location.assign(url.toString());
    } catch (e) {
      global.location.href = './login.html';
    }
  }

  /* ---------- 认证流程 ---------- */
  async function signUp(email, firstName, lastName, password) {
    const data = await cognitoRequest('SignUp', {
      ClientId: CFG.cognitoClientId,
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
      Username: username,
      ConfirmationCode: code
    });
  }

  async function resendCode(username) {
    return cognitoRequest('ResendConfirmationCode', {
      ClientId: CFG.cognitoClientId,
      Username: username
    });
  }

  async function login(username, password) {
    const data = await cognitoRequest('InitiateAuth', {
      ClientId: CFG.cognitoClientId,
      AuthFlow: 'USER_PASSWORD_AUTH',
      AuthParameters: {
        USERNAME: username,
        PASSWORD: password
      }
    });
    if (data.ChallengeName) {
      // 本作业配置下不应出现（NEW_PASSWORD_REQUIRED 等），出现则抛出便于排查
      throw new Error('Unexpected Cognito challenge: ' + data.ChallengeName);
    }
    saveSession(data.AuthenticationResult, username);
    return data.AuthenticationResult;
  }

  function oauthBaseUrl() {
    const domain = String(CFG.cognitoDomain || '')
      .trim()
      .replace(/^https?:\/\//i, '')
      .replace(/\/+$/, '');
    if (!domain || domain.indexOf('YOUR_') === 0) {
      throw new Error('Cognito domain is not configured.');
    }
    return 'https://' + domain;
  }

  function base64Url(bytes) {
    let binary = '';
    bytes.forEach(function (byte) { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function randomBase64Url(byteLength) {
    const bytes = new Uint8Array(byteLength);
    global.crypto.getRandomValues(bytes);
    return base64Url(bytes);
  }

  async function pkceChallenge(verifier) {
    const digest = await global.crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(verifier)
    );
    return base64Url(new Uint8Array(digest));
  }

  /** Start Google federation through Cognito using authorization code + PKCE. */
  async function startGoogleLogin() {
    if (!global.crypto || !global.crypto.subtle) {
      throw new Error('Google sign-in requires HTTPS or localhost.');
    }

    const state = randomBase64Url(32);
    const verifier = randomBase64Url(64);
    const challenge = await pkceChallenge(verifier);
    const redirectUri = new URL('./auth-callback.html', global.location.href).href;

    try {
      sessionStorage.setItem(OAUTH_STATE_KEY, state);
      sessionStorage.setItem(OAUTH_VERIFIER_KEY, verifier);
      sessionStorage.setItem(OAUTH_REDIRECT_KEY, redirectUri);
    } catch (e) {
      throw new Error('Browser session storage is required for Google sign-in.');
    }

    const url = new URL('/oauth2/authorize', oauthBaseUrl());
    url.searchParams.set('identity_provider', 'Google');
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('client_id', CFG.cognitoClientId);
    url.searchParams.set('redirect_uri', redirectUri);
    url.searchParams.set('scope', 'openid email profile');
    url.searchParams.set('state', state);
    url.searchParams.set('code_challenge', challenge);
    url.searchParams.set('code_challenge_method', 'S256');
    global.location.assign(url.toString());
  }

  /** Validate the OAuth callback and exchange its code for Cognito tokens. */
  async function handleOAuthCallback() {
    const params = new URLSearchParams(global.location.search);
    const oauthError = params.get('error');
    if (oauthError) {
      const description = params.get('error_description');
      clearOAuthTransaction();
      throw new Error(description || ('Google sign-in failed: ' + oauthError));
    }

    const code = params.get('code');
    const returnedState = params.get('state');
    let expectedState;
    let verifier;
    let redirectUri;
    try {
      expectedState = sessionStorage.getItem(OAUTH_STATE_KEY);
      verifier = sessionStorage.getItem(OAUTH_VERIFIER_KEY);
      redirectUri = sessionStorage.getItem(OAUTH_REDIRECT_KEY);
    } catch (e) {
      throw new Error('Browser session storage is unavailable. Start Google sign-in again.');
    }

    if (!code) throw new Error('Missing authorization code. Start Google sign-in again.');
    if (!returnedState || !expectedState || returnedState !== expectedState) {
      clearOAuthTransaction();
      throw new Error('Google sign-in state validation failed. Start again.');
    }
    if (!verifier || !redirectUri) {
      clearOAuthTransaction();
      throw new Error('Google sign-in session expired. Start again.');
    }
    const currentCallback = new URL(global.location.href);
    currentCallback.search = '';
    currentCallback.hash = '';
    if (redirectUri !== currentCallback.href) {
      clearOAuthTransaction();
      throw new Error('Google sign-in redirect validation failed. Start again.');
    }

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CFG.cognitoClientId,
      code: code,
      redirect_uri: redirectUri,
      code_verifier: verifier
    });
    const response = await fetch(oauthBaseUrl() + '/oauth2/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString()
    });

    let data = null;
    try { data = await response.json(); } catch (e) { data = null; }
    if (!response.ok) {
      const detail = data && (data.error_description || data.error);
      throw new Error(detail || ('Token exchange failed: HTTP ' + response.status));
    }
    if (!data || !data.id_token || !data.access_token) {
      throw new Error('Cognito returned an incomplete Google session.');
    }

    const identity = parseJwtPayload(data.id_token);
    saveSession({
      IdToken: data.id_token,
      AccessToken: data.access_token,
      RefreshToken: data.refresh_token,
      ExpiresIn: data.expires_in
    }, identity.email || identity['cognito:username'] || 'Google user');
    clearOAuthTransaction();
    return data;
  }

  /** 用 refresh token 刷新会话（token 过期时自动调用）。 */
  async function refreshSession() {
    const s = getSession();
    if (!s || !s.refreshToken) return null;
    try {
      const data = await cognitoRequest('InitiateAuth', {
        ClientId: CFG.cognitoClientId,
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        AuthParameters: {
          REFRESH_TOKEN: s.refreshToken
        }
      });
      saveSession(data.AuthenticationResult, localStorage.getItem(USER_KEY), s.refreshToken);
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
    signUp, confirmSignUp, resendCode, login, startGoogleLogin, handleOAuthCallback,
    logout, signOut, refreshSession,
    isAuthenticated, requireAuth, redirectIfAuthenticated,
    getSession, getCurrentUser, authHeaders, apiGet
  };
})(window);
