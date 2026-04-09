(function () {
  'use strict';

  var MAX_MESSAGES = 15;
  var HISTORY_KEY  = 'axiom_chat_history';
  var COUNT_KEY    = 'axiom_chat_count';

  // --- State ---
  var history = [];
  var count   = 0;
  try {
    history = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
    count   = parseInt(sessionStorage.getItem(COUNT_KEY) || '0', 10);
  } catch (_) {}

  // --- DOM ---
  var toggle      = document.getElementById('chat-toggle');
  var panel       = document.getElementById('chat-panel');
  var msgList     = document.getElementById('chat-messages');
  var input       = document.getElementById('chat-input');
  var sendBtn     = document.getElementById('chat-send');
  var papersPanel  = document.getElementById('papers-panel');
  var papersToggle = document.getElementById('papers-toggle');

  if (!toggle || !panel || !msgList || !input || !sendBtn) return;

  renderMessages();

  // --- Toggle ---
  toggle.addEventListener('click', function () {
    var isOpen = !panel.hidden;
    if (isOpen) {
      panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('chat-open');
    } else {
      if (papersPanel && !papersPanel.hidden) {
        papersPanel.hidden = true;
        if (papersToggle) papersToggle.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('papers-open');
      }
      panel.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
      document.body.classList.add('chat-open');
      renderMessages();
      setTimeout(function () { input.focus(); }, 50);
    }
  });

  // --- Input ---
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  sendBtn.addEventListener('click', sendMessage);

  // --- Render ---
  function renderMessages() {
    msgList.innerHTML = '';
    if (history.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'chat-empty';
      empty.textContent = 'Ask me anything about how Axiom works.';
      msgList.appendChild(empty);
    } else {
      history.forEach(function (item) {
        var bubble = document.createElement('div');
        bubble.className = 'chat-msg ' + item.role;
        bubble.textContent = item.content;
        msgList.appendChild(bubble);
      });
    }
    if (count >= MAX_MESSAGES) showLimitMessage();
    scrollToBottom();
  }

  function scrollToBottom() {
    msgList.scrollTop = msgList.scrollHeight;
  }

  function showLimitMessage() {
    if (!msgList.querySelector('.chat-limit-msg')) {
      var lim = document.createElement('p');
      lim.className = 'chat-limit-msg';
      lim.textContent = 'Session limit reached. Refresh the page to start a new session.';
      msgList.appendChild(lim);
    }
    input.disabled = true;
    sendBtn.disabled = true;
    input.placeholder = 'Session limit reached.';
  }

  function showInlineError(text) {
    var err = document.createElement('p');
    err.className = 'chat-inline-error';
    err.textContent = text;
    msgList.appendChild(err);
    scrollToBottom();
    setTimeout(function () { if (err.parentNode) err.remove(); }, 5000);
  }

  // --- Send ---
  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;
    if (count >= MAX_MESSAGES) { showLimitMessage(); return; }

    var priorHistory = history.slice();
    history.push({ role: 'user', content: text });
    saveState();
    renderMessages();
    input.value = '';
    input.disabled = true;
    sendBtn.disabled = true;

    var typing = document.createElement('div');
    typing.className = 'chat-typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    msgList.appendChild(typing);
    scrollToBottom();

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: priorHistory.slice(-10) })
    })
      .then(function (res) {
        if (res.status === 429) throw new Error('rate_limit');
        if (!res.ok) throw new Error('server_error');
        return res.json();
      })
      .then(function (data) {
        if (typing.parentNode) typing.remove();
        history.push({ role: 'assistant', content: data.reply });
        count++;
        saveState();
        renderMessages();
      })
      .catch(function (err) {
        if (typing.parentNode) typing.remove();
        history = priorHistory;
        saveState();
        renderMessages();
        if (err.message === 'rate_limit') {
          showInlineError('Too many requests. Please wait a moment.');
        } else {
          showInlineError('Something went wrong. Please try again.');
        }
      })
      .finally(function () {
        if (count < MAX_MESSAGES) {
          input.disabled = false;
          sendBtn.disabled = false;
          input.focus();
        }
      });
  }

  function saveState() {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
      sessionStorage.setItem(COUNT_KEY, String(count));
    } catch (_) {}
  }
}());
