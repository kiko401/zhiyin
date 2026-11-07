/* 知音前端骨架：卡片渲染 / 任务轮询 / 会话输入 / 登录注册 */
(function () {
  'use strict';

  /* ---------- 基础工具 ---------- */
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls; if (text != null) node.textContent = text; return node;
  }
  function fetchJSON(url, options) { return fetch(url, options).then(function (res) { return res.json(); }); }
  function postJSON(url, body) {
    return fetchJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  }
  function envelope(res) { if (res && res.code === 0) return res.data || {}; throw new Error((res && res.message) || '请求失败'); }
  function dataOf(res) { return (res && res.code === 0 ? res.data : res) || {}; }
  function payloadOf(card) { return (card && (card.payload || card.data)) || {}; }
  function sessionUid() {
    var uid = sessionStorage.getItem('zhiyin_session');
    if (!uid) sessionStorage.setItem('zhiyin_session', uid = 's-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
    return uid;
  }
  function badge(text, variant) { return el('span', 'badge' + (variant ? ' badge--' + variant : ''), text); }
  function cardNode(modifier) { return el('section', 'card card--' + modifier); }
  function textBtn(label, onClick) { var b = el('button', 'btn btn--text', label); b.type = 'button'; b.addEventListener('click', onClick); return b; }
  function noteHead(title, badgeText, variant) {
    var head = el('div', 'note-head'); head.appendChild(el('strong', null, title));
    if (badgeText) head.appendChild(badge(badgeText, variant)); return head;
  }

  /* ---------- 卡片渲染：按 card_type 分派 ---------- */
  var STAGES = ['排队', '规划', '取数', '校验', '组装', '已交付'], TERMINAL = { DELIVERED: 1, FAILED: 1, DEGRADED: 1 };

  function stageBar(current) {
    var idx = STAGES.indexOf(current), bar = el('div', 'stage-bar');
    if (idx < 0) idx = 0;
    for (var i = 0; i < STAGES.length; i++) {
      var node = el('span', 'stage-node');
      node.appendChild(el('i', 'stage-dot'));
      node.appendChild(el('span', 'stage-label', STAGES[i]));
      node.classList.add(i < idx ? 'is-done' : (i === idx ? 'is-current' : 'is-todo'));
      bar.appendChild(node);
      if (i < STAGES.length - 1) bar.appendChild(el('span', i < idx ? 'stage-line is-done' : 'stage-line'));
    }
    return bar;
  }

  function renderClarify(p, card) {
    var node = cardNode('clarify'), cid = card.clarify_id || card.id || p.clarify_id || p.id;
    node.appendChild(noteHead('需要你确认', '澄清', 'clarify'));
    node.appendChild(el('p', 'clarify-question', p.question || p.text || ''));
    if (p.options && p.options.length) {
      var chips = el('div', 'chips');
      p.options.forEach(function (opt) {
        var value = typeof opt === 'string' ? opt : (opt.value || opt.label);
        var chip = el('button', 'chip', typeof opt === 'string' ? opt : (opt.label || value)); chip.type = 'button';
        chip.addEventListener('click', function () {
          if (chip.disabled) return;
          chip.classList.add('is-active');
          chips.querySelectorAll('.chip').forEach(function (c) { c.disabled = true; });
          postJSON('/api/clarify/' + cid + '/choice', { choice: value })
            .then(function (res) { appendCards(cardsOf(res)); }).catch(function () { chip.classList.remove('is-active'); });
        });
        chips.appendChild(chip);
      }); node.appendChild(chips);
    }
    if (cid) {
      var memory = el('div', 'clarify-memory'); memory.appendChild(el('span', null, '这条偏好要记住吗'));
      [['记住', 'remember'], ['仅本次', 'once'], ['别记', 'never']].forEach(function (m) {
        memory.appendChild(textBtn(m[0], function () {
          memory.querySelectorAll('.btn--text').forEach(function (x) { x.disabled = true; });
          postJSON('/api/clarify/' + cid + '/memory', { action: m[1] }).catch(function () {});
        }));
      });
      node.appendChild(memory);
    }
    return node;
  }

  function renderBoundary(p) {
    var node = cardNode('boundary'); node.appendChild(el('p', 'boundary-title', p.title || '边界提示'));
    var items = p.items || p.rules || [];
    if (items.length) {
      var list = el('ul', 'boundary-list');
      items.forEach(function (it) { list.appendChild(el('li', null, typeof it === 'string' ? it : (it.text || it.rule || ''))); });
      node.appendChild(list);
    } else { node.appendChild(el('p', null, p.message || p.text || '')); }
    return node;
  }

  function renderWork(p) {
    var node = cardNode('work'), uid = p.task_uid || p.task_id;
    node.appendChild(noteHead(p.title || '任务执行', uid ? String(uid).slice(-6) : null, 'stage'));
    var bar = stageBar(p.stage || p.status); node.appendChild(bar);
    if (p.detail || p.current_action) node.appendChild(el('p', 'work-detail', p.detail || p.current_action));
    if (uid && !TERMINAL[String(p.status || '').toUpperCase()]) {
      pollTask(uid, function (task) { var fresh = stageBar(task.stage || task.status); bar.replaceWith(fresh); bar = fresh; });
    }
    return node;
  }

  function renderAnswer(p) {
    var node = cardNode('answer');
    node.appendChild(el('p', 'card-title', p.title || '回答'));
    if (p.summary || p.text) node.appendChild(el('p', 'answer-summary', p.summary || p.text));
    var sections = p.sections || [
      { title: '事实', content: p.facts }, { title: '分析', content: p.analysis },
      { title: '依据', content: p.evidence }, { title: '边界', content: p.boundary }];
    (Array.isArray(sections) ? sections : []).forEach(function (sec, i) {
      var fold = el('details', 'ans-fold'); if (i === 0) fold.open = true;
      fold.appendChild(el('summary', 'ans-fold-head', sec.title || ('段落 ' + (i + 1))));
      var c = sec.content || sec.body || sec.text;
      fold.appendChild(el('div', 'ans-fold-body', Array.isArray(c) ? c.join('\n') : (c == null ? '待补充' : String(c))));
      node.appendChild(fold);
    });
    node.appendChild(el('span', 'ans-corner')).appendChild(badge(p.flag || '可溯源', 'fact'));
    return node;
  }

  function renderBriefing(p, card) {
    var node = cardNode('briefing');
    node.appendChild(el('p', 'card-title', p.title || p.date || '简报'));
    if (p.facts && p.facts.length) {
      var facts = el('ul', 'briefing-facts');
      p.facts.forEach(function (f) {
        var li = el('li', null); li.appendChild(badge('事实', 'fact'));
        li.appendChild(document.createTextNode(' ' + (typeof f === 'string' ? f : (f.text || ''))));
        facts.appendChild(li);
      });
      node.appendChild(facts);
    }
    if (p.impact || p.impact_text) node.appendChild(el('p', 'briefing-impact', p.impact || p.impact_text));
    var bid = card.briefing_id || p.briefing_id || p.id, actions = el('div', 'card-actions');
    [['转任务', 'btn', 'to_task'], ['这条不重要', 'btn btn--ghost', 'noise']].forEach(function (m) {
      var b = el('button', m[1], m[0]); b.type = 'button'; if (!bid) b.disabled = true;
      b.addEventListener('click', function () {
        b.disabled = true; if (m[2] === 'noise') node.classList.add('is-muted');
        postJSON('/api/briefing/' + bid + '/feedback', { action: m[2] }).catch(function () {});
      });
      actions.appendChild(b);
    });
    node.appendChild(actions);
    return node;
  }

  function renderSpec(p) {
    var node = cardNode('spec');
    node.appendChild(el('p', 'card-title', p.title || '研究规格')); var wrap = el('div', 'spec-fields');
    (p.fields || []).forEach(function (f) {
      var raw = f.value == null ? '' : (typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value));
      var row = el('div', 'field-row'); row.appendChild(el('span', 'field-name', f.name || f.key || ''));
      row.appendChild(el('span', 'field-value', raw));
      if (f.source) row.appendChild(badge(f.source === 'inferred' ? '推断' : f.source, f.source === 'inferred' ? 'inferred' : 'fact'));
      if (f.editable) row.appendChild(textBtn('改', function () {
        var next = window.prompt('修改「' + (f.name || f.key) + '」', raw);
        if (next != null && next !== raw) row.querySelector('.field-value').textContent = next;
      }));
      wrap.appendChild(row);
    });
    node.appendChild(wrap);
    return node;
  }

  function renderDelegate(p) {
    var node = cardNode('delegate');
    node.appendChild(noteHead(p.title || '已转为任务', p.status || null, 'stage'));
    if (p.desc || p.text) node.appendChild(el('p', null, p.desc || p.text));
    if (p.task_uid) { var a = el('a', 'link', '查看任务进度'); a.href = '/tasks'; node.appendChild(a); }
    return node;
  }

  function renderNote(modifier, title, p, badgeText, variant) {
    var node = cardNode(modifier);
    node.appendChild(noteHead(p.title || title, p.source || p.scope || badgeText, variant));
    node.appendChild(el('p', null, p.definition || p.content || p.note || p.text || ''));
    return node;
  }
  function renderSystemBanner(p) { return el('div', (p.level || '') === 'degraded' ? 'banner--degraded' : 'system-banner', p.text || p.message || ''); }
  function renderFallback(card) {
    var node = cardNode('fallback');
    node.appendChild(el('p', 'card-title', (card && card.card_type) || '未知卡片'));
    var pre = el('pre', 'fallback-payload');
    try { pre.textContent = JSON.stringify((card && card.payload) || card || {}, null, 2); } catch (e) { /* 忽略 */ }
    node.appendChild(pre); return node;
  }

  var RENDERERS = {
    lexicon_note: function (p) { return renderNote('lexicon-note', '词条', p, null, 'source'); },
    memory_note: function (p) { return renderNote('memory-note', '记忆', p, '推断', 'inferred'); },
    clarify: renderClarify, boundary: renderBoundary, spec: renderSpec, delegate: renderDelegate,
    work: renderWork, answer: renderAnswer, briefing: renderBriefing, system_banner: renderSystemBanner
  };

  function renderCard(card) {
    var fn = card && RENDERERS[card.card_type];
    try { return fn ? fn(payloadOf(card), card || {}) : renderFallback(card); } catch (e) { return renderFallback(card); }
  }

  /* ---------- 任务轮询：2 秒一查，页面不可见暂停，终态停止 ---------- */
  function pollTask(taskUid, onUpdate) {
    var timer = null, stopped = false;
    function tick() {
      if (stopped || document.hidden) return;
      fetchJSON('/api/task/' + encodeURIComponent(taskUid)).then(function (res) {
        var task = dataOf(res);
        if (onUpdate) onUpdate(task);
        if (TERMINAL[String(task.status || '').toUpperCase()]) stop();
      }).catch(function () { /* 单次失败忽略，等待下一轮 */ });
    }
    function start() { if (timer || stopped) return; timer = setInterval(tick, 2000); tick(); }
    function stop() { stopped = true; if (timer) { clearInterval(timer); timer = null; } }
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { if (timer) { clearInterval(timer); timer = null; } } else if (!stopped) start();
    });
    start(); return stop;
  }

  /* ---------- 会话输入与消息流 ---------- */
  function cardsOf(res) { var data = dataOf(res); return Array.isArray(data) ? data : (data.cards || []); }
  function appendCards(stream, cards) {
    var last = null; (cards || []).forEach(function (c) { last = renderCard(c); stream.appendChild(last); });
    if (last) last.scrollIntoView({ block: 'end' });
  }

  function initComposer() {
    var stream = document.getElementById('stream');
    var composer = document.getElementById('composer');
    if (!stream || !composer) return;
    var input = composer.querySelector('.composer-input'), count = composer.querySelector('.composer-count');
    var sendBtn = composer.querySelector('.composer-send'), empty = stream.querySelector('.empty-state');
    var max = Number(input && input.getAttribute('maxlength')) || 2000, busy = false;
    function send() {
      var text = input.value.trim();
      if (!text || busy) return;
      busy = true;
      if (empty) { empty.remove(); empty = null; }
      stream.appendChild(el('div', 'msg-user', text));
      input.value = ''; if (count) count.textContent = '0/' + max;
      postJSON('/api/chat', { text: text, session_uid: sessionUid() })
        .then(function (res) { appendCards(stream, cardsOf(res)); })
        .catch(function () { stream.appendChild(el('div', 'system-banner is-error', '发送失败，请稍后重试')); })
        .then(function () { busy = false; input.focus(); });
    }
    if (input) {
      input.addEventListener('input', function () { if (count) count.textContent = input.value.length + '/' + max; });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
    }
    if (sendBtn) sendBtn.addEventListener('click', send);
    stream.addEventListener('click', function (e) {
      var chip = e.target.closest('.empty-state .chip');
      if (chip && input) { input.value = chip.textContent; send(); }
    });
  }

  /* ---------- 登录 / 注册 / Demo 进入 ---------- */
  function initAuth() {
    var demo = document.getElementById('demo-entry'), form = document.getElementById('login-form');
    var regForm = document.getElementById('register-form'), toggle = document.getElementById('toggle-register');
    var errLine = document.getElementById('auth-error');
    if (!demo && !form && !regForm) return;
    function showErr(msg) { if (errLine) { errLine.textContent = msg; errLine.hidden = false; } }
    function clearErr() { if (errLine) errLine.hidden = true; }
    function submitAuth(url, body, onFail) {
      clearErr();
      postJSON(url, body).then(function (res) { envelope(res); location.href = '/'; })
        .catch(function (err) { if (onFail) onFail(); showErr(err.message || '操作失败，请重试'); });
    }
    function readForm(f) {
      var u = f.username.value.trim(), pw = f.password.value;
      if (!u || !pw) { showErr('请输入用户名与密码'); return null; } return { username: u, password: pw };
    }
    if (demo) demo.addEventListener('click', function () {
      demo.disabled = true;
      submitAuth('/api/auth/login', { username: 'demo', password: 'demo123456' }, function () { demo.disabled = false; });
    });
    if (form) form.addEventListener('submit', function (e) {
      e.preventDefault(); var b = readForm(form); if (b) submitAuth('/api/auth/login', b);
    });
    if (regForm) regForm.addEventListener('submit', function (e) {
      e.preventDefault(); var b = readForm(regForm); if (b) submitAuth('/api/auth/register', b);
    });
    if (toggle) toggle.addEventListener('click', function (e) {
      e.preventDefault(); clearErr();
      var toReg = regForm.hidden;
      regForm.hidden = !toReg; form.hidden = toReg;
      toggle.textContent = toReg ? '返回登录' : '注册新账号';
    });
  }

  /* ---------- 导航当前页高亮 ---------- */
  function initNav() {
    var path = location.pathname.replace(/\/+$/, '') || '/';
    document.querySelectorAll('.site-nav a').forEach(function (a) {
      var href = a.getAttribute('href');
      if (href === '/' ? path === '/' : (path === href || path.indexOf(href + '/') === 0)) a.classList.add('is-active');
    });
  }

  initNav(); initComposer(); initAuth();
})();
