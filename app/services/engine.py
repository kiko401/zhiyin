"""任务化执行引擎：一处引擎、五入口（PRD 2.12）。

状态机 QUEUED→PLANNING→FETCHING→VERIFYING→ASSEMBLING→DELIVERED / FAILED / DEGRADED；
每次转移与工具调用写 task_event；交付物回贴会话消息流。
"""
import asyncio
import json
import re
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from app.core import config
from app.core.db import SessionLocal
from app.core.security import incr_daily
from app.models import (Answer, EvidenceItem, Message, ResearchSpec, ResearchTask,
                        Session as ChatSession, TaskEvent, ToolCall)
from app.services import compliance
from app.tools import dossier, fuyao

_sem = asyncio.Semaphore(config.MAX_CONCURRENT_TASKS)
_running = 0

LAYER_OF_TOOL = {"snapshot": "fact", "kline": "fact", "valuation": "fact", "financials": "fact",
                 "limit_up": "env", "hot_list": "env", "breadth": "env", "capital": "env", "news": "cause"}

IFIND_TOOLS = {"news", "breadth", "capital", "policy", "cross_market"}

FACT_TOOL_OF_METRIC = (
    (("近", "区间", "60日", "最高价", "最低价"), "kline"),
    (("pe", "pb", "ps", "pcf", "市盈", "市净", "市销", "市现"), "valuation"),
    (("营收", "净利", "eps", "每股收益", "毛利"), "financials"),
    (("收盘", "最新价", "现价", "开盘", "最高", "最低", "成交量", "成交额", "涨", "跌"), "snapshot"),
)


def plan_steps(spec: dict) -> list[dict]:
    """证据蓝图：任务类型与规格 → 确定性工具步骤（非模型自由规划）。"""
    tt = spec.get("task_type")
    if tt == "fact_query":
        metric = str(spec.get("fields", {}).get("metric", {}).get("value", "")).lower()
        steps = []
        for keys, tool in FACT_TOOL_OF_METRIC:
            if any(k in metric for k in keys):
                steps.append({"tool": tool})
        return steps or [{"tool": "snapshot"}]
    if tt == "decision_support" or tt == "routine_review":
        return [{"tool": "snapshot"}, {"tool": "kline"}, {"tool": "valuation"},
                {"tool": "financials"}, {"tool": "news", "ifind": True}, {"tool": "breadth", "ifind": True}]
    if tt == "limit_up_review":
        return [{"tool": "limit_up"}, {"tool": "hot_list"}, {"tool": "snapshot"}, {"tool": "news", "ifind": True}]
    if tt == "sector_review":
        return [{"tool": "hot_list"}, {"tool": "breadth", "ifind": True}, {"tool": "capital", "ifind": True}]
    if tt == "capital_perspective":
        return [{"tool": "snapshot"}, {"tool": "capital", "ifind": True}, {"tool": "news", "ifind": True}]
    if tt == "standing_watch":
        return [{"tool": "snapshot"}, {"tool": "limit_up"}, {"tool": "hot_list"}, {"tool": "news", "ifind": True}]
    return []  # knowledge 不取数


async def _event(db, task_id: int, etype: str, stage: str | None = None, payload=None, elapsed_ms=None):
    db.add(TaskEvent(task_id=task_id, event_type=etype, stage=stage, payload=payload, elapsed_ms=elapsed_ms))


async def create_task(user_id: int, session_id: int | None, spec_row: ResearchSpec,
                      standing_task_id: int | None = None, idempotency_key: str | None = None,
                      auto_confirmed: bool = False, check_quota: bool = False) -> ResearchTask:
    """创建任务实例并启动执行协程。202 语义由调用方返回。"""
    quota = await incr_daily(f"task_research:{user_id}")
    if quota > config.DAILY_RESEARCH_QUOTA:
        from app.core.responses import ApiError
        raise ApiError(42901, "今日研究任务数已达上限", status_code=429)

    async with SessionLocal() as db:
        task = ResearchTask(
            task_uid=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            standing_task_id=standing_task_id,
            spec_id=spec_row.id,
            spec_version=spec_row.version,
            task_type=spec_row.task_type,
            state="QUEUED",
            blueprint="、".join(s["tool"] for s in plan_steps(spec_row.spec)),
            idempotency_key=idempotency_key,
        )
        db.add(task)
        if auto_confirmed:
            spec_row.status = "confirmed"
        await db.commit()
        await db.refresh(task)

    asyncio.create_task(_run(task.task_uid))
    return task


