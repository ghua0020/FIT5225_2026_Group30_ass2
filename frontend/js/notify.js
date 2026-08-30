/**
 * Pacific BioArchive — 通知设置页逻辑（成员 C）
 * §4.4 按标签订阅/退订：新增标签时 SNS 会向该邮箱发送确认邮件，点击后订阅生效。
 */
(function () {
  'use strict';

  if (!Auth.requireAuth()) return;

  const $ = id => document.getElementById(id);
  const chipsEl = $('chips');
  const emptyNote = $('emptyNote');
  const msgEl = $('msg');

  const user = Auth.getCurrentUser();
  const NOTIFY_STATE_KEY = 'pba_notify_page_state:' + String((user && (user.sub || user.email)) || 'anonymous');
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    sessionStorage.removeItem(NOTIFY_STATE_KEY);
    Auth.signOut();
  });

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function readNotifyState() {
    try {
      return JSON.parse(sessionStorage.getItem(NOTIFY_STATE_KEY)) || {};
    } catch (error) {
      return {};
    }
  }

  function saveNotifyState() {
    try {
      sessionStorage.setItem(NOTIFY_STATE_KEY, JSON.stringify({
        draft: $('subTags').value,
        message: msgEl.textContent,
        messageClass: msgEl.className
      }));
    } catch (error) {
      // The page remains functional if browser storage is unavailable.
    }
  }

  function show(text, cls) {
    msgEl.className = 'msg ' + (cls || 'info');
    msgEl.textContent = text;
    saveNotifyState();
  }

  function renderChips(tags) {
    chipsEl.innerHTML = '';
    emptyNote.textContent = '';
    if (!tags || tags.length === 0) {
      emptyNote.textContent = 'No subscriptions yet.';
      return;
    }
    tags.forEach(tag => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = escapeHtml(tag) + ' <button type="button" title="Remove">×</button>';
      chip.querySelector('button').addEventListener('click', () => unsubscribe(tag));
      chipsEl.appendChild(chip);
    });
  }

  function loadSubscriptions() {
    Api.get('notify/subscriptions')
      .then(r => renderChips(r.tags || []))
      .catch(err => show(err.message, 'error'));
  }

  function unsubscribe(tag) {
    Api.post('notify/unsubscribe', { tags: [tag] })
      .then(() => { show('Unsubscribed from "' + tag + '".', 'success'); loadSubscriptions(); })
      .catch(err => show(err.message, 'error'));
  }

  $('btnSubscribe').addEventListener('click', function () {
    const tags = $('subTags').value.split(',').map(s => s.trim()).filter(Boolean);
    if (!tags.length) { show('Please enter at least one species.', 'error'); return; }
    Api.post('notify/subscribe', { tags: tags })
      .then(r => {
        $('subTags').value = '';
        show(r.message || 'Subscribed.', 'success');
        loadSubscriptions();
      })
      .catch(err => show(err.message, 'error'));
  });

  $('subTags').addEventListener('input', saveNotifyState);

  const notifyState = readNotifyState();
  if (typeof notifyState.draft === 'string') $('subTags').value = notifyState.draft;
  if (notifyState.message) {
    msgEl.textContent = notifyState.message;
    msgEl.className = notifyState.messageClass || 'msg info';
  }

  loadSubscriptions();
})();
