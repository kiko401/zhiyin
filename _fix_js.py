# -*- coding: utf-8 -*-
"""app.js 修复补丁：payloadOf/renderSpec/renderWork/renderAnswer/renderBriefing"""
import re

p = 'app/static/app.js'
s = open(p, encoding='utf-8').read()

# 1) payloadOf
s = s.replace(
    "function payloadOf(card) { return (card && (card.payload || card.data)) || {}; }",
    """function payloadOf(card) {
    if (card && card.payload) return card.payload;
    if (card && card.data) return card.data;
    return card || {};
  }""")

# 2) pollTask state
s = s.replace(
    "if (TERMINAL[String(task.status || '').toUpperCase()]) stop();",
    "if (TERMINAL[String(task.state || '').toUpperCase()]) stop();")

# 3) renderSpec
old_spec = re.search(
    r'function renderSpec\(p\) \{.*?\n  \}',
    s, re.DOTALL)
if old_spec:
    new_spec = """function renderSpec(p, card) {
    var node = cardNode('spec');
    node.appendChild(el('p', 'card-title', '研究规格'));
    if (p.spec_uid) node.dataset.specUid = p.spec_uid;
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
          });
        }
      }).catch(function (e) { confirmBtn.textContent = '确认失败：' + (e.message || '重试'); confirmBtn.disabled = false; busy = false; });
    });
    var skipBtn = el('button', 'btn btn--ghost', '本次不使用画像'); skipBtn.type = 'button';
    btnWrap.appendChild(confirmBtn); btnWrap.appendChild(skipBtn);
    node.appendChild(btnWrap);
    return node;
  }"""
    s = s[:old_spec.start()] + new_spec + s[old_spec.end():]
    print("renderSpec replaced")

# 4) renderWork
old_work = re.search(r'function renderWork\(p\) \{.*?\n  \}', s, re.DOTALL)
if old_work:
    new_work = """function renderWork(p) {
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
    if (p.task_uid && !TERMINAL[String(p.state || '').toUpperCase()]) pollTask(p.task_uid, function (task) {
      var stMap = {DELIVERED:'已交付',DEGRADED:'已交付',FAILED:'排队',PLANNING:'规划',FETCHING:'取数',VERIFYING:'校验',ASSEMBLING:'组装'};
      var newBar = stageBar(stMap[task.state] || '排队');
      var old = node.querySelector('.stage-bar');
      if (old) node.replaceChild(newBar, old);
      if ((task.state === 'DELIVERED' || task.state === 'DEGRADED') && task.deliverable) {
        var dl = task.deliverable;
        var ansNode = renderAnswer({card_type:'answer',task_uid:p.task_uid,type:dl.type,summary:dl.summary,pros:dl.pros,cons:dl.cons,gaps:dl.gaps,statement:dl.statement,evidence_lines:dl.evidence_lines,citations:dl.citations,confidence:dl.confidence,fact_text:dl.fact_text,impact_text:dl.impact_text});
        node.parentNode.insertBefore(ansNode, node.nextSibling);
      }
    });
    return node;
  }"""
    s = s[:old_work.start()] + new_work + s[old_work.end():]
    print("renderWork replaced")

# 5) renderAnswer
old_ans = re.search(r'function renderAnswer\(.*?\n  \}', s, re.DOTALL)
new_ans = """function renderAnswer(p) {
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
      if (p.gaps) { details.appendChild(el('strong', null, '未覆盖与假设')); details.appendChild(el('p', null, p.gaps)); }
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
  }"""
if old_ans:
    s = s[:old_ans.start()] + new_ans + s[old_ans.end():]
    print("renderAnswer replaced")
else:
    # renderAnswer 不存在则插入到 renderBriefing 前
    idx = s.find('function renderBriefing(')
    if idx >= 0:
        s = s[:idx] + new_ans + '\n  ' + s[idx:]
        print("renderAnswer inserted")

# 6) renderBriefing
old_brf = re.search(r'function renderBriefing\(.*?\n  \}', s, re.DOTALL)
new_brf = """function renderBriefing(p) {
    var node = cardNode('briefing');
    node.appendChild(noteHead(p.headline || '值守简报', '简报', 'stage'));
    node.appendChild(el('p', null, p.fact_text || ''));
    if (p.impact_text) node.appendChild(el('p', 'card-impact', p.impact_text));
    return node;
  }"""
if old_brf:
    s = s[:old_brf.start()] + new_brf + s[old_brf.end():]
    print("renderBriefing replaced")

p.write_text(s, encoding='utf-8', newline='\n')
print("app.js patched, total lines:", s.count('\n'))