async def _exec_step(step: dict, ticker: str | None) -> dict:
    """执行单个工具步骤；失败走底稿兜底；iFinD 缺失记为证据缺口（E10）。"""
    tool = step["tool"]
    if step.get("ifind"):
        return {"tool": tool, "gap": "iFinD 资讯源未接入（环境与归因层缺口）", "layer": LAYER_OF_TOOL.get(tool, "env")}
    if not ticker:
        return {"tool": tool, "gap": "无标的，跳过取数", "layer": LAYER_OF_TOOL.get(tool, "fact")}
    try:
        if tool == "snapshot":
            d = await fuyao.snapshot([ticker])
            return {"tool": tool, "layer": "fact", "source": "fuyao", "as_of": d["as_of"],
                    "unit": d["unit"], "caliber": d["caliber"], "payload": d["items"].get(ticker)}
        if tool == "kline":
            d = await fuyao.kline(ticker)
            return {"tool": tool, "layer": "fact", "source": "fuyao", "as_of": d["as_of"],
                    "unit": d["unit"], "caliber": d["caliber"], "payload": {"bars": d["bars"]}}
        if tool == "valuation":
            d = await fuyao.valuations([ticker])
            return {"tool": tool, "layer": "fact", "source": "fuyao", "as_of": d["as_of"],
                    "unit": d["unit"], "caliber": d["caliber"], "payload": d["items"].get(ticker)}
        if tool == "financials":
            d = await fuyao.income_statements(ticker)
            return {"tool": tool, "layer": "fact", "source": "fuyao", "as_of": None,
                    "unit": d["unit"], "caliber": d["caliber"],
                    "payload": {"items": d["items"][:4], "latest_yoy_pct": d["latest_yoy_pct"]}}
        if tool == "limit_up":
            d = await fuyao.limit_up_pool()
            return {"tool": tool, "layer": "env", "source": "fuyao", "as_of": d["as_of"],
                    "unit": d["unit"], "caliber": d["caliber"], "payload": {"top": d["items"][:20]}}
        if tool == "hot_list":
            d = await fuyao.hot_stock_list()
            return {"tool": tool, "layer": "env", "source": "fuyao", "as_of": d["as_of"],
                    "unit": d["unit"], "caliber": d["caliber"], "payload": {"top": d["items"][:15]}}
    except Exception as e:
        fb = dossier.fallback(ticker, tool)
        if fb:
            return {"tool": tool, "layer": LAYER_OF_TOOL.get(tool, "fact"), "source": "dossier",
                    "as_of": fb.get("as_of"), "unit": fb.get("unit"), "caliber": fb.get("caliber"),
                    "payload": {k: v for k, v in fb.items() if not k.startswith("__")}}
        return {"tool": tool, "layer": LAYER_OF_TOOL.get(tool, "fact"), "error": str(e)[:120]}
    return {"tool": tool, "gap": f"工具 {tool} 未实现"}


TOOL_LABELS = {"snapshot": "行情快照", "kline": "日K行情", "valuation": "估值指标", "financials": "财务报表",
               "limit_up": "涨停池", "hot_list": "热门股榜", "news": "资讯", "capital": "资金流",
               "breadth": "市场宽度", "index": "指数行情"}

