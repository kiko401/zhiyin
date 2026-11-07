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
  function payloadOf(card) {
    if (card && card.payload) return card.payload;
    if (card && card.data) return card.data;
    return card || {};
  }
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
    var node = cardNode('work');
    if (p.task_uid) node.dataset.taskUid = p.task_uid;
    node.appendChild(stageBar(p.state === 'QUEUED' ? '排队' : p.state || ''));
    var info = el('div', 'work-info');
    if (p.blueprint) info.appendChild(el('span', null, '蓝图：' + p.blueprint));
    (p.tools || []).forEach(function (t) {
      if (typeof t === 'object' && t.tool) info.appendChild(el('span', 'chip', t.tool + ' ' + (t.status || '')));
      else info.appendChild(el('span', 'chip', String(t)));
    });
    node.appendChild(info);
    if (p.task_uid && !TERMINAL[String(p.state || '').toUpperCase()]) {
      var loadTip = el('div', 'work-loading');
      loadTip.innerHTML = '正在分析中，约需 20–40 秒 · 已等待 <span class="elapsed">0</span> 秒';
      node.appendChild(loadTip);
      var startTime = Date.now();
      var loadTimer = setInterval(function() {
        var e = loadTip.querySelector('.elapsed');
        if (e) e.textContent = Math.round((Date.now() - startTime) / 1000);
        else clearInterval(loadTimer);
      }, 1000);
      pollTask(p.task_uid, function (task) {
      var stMap = {DELIVERED:'已交付',DEGRADED:'已交付',FAILED:'排队',PLANNING:'规划',FETCHING:'取数',VERIFYING:'校验',ASSEMBLING:'组装'};
      var newBar = stageBar(stMap[task.state] || '排队');
      var old = node.querySelector('.stage-bar');
      if (old) node.replaceChild(newBar, old);
      if ((task.state === 'DELIVERED' || task.state === 'DEGRADED') && task.deliverable) {
        var dl = task.deliverable;
        var ansNode = renderAnswer({card_type:'answer',task_uid:p.task_uid,type:dl.type,summary:dl.summary,pros:dl.pros,cons:dl.cons,gaps:dl.gaps,statement:dl.statement,evidence_lines:dl.evidence_lines,citations:dl.citations,confidence:dl.confidence,fact_text:dl.fact_text,impact_text:dl.impact_text});
        node.parentNode.insertBefore(ansNode, node.nextSibling);
      }
      if (task.state === 'DELIVERED' || task.state === 'DEGRADED') { var lt = node.querySelector('.work-loading'); if (lt) lt.remove(); clearInterval(loadTimer); }
    });
    }
    return node;
  }

  function renderAnswer(p) {
    var node = cardNode('answer');
    var type = p.type || 'four_part';
    if (type === 'briefing') {
      node.appendChild(noteHead(p.headline || '值守简报', '简报', 'stage'));
      node.appendChild(el('p', null, p.fact_text || ''));
      if (p.impact_text) node.appendChild(el('p', 'card-impact', p.impact_text));
    } else if (type === 'fact_card') {
      node.appendChild(noteHead('事实查询', '直答', 'fact'));
      (p.evidence_lines || []).forEach(function (ln) { node.appendChild(el('p', null, ln)); });
    } else if (type === 'evidence_card') {
      node.appendChild(noteHead('证据数据', '降级', 'inferred'));
      node.appendChild(el('p', null, p.statement || 'AI 分析暂不可用'));
      (p.evidence_lines || []).forEach(function (ln) { node.appendChild(el('pre', 'fallback-payload', ln)); });
    } else if (type === 'knowledge_card') {
      node.appendChild(noteHead('知识回答', '知识', 'fact'));
      node.appendChild(el('p', null, p.summary || ''));
      if (p.body) node.appendChild(el('p', null, p.body));
      if (p.gaps) node.appendChild(el('p', 'card-gaps', p.gaps));
    } else {
      var conf = p.confidence === 'high' ? '高' : p.confidence === 'low' ? '低' : '中';
      node.appendChild(noteHead('研究回答', '置信度 ' + conf + ' · AI 生成', 'fact'));
      if (p.summary) node.appendChild(el('p', 'card-summary', p.summary));
      var details = el('details', 'answer-details');
      details.appendChild(el('summary', null, '展开全文'));
      if ((p.pros || []).length) {
        details.appendChild(el('strong', null, '事实与正方论点'));
        p.pros.forEach(function (x) { details.appendChild(el('p', null, x)); });
      }
      if ((p.cons || []).length) {
        details.appendChild(el('strong', null, '反方论点与风险'));
        p.cons.forEach(function (x) { details.appendChild(el('p', null, x)); });
      }
      if (p.gaps) {
        details.appendChild(el('strong', null, '未覆盖与假设'));
        var gapOut = [];
        p.gaps.split(/\n+/).forEach(function (line) {
          line.split(/(?=[①-⑳])|(?=\d+[)）、])/).forEach(function (item) {
            if (item.trim()) gapOut.push(item.trim());
          });
        });
        gapOut.forEach(function (item) { details.appendChild(el('p', null, item)); });
      }
      if ((p.citations || []).length) {
        details.appendChild(el('strong', null, '引用'));
        p.citations.forEach(function (ct) {
          details.appendChild(el('p', 'card-cite', '[' + ct.n + '] ' + (ct.tool || '') + ' · ' + (ct.as_of || '') + ' · ' + (ct.source || '')));
        });
      }
      node.appendChild(details);
    }
    node.appendChild(el('p', 'card-footer', '仅供参考，不构成投资建议 · AI 生成'));
    return node;
  }

  function renderBriefing(p) {
    var node = cardNode('briefing');
    node.appendChild(noteHead(p.headline || '值守简报', '简报', 'stage'));
    node.appendChild(el('p', null, p.fact_text || ''));
    if (p.impact_text) node.appendChild(el('p', 'card-impact', p.impact_text));
    return node;
  }

  function renderSpec(p, card) {
    var node = cardNode('spec');
    node.appendChild(el('p', 'card-title', '研究规格'));
    if (p.spec_uid) node.dataset.specUid = p.spec_uid;
    var ctxHint = el('p', null, '');
    ctxHint.style.cssText = 'font-size:12px;color:#aab4c0;margin:0 0 10px;';
    ctxHint.textContent = '标的 = 哪只股票 · 处境 = 你目前是套着还是赚着 · 周期 = 打算拿多久';
    node.appendChild(ctxHint);
    var wrap = el('div', 'spec-fields');
    (p.fields || []).forEach(function (f) {
      var display = f.value == null ? '' : (typeof f.value === 'object' ? (f.value.name || JSON.stringify(f.value)) : String(f.value));
      var row = el('div', 'field-row');
      row.appendChild(el('span', 'field-name', f.label || f.key || ''));
      row.appendChild(el('span', 'field-value', display));
      var srcLabel = f.resolved_by_label || f.resolved_by;
      if (srcLabel) row.appendChild(badge(srcLabel, f.resolved_by === 'assumption' ? 'inferred' : 'source'));
      wrap.appendChild(row);
    });
    node.appendChild(wrap);
    var hint = el('p', null, '');
    hint.style.cssText = 'font-size:12px;color:#5c6675;margin:10px 0 4px;line-height:1.5;';
    hint.innerHTML = '以上是知音对你问题的理解。<b>确认无误请点下方按钮</b>，知音将开始研究并在完成后给你一份带来源引用的报告。每个字段都可点击修改。';
    node.appendChild(hint);
    var legend = el('p', null, '');
    legend.style.cssText = 'font-size:11px;color:#aab4c0;margin:0 0 8px;';
    legend.innerHTML = '<span class="badge badge--source">词典</span> = 黑话转标准名称 &nbsp; <span class="badge badge--source">画像</span> = 记住了你的偏好 &nbsp; <span class="badge badge--source">检索</span> = 从全市场匹配 &nbsp; <span class="badge badge--inferred">假设</span> = 不确定，可修改';
    node.appendChild(legend);
    var btnWrap = el('div', 'spec-actions');
    var confirmBtn = el('button', 'btn btn--primary', '确认执行'); confirmBtn.type = 'button';
    var busy = false;
    confirmBtn.addEventListener('click', function () {
      if (busy) return; busy = true; confirmBtn.textContent = '执行中…'; confirmBtn.disabled = true;
      var uid = p.spec_uid || (card && card.spec_uid);
      postJSON('/api/spec/' + uid + '/confirm').then(function (res) {
        var d = dataOf(res);
        if (d.task_uid) {
          var wc = el('section', 'card card--work');
          wc.dataset.taskUid = d.task_uid;
          wc.appendChild(stageBar('排队'));
          var loadTip = el('div', 'work-loading');
          loadTip.innerHTML = '正在分析中，约需 20–40 秒 · 已等待 <span class="elapsed">0</span> 秒';
          wc.appendChild(loadTip);
          var startTime = Date.now();
          var loadTimer = setInterval(function() {
            var e = loadTip.querySelector('.elapsed');
            if (e) e.textContent = Math.round((Date.now() - startTime) / 1000);
            else clearInterval(loadTimer);
          }, 1000);
          node.parentNode.insertBefore(wc, node.nextSibling);
          pollTask(d.task_uid, function (task) {
            var stMap = {DELIVERED:'已交付',DEGRADED:'已交付',FAILED:'排队',PLANNING:'规划',FETCHING:'取数',VERIFYING:'校验',ASSEMBLING:'组装'};
            var newBar = stageBar(stMap[task.state] || '排队');
            var old = wc.querySelector('.stage-bar');
            if (old) wc.replaceChild(newBar, old);
            if ((task.state === 'DELIVERED' || task.state === 'DEGRADED') && task.deliverable) {
              var dl = task.deliverable;
              var ansNode = renderAnswer({card_type:'answer',task_uid:task.task_uid,type:dl.type,summary:dl.summary,pros:dl.pros,cons:dl.cons,gaps:dl.gaps,statement:dl.statement,evidence_lines:dl.evidence_lines,citations:dl.citations,confidence:dl.confidence,fact_text:dl.fact_text,impact_text:dl.impact_text});
              wc.parentNode.insertBefore(ansNode, wc.nextSibling);
            }
            if (task.state === 'DELIVERED' || task.state === 'DEGRADED') { var lt = wc.querySelector('.work-loading'); if (lt) lt.remove(); clearInterval(loadTimer); var sp = wc.previousElementSibling; if (sp) { var cb = sp.querySelector('.btn--primary'); if (cb) { cb.textContent = '✓ 已完成'; cb.disabled = true; } } }
          });
        }
      }).catch(function (e) { confirmBtn.textContent = '确认失败：' + (e.message || '重试'); confirmBtn.disabled = false; busy = false; });
    });
    var skipBtn = el('button', 'btn btn--ghost', '本次不使用画像'); skipBtn.type = 'button';
    btnWrap.appendChild(confirmBtn); btnWrap.appendChild(skipBtn);
    node.appendChild(btnWrap);
    return node;
  }

  function renderDelegate(p, card) {
    var node = cardNode('delegate');
    node.appendChild(el('p', 'card-title', '委托确认'));
    if (p.spec_uid) node.dataset.specUid = p.spec_uid;
    var tk = p.ticker || {};
    var tkLabel = typeof tk === 'object' ? (tk.name || '') : (tk || '');
    node.appendChild(el('p', null, '监的是：' + tkLabel));
    var trg = p.trigger || {};
    var wrap = el('div', 'spec-fields');
    var rows = [
      ['盯什么', trg.scope || '公告与新闻'],
      ['何时查', trg.schedule || '交易日每小时'],
      ['怎么通知', trg.notify || '动态页 + 简报'],
    ];
    rows.forEach(function (r) {
      var row = el('div', 'field-row');
      row.appendChild(el('span', 'field-name', r[0]));
      row.appendChild(el('span', 'field-value', r[1]));
      wrap.appendChild(row);
    });
    if ((trg.keywords || []).length) {
      var kwRow = el('div', 'field-row');
      kwRow.appendChild(el('span', 'field-name', '触发词表'));
      var chips = el('div', 'chips');
      trg.keywords.forEach(function (kw) { chips.appendChild(el('span', 'chip', kw)); });
      kwRow.appendChild(chips);
      wrap.appendChild(kwRow);
    }
    node.appendChild(wrap);
    var dHint = el('p', null, '');
    dHint.style.cssText = 'font-size:12px;color:#5c6675;margin:10px 0 4px;line-height:1.5;';
    dHint.innerHTML = '确认后知音将<b>持续替你盯盘</b>，检查结果以简报形式出现在动态页。以上设定可修改，下次检查生效。';
    node.appendChild(dHint);
    if (p.freq_cap) node.appendChild(el('p', 'card-footer', p.freq_cap));
    var btnWrap = el('div', 'spec-actions');
    var confirmBtn = el('button', 'btn btn--primary', '确认委托'); confirmBtn.type = 'button';
    confirmBtn.addEventListener('click', function () {
      var uid = p.spec_uid || (card && card.spec_uid);
      confirmBtn.textContent = '创建中…'; confirmBtn.disabled = true;
      postJSON('/api/spec/' + uid + '/confirm').then(function (res) {
        var d = dataOf(res);
        node.appendChild(el('p', 'card-footer', '✅ 已开始值守，首次检查结果稍后在动态页可查'));
        confirmBtn.remove();
      }).catch(function (e) { confirmBtn.textContent = '失败：' + (e.message || ''); confirmBtn.disabled = false; });
    });
    btnWrap.appendChild(confirmBtn);
    node.appendChild(btnWrap);
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
    memory_note: function (p, card) {
      var node = cardNode('clarify');
      node.appendChild(noteHead('需要你确认', '澄清', 'source'));
      node.appendChild(el('p', null, '这条偏好要记住吗'));
      var actions = el('div', 'clarify-actions');
      var cid = p.clarify_id || (card && card.clarify_id);
      var opts = [['记住','granted'],['仅本次','session_only'],['别记','denied']];
      opts.forEach(function (o) {
        var b = el('button', 'btn btn--ghost', o[0]); b.type = 'button';
        b.addEventListener('click', function () {
          var fields = p.fields || (card && card.fields) || [];
          fields.forEach(function (f) {
            postJSON('/api/clarify/' + cid + '/memory', {field_key: f.field_key, state: o[1]}).catch(function(){});
          });
          node.appendChild(el('p', 'card-footer', '已选择：' + o[0]));
          actions.remove();
        });
        actions.appendChild(b);
      });
      node.appendChild(actions);
      return node;
    },
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
        if (TERMINAL[String(task.state || '').toUpperCase()]) stop();
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
