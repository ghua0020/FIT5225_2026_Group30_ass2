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
  if (user) {
    $('userInfo').textContent = user.firstName + ' ' + user.lastName + ' (' + user.email + ')';
  }
  $('btnLogout').addEventListener('click', function () {
    Auth.logout();
    window.location.href = './index.html';
  });

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function show(text, cls) {
    msgEl.className = 'msg ' + (cls || 'info');
    msgEl.textContent = text;
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
        show(r.message || 'Subscribed.', 'success');
        $('subTags').value = '';
        loadSubscriptions();
      })
      .catch(err => show(err.message, 'error'));
  });

  loadSubscriptions();
})();