_KV_LABELS = {"last_price": "最新价", "price_change": "涨跌", "price_change_rate": "涨跌幅",
              "volume": "成交量", "turnover": "成交额", "close_price": "收盘", "open_price": "开盘",
              "high_price": "最高", "low_price": "最低", "pe_ttm": "PE（TTM）", "pe_mrq": "PE（MRQ）",
              "pb_mrq": "PB（MRQ）", "ps_ttm": "PS（TTM）", "pcf_ttm": "PCF（TTM）",
              "operating_income": "营业总收入", "net_profit": "净利润", "net_profit_atsopc": "归母净利润",
              "basic_eps": "基本每股收益"}


def _fmt_num(v) -> str:
    if isinstance(v, (int, float)):
        a = abs(v)
        if a >= 1e8:
            return f"{v / 1e8:.2f} 亿"
        if a >= 1e4:
            return f"{v / 1e4:.2f} 万"
        return f"{v:g}"
    return str(v)


def _evidence_item(e: dict) -> dict:
    """证据 → 结构化摘要（确定性拼装，非模型生成），供降级/直答卡渲染。"""
    item = {"tool": e.get("tool"), "tool_label": TOOL_LABELS.get(e.get("tool"), e.get("tool")),
            "source": e.get("source"), "as_of": e.get("as_of"), "unit": e.get("unit"),
            "caliber": e.get("caliber"), "summary": "", "kv": []}
    if e.get("gap"):
        item["summary"] = e["gap"]
        return item
    if e.get("error"):
        item["summary"] = f"取数失败：{e['error']}"
        return item
    p = e.get("payload") or {}
    t = e.get("tool")
    if t == "kline" and isinstance(p.get("bars"), list) and p["bars"]:
        bars = p["bars"]
        closes = [b.get("close_price") for b in bars if isinstance(b.get("close_price"), (int, float))]
        highs = [b.get("high_price") for b in bars if isinstance(b.get("high_price"), (int, float))]
        lows = [b.get("low_price") for b in bars if isinstance(b.get("low_price"), (int, float))]
        item["summary"] = f"共 {len(bars)} 根日K"
        kv = []
        if closes:
            kv.append(["最新收盘", _fmt_num(closes[0])])
        if highs:
            kv.append(["区间最高", _fmt_num(max(highs))])
        if lows:
            kv.append(["区间最低", _fmt_num(min(lows))])
        item["kv"] = kv
    elif t == "financials" and isinstance(p.get("items"), list) and p["items"]:
        it0 = p["items"][0]
        period = f"{it0.get('fiscal_year', '')}{it0.get('fiscal_period', '')}"
        item["summary"] = f"最新报告期 {period}（累计口径）" if period else "利润表报告期序列"
        kv = []
        for k in ("operating_income", "net_profit", "net_profit_atsopc", "basic_eps"):
            if it0.get(k) is not None:
                kv.append([_KV_LABELS[k], _fmt_num(it0[k])])
        if p.get("latest_yoy_pct") is not None:
            kv.append(["最新单季营收同比", f"{p['latest_yoy_pct']}%"])
        item["kv"] = kv
    elif t in ("limit_up", "hot_list") and isinstance(p.get("top"), list):
        names = [str(x.get("name") or x.get("stock_name") or "?") for x in p["top"][:3]]
        item["summary"] = f"共 {len(p['top'])} 只" + ("：" + "、".join(names) if names else "")
    elif isinstance(p, dict):
        item["kv"] = [[_KV_LABELS[k], _fmt_num(v)] for k, v in p.items()
                      if k in _KV_LABELS and isinstance(v, (int, float))]
        item["summary"] = "关键数据如下" if item["kv"] else ""
    if not item["summary"]:
        item["summary"] = "原始数据见展开"
    return item


def _num_tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def _verify(answer_text: str, evidence_dump: str) -> list[str]:
    """数字—证据比对：回答中的数字须能在证据中找到（忽略精度差异）。"""
    bad = []
    for tok in _num_tokens(answer_text):
        try:
            variants = {tok, format(float(tok), "g"), str(int(float(tok)))}
        except ValueError:
            variants = {tok}
        if not any(v in evidence_dump for v in variants):
            bad.append(tok)
    return bad


def _verifiable_text(content: dict) -> str:
    """仅取模型生成的叙述文本参与校验；引用序号与确定性证据摘要不参与比对。"""
    skip = ("citations", "type", "evidence_items", "evidence_lines", "evidence", "note")
    c = {k: v for k, v in content.items() if k not in skip}
    return json.dumps(c, ensure_ascii=False, default=str)


def _confidence(spec: dict, evidences: list) -> str:
    # 口径默认声明不计入假设；影响方向字段的假设才降档
    driver = [k for k in spec.get("fields", {}) if k in ("ticker", "time_horizon", "risk_context")]
    if any(spec["fields"][k].get("resolved_by") == "assumption" for k in driver):
        return "low"
    fact_ok = [e for e in evidences if e.get("layer") == "fact" and not e.get("gap") and not e.get("error")]
    if spec.get("terms"):
        return "mid"
    if fact_ok and not any(e.get("gap") for e in evidences):
        return "high"
    return "mid"


async def _generate(task_row, spec: dict, evidences: list, question: str | None) -> dict:
    """ASSEMBLING：按回答形态分级生成（PRD 2.7）。"""
    tt = spec.get("task_type")
    clean = [e for e in evidences if not e.get("gap") and not e.get("error")]
    dump = json.dumps(clean, ensure_ascii=False, default=str)


    if tt == "standing_watch":
        # 简报四件套：事实段（≤120字带角标）+ 中性影响一句；模板组装不经模型（触发是规则、行文求稳）
        snap = next((e for e in clean if e["tool"] == "snapshot"), None)
        lu = next((e for e in clean if e["tool"] == "limit_up"), None)
        tk = spec.get("fields", {}).get("ticker", {}).get("value", {})
        cites, facts = [], []
        n = 0
        if snap:
            n += 1
            it = snap.get("payload") or {}
            facts.append(f"最新价 {it.get('last_price')} 元（涨跌 {it.get('price_change_ratio_pct')}%）[{n}]")
            cites.append({"n": n, "source": snap.get("source"), "as_of": snap.get("as_of"),
                          "unit": snap.get("unit"), "caliber": snap.get("caliber"), "tool": "snapshot"})
        if lu:
            n += 1
            top = (lu.get("payload") or {}).get("top", [])
            names = "、".join(i.get("name", "") for i in top[:3])
            facts.append(f"今日涨停池 {len(top)} 家（连板前列：{names}）[{n}]")
            cites.append({"n": n, "source": lu.get("source"), "as_of": lu.get("as_of"),
                          "unit": lu.get("unit"), "caliber": lu.get("caliber"), "tool": "limit_up"})
        gaps = [e.get("gap") for e in evidences if e.get("gap")]
        if gaps:
            facts.append(f"缺口：{'；'.join(gaps)}")
        content = {
            "type": "briefing",
            "headline": f"{tk.get('name', '')}盯盘检查",
            "fact_text": "；".join(facts)[:120],
            "impact_text": "以上为盘面事实记录，不构成操作建议",
            "evidence": cites,
            "gaps_note": "；".join(gaps),
        }
        return content
    if tt == "fact_query":
        metric = str(spec.get("fields", {}).get("metric", {}).get("value", ""))
        caliber = str(spec.get("fields", {}).get("caliber", {}).get("value", ""))
        tk = spec.get("fields", {}).get("ticker", {}).get("value", {})
        cites = []
        for i, e in enumerate(clean, 1):
            cites.append({"n": i, "source": e.get("source"), "as_of": e.get("as_of"),
                          "unit": e.get("unit"), "caliber": e.get("caliber"), "tool": e.get("tool")})
        content = {
            "type": "fact_card",
            "statement": f"{tk.get('name')}（{tk.get('code')}）{metric}。口径：{caliber}；数据均带来源与时点。",
            "evidence_items": [_evidence_item(e) for e in clean], "citations": cites,
        }
        return content

    if tt == "knowledge":
        sys_p = ("你是投研助手知音的知识模块。开头标注「以下为知识性内容，未接入实时数据」，"
                 "结合通用知识解释概念或规则，不构成投资建议，不预测涨跌。"
                 '输出 JSON：{"summary":"一句话概括","body":"正文，≤300字","gaps":"未接入实时数据，请以官方披露为准"}')
        user = f"用户问题：{question or spec.get('fields', {}).get('ticker', {}).get('value', {}).get('name', '')}"
        out = await llm_json(sys_p, user, task_row)
        out["type"] = "knowledge_card"
        out["citations"] = []
        return out

    gaps = [e.get("gap") for e in evidences if e.get("gap")]
    sys_p = (
        "你是投研助手知音的回答生成模块。严格规则："
        "1) 数字与事实只能来自证据块，每个数字后用[n]标注对应证据编号；"
        "2) 证据没有的信息不得编造，写入 gaps 段；"
        "3) 禁用词：涨停预测、建议买入、目标价、稳赚、必涨；不输出买卖指令与涨跌预测；"
        '4) 输出 JSON：{"summary":"不超过80字的结论摘要","pros":["事实与正方论点，每条含[n]"],'
        '"cons":["反方论点与风险，每条含[n]"],"gaps":["未覆盖与假设，数组，每条独立一项，1~3条，每条不超过60字"]}。'
        "语气中性，仅供参考。"
    )
    blocks = []
    cites = []
    for i, e in enumerate(clean, 1):
        blocks.append(f"[{i}] ({e['tool']}，时点 {e.get('as_of')}，单位 {e.get('unit')}，口径 {e.get('caliber')}) "
                      + json.dumps(e.get("payload"), ensure_ascii=False, default=str)[:600])
        cites.append({"n": i, "source": e.get("source"), "as_of": e.get("as_of"),
                      "unit": e.get("unit"), "caliber": e.get("caliber"), "tool": e.get("tool")})
    gap_note = "已知缺口：" + "；".join(gaps) if gaps else ""
    tk = spec.get("fields", {}).get("ticker", {}).get("value", {})
    user = (f"用户问题：{question or '对该标的的研究'}\n标的：{tk.get('name')}（{tk.get('code')}）\n"
            f"周期：{spec.get('fields', {}).get('time_horizon', {}).get('value', '')}；"
            f"处境：{spec.get('fields', {}).get('risk_context', {}).get('value', '')}\n"
            f"{gap_note}\n证据块：\n" + "\n".join(blocks))

    content = await llm_json(sys_p, user, task_row)
    g = content.get("gaps")
    if isinstance(g, list):
        content["gaps"] = [str(x).strip() for x in g if str(x).strip()]
    elif isinstance(g, str) and g.strip():
        content["gaps"] = [g.strip()]
    else:
        content["gaps"] = []
    content["type"] = "four_part"
    content["citations"] = cites
    return content


async def llm_json(sys_p: str, user: str, task_row) -> dict:
    from app.llm import client as llm

    try:
        return await llm.chat_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user}],
            purpose="answer", task_id=task_row.id, max_tokens=4000,
        )
    except llm.LlmBadJson:
        return await llm.chat_json(
            [{"role": "system", "content": sys_p + " 上次输出不是合法JSON。"},
             {"role": "user", "content": user}],
            purpose="answer", task_id=task_row.id, max_tokens=4000,
        )


async def _run(task_uid: str):
    global _running
    async with _sem:
        _running += 1
        try:
            await _execute(task_uid)
        except Exception as e:  # 兜底：不静默失败
            async with SessionLocal() as db:
                row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
                t = row.scalar_one_or_none()
                if t and t.state not in ("DELIVERED",):
                    t.state = "FAILED"
                    t.error_note = str(e)[:200]
                    await _event(db, t.id, "stage_end", stage="FAILED", payload={"error": str(e)[:200]})
                    await db.commit()
        finally:
            _running -= 1


async def _execute(task_uid: str):
    t0 = time.monotonic()
    async with SessionLocal() as db:
        row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        task = row.scalar_one_or_none()
        spec_row = await db.get(ResearchSpec, task.spec_id)
        spec = spec_row.spec
        ticker_v = spec.get("fields", {}).get("ticker", {}).get("value")
        ticker = ticker_v.get("code") if isinstance(ticker_v, dict) else None
        question = spec.get("question")

        task.state = "PLANNING"
        task.started_at = datetime.now()
        steps = plan_steps(spec)
        await _event(db, task.id, "stage_start", stage="PLANNING")
        await _event(db, task.id, "plan_complete", stage="PLANNING",
                     payload={"steps": [s["tool"] for s in steps], "reason": "证据蓝图确定性映射"})
        task.state = "FETCHING"
        await _event(db, task.id, "stage_start", stage="FETCHING")
        await db.commit()
        task_id = task.id

    # 并行取数（信号量内）
    results = await asyncio.gather(*[_exec_step(s, ticker) for s in steps])

    async with SessionLocal() as db:
        row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        task = row.scalar_one()
        evidences = []
        for r in results:
            db.add(ToolCall(task_id=task_id, tool_name=r["tool"],
                            source=r.get("source") or ("ifind" if r.get("ifind") else "engine"),
                            input_digest=ticker or "", output_count=0 if (r.get("gap") or r.get("error")) else 1,
                            status="error" if r.get("error") else ("empty" if r.get("gap") else "ok"),
                            latency_ms=None))
            if not r.get("error") and not r.get("gap") and r.get("payload") is not None:
                ev = EvidenceItem(task_id=task_id, layer=r.get("layer", "fact"), source=r.get("source"),
                                  as_of=str(r.get("as_of")), unit=r.get("unit"), caliber=r.get("caliber"),
                                  payload={"tool": r["tool"], "data": r.get("payload")})
                db.add(ev)
                evidences.append({**r, "evidence_id": ev.id})
            else:
                evidences.append(r)
        await _event(db, task_id, "stage_end", stage="FETCHING",
                     payload={"ok": sum(1 for e in evidences if not e.get("gap") and not e.get("error")),
                              "gap": sum(1 for e in evidences if e.get("gap")),
                              "error": sum(1 for e in evidences if e.get("error"))})
        task.state = "VERIFYING"
        await _event(db, task.id, "stage_start", stage="VERIFYING")
        await db.commit()

    # VERIFYING：证据合理性（事实层至少一条，或 knowledge）
    fact_ok = any(e.get("layer") == "fact" and not e.get("gap") and not e.get("error") for e in evidences)
    if spec.get("task_type") != "knowledge" and not fact_ok:
        async with SessionLocal() as db:
            row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
            task = row.scalar_one()
            task.state = "DEGRADED"
            task.finished_at = datetime.now()
            await _event(db, task.id, "verify_fail", stage="VERIFYING", payload={"reason": "事实层证据不可用"})
            content = {"type": "evidence_card", "statement": "数据源暂不可用，以下为可用证据与缺口说明",
                       "evidence_items": [_evidence_item(e) for e in evidences], "citations": []}
            db.add(Answer(task_id=task.id, answer_uid=str(uuid.uuid4()), content=content, confidence="low"))
            await _event(db, task.id, "deliver", stage="DEGRADED")
            await _deliver_to_session(db, task, content)
            await db.commit()
        return

    async with SessionLocal() as db:
        row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        task = row.scalar_one()
        task.state = "ASSEMBLING"
        await _event(db, task.id, "verify_pass", stage="VERIFYING")
        await _event(db, task.id, "stage_start", stage="ASSEMBLING")
        await db.commit()

    # ASSEMBLING：生成 + 输出校验（数字-证据比对 + 红线扫描），失败重写一次，再失败 DEGRADED
    try:
        content = await _generate(task, spec, evidences, question)
        text_dump = _verifiable_text(content)
        clean_dump = json.dumps([e for e in evidences if not e.get("gap")], ensure_ascii=False, default=str)
        has_clean = any(not e.get("gap") and not e.get("error") for e in evidences)
        bad = _verify(text_dump, clean_dump) if has_clean else []  # 无事实证据（如知识类）时跳过数字比对
        if bad or compliance.scan_redline(text_dump):
            content = await _generate(task, spec, evidences, question)  # 重写一次
            text_dump = _verifiable_text(content)
            bad = _verify(text_dump, clean_dump)
            if bad or compliance.scan_redline(text_dump):
                raise ValueError(f"输出校验未通过：数字失源 {bad[:5]}")
        degraded = False
    except Exception as e:  # 模型故障或校验失败 → E1 证据卡
        content = {"type": "evidence_card", "statement": "AI 分析暂不可用，以下为可用证据数据",
                   "evidence_items": [_evidence_item(e) for e in evidences if not e.get("gap")],
                   "citations": [], "note": str(e)[:120]}
        degraded = True

    async with SessionLocal() as db:
        row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        task = row.scalar_one()
        task.state = "DEGRADED" if degraded else "DELIVERED"
        task.finished_at = datetime.now()
        elapsed = int((time.monotonic() - t0) * 1000)
        conf = _confidence(spec, evidences)
        db.add(Answer(task_id=task.id, answer_uid=str(uuid.uuid4()), content=content, confidence=conf))
        if content.get("type") == "briefing" and task.standing_task_id:
            # 频控：同任务当日已有简报则不入流（宁缺毋假）
            from app.models import Briefing

            brows = await db.execute(select(Briefing).where(
                Briefing.standing_task_id == task.standing_task_id,
                Briefing.status == "published"))
            today = datetime.now().isoformat()[:10]
            today_count = sum(1 for b in brows.scalars() if str(b.created_at)[:10] == today)
            if today_count < 1:
                db.add(Briefing(briefing_uid=str(uuid.uuid4()), standing_task_id=task.standing_task_id,
                                task_id=task.id, headline=content.get("headline"),
                                fact_text=content.get("fact_text", ""),
                                impact_text=content.get("impact_text"),
                                evidence=content.get("evidence"), status="published"))
        await _event(db, task.id, "deliver", stage=task.state, elapsed_ms=elapsed)
        await _deliver_to_session(db, task, content)
        await db.commit()


async def _deliver_to_session(db, task: ResearchTask, content: dict) -> None:
    """交付物回贴契约：回答落会话消息流，会话转 ANSWERED。"""
    if not task.session_id:
        return
    db.add(Message(session_id=task.session_id, role="system", card_type="answer",
                   content={"card_type": "answer", "task_uid": task.task_uid, **content}))
    row = await db.execute(select(ChatSession).where(ChatSession.id == task.session_id))
    s = row.scalar_one_or_none()
    if s:
        s.state = "ANSWERED"


async def get_task_view(task_uid: str, user_id: int) -> dict | None:
    from app.services import spec_service

    async with SessionLocal() as db:
        row = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        t = row.scalar_one_or_none()
        if not t or t.user_id != user_id:
            return None
        tools = await db.execute(select(ToolCall).where(ToolCall.task_id == t.id))
        ans_row = await db.execute(select(Answer).where(Answer.task_id == t.id).order_by(Answer.id.desc()).limit(1))
        ans = ans_row.scalar_one_or_none()
        deliverable = None
        if t.state in ("DELIVERED", "DEGRADED") and ans:
            deliverable = {"answer_uid": ans.answer_uid, "confidence": ans.confidence, **ans.content}
        return {
            "task_uid": t.task_uid, "state": t.state, "task_type": t.task_type,
            "blueprint": t.blueprint, "error_note": t.error_note,
            "tools": [{"tool": x.tool_name, "status": x.status, "source": x.source} for x in tools.scalars()],
            "created_at": str(t.created_at), "finished_at": str(t.finished_at) if t.finished_at else None,
            "spec_uid": (await spec_service.get_uid_by_id(t.spec_id)),
            "deliverable": deliverable,
        }
