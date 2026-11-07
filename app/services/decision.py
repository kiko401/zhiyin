"""Clarify-or-Delegate 决策器（D1–D11，PRD 2.4）。

三层顺序：词典层（确定性消解）→ 规则层（红线/清晰题）→ 大模型层（意图与缺失维度）。
决策只产出卡片动作，不取数；执行属任务引擎（M3）。
"""
from app.core import config
from app.llm import client as llm
from app.services import compliance, profile as profile_svc
from app.services import lexicon as lexicon_svc
from app.tools import fuyao

# D2 可直答指标 →（证据工具， 默认口径）
FACT_METRICS = {
    "收盘价": ("snapshot", "最新行情快照"),
    "最新价": ("snapshot", "最新行情快照"),
    "现价": ("snapshot", "最新行情快照"),
    "涨跌幅": ("snapshot", "当日涨跌幅"),
    "涨了多少": ("snapshot", "当日涨跌幅"),
    "跌了多少": ("snapshot", "当日涨跌幅"),
    "开盘价": ("snapshot", "当日开盘"),
    "最高价": ("snapshot", "当日最高"),
    "最低价": ("snapshot", "当日最低"),
    "成交量": ("snapshot", "当日成交量（股）"),
    "成交额": ("snapshot", "当日成交额（元）"),
    "pe-ttm": ("valuation", "PE-TTM（滚动十二个月）"),
    "pe": ("valuation", "PE-TTM（滚动十二个月）"),
    "pb": ("valuation", "PB-MRQ（最近报告期净资产）"),
    "ps": ("valuation", "PS-TTM"),
    "pcf": ("valuation", "PCF-TTM"),
    "市盈率": ("valuation", "PE-TTM（滚动十二个月）"),
    "市净率": ("valuation", "PB-MRQ"),
    "营业收入": ("financials", "最新已披露报告期（累计口径）"),
    "营收": ("financials", "最新已披露报告期（累计口径）"),
    "归母净利润": ("financials", "最新已披露报告期（累计口径）"),
    "净利润": ("financials", "最新已披露报告期（累计口径）"),
    "每股收益": ("financials", "最新已披露报告期"),
    "eps": ("financials", "最新已披露报告期"),
    "毛利率": ("financials", "最新已披露报告期，毛利=营收-营业成本"),
}

# A3 口径歧义触发词：出现即要求澄清（除非题面已带报告期/时间范围）
PERIOD_HINTS = ("年报", "半年报", "中报", "季报", "q1", "q2", "q3", "q4", "一季度", "二季度", "三季度", "四季度", "最新", "今日", "今天", "当日", "年初至今", "近一")

CLARIFY_TEMPLATES = {
    "A4": {
        "question": "你关注的持有周期是哪种？这决定研究的口径与侧重。",
        "options": ["短线（数日）", "波段（数周）", "中长线（数月以上）"],
        "field": "time_horizon",
    },
    "A5": {
        "question": "你当前的处境更接近哪种？答案会更有针对性。",
        "options": ["被套中", "浮盈中", "空仓观察"],
        "field": "risk_context",
    },
}

CALIBER_CLARIFY = {
    "financials": {
        "question": "业绩口径按哪个算？",
        "options": ["最新单季同比", "最新报告期累计", "指定报告期（请在补充里说明）"],
    },
    "snapshot": {
        "question": "涨跌按哪个时间范围算？",
        "options": ["当日", "近一月", "年初至今"],
    },
}

DELEGATE_DEFAULTS = {
    "scope": "公告与新闻",
    "keywords": ["减持", "质押", "业绩预告", "立案调查", "监管函"],
    "schedule": "交易日每小时",
    "notify": "动态页 + 简报",
}


def _detect_metric(text: str) -> tuple[str, tuple] | None:
    low = text.lower()
    for key in sorted(FACT_METRICS, key=len, reverse=True):
        if key in low:
            return key, FACT_METRICS[key]
    return None


def _has_period_hint(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in PERIOD_HINTS)


async def _llm_intent(text: str, lex_notes: list, prof: dict) -> dict:
    """D6：意图分类与风险分级。LLM 不可用时走保守规则。"""
    if not config.LLM_ENABLED:
        lowered = text.lower()
        if any(w in text for w in ("盯", "提醒我", "有动静", "每天", "帮我盯着")):
            intent = "delegate"
        elif any(w in lowered for w in ("是什么", "怎么理解", "什么意思", "为什么")):
            intent = "knowledge"
        elif any(w in text for w in ("怎么办", "还能拿", "要不要", "怎么看", "适合")):
            intent = "decision_support"
        else:
            intent = "fact_query"
        return {"intent": intent, "risk_tier": 0, "tickers": [], "metrics": []}

    ctx = []
    if lex_notes:
        ctx.append("已消解术语：" + "；".join(f"{n['term']}={n['canonical']}" for n in lex_notes))
    if prof.get("time_horizon"):
        ctx.append(f"用户周期：{prof['time_horizon']}")
    if prof.get("risk_context"):
        ctx.append(f"用户处境：{prof['risk_context']}")
    system = (
        "你是投研助手的意图分析模块，只输出 JSON，不输出其他文字。"
        '输出：{"intent":"fact_query|knowledge|decision_support|delegate",'
        '"risk_tier":0,"tickers":["提到的A股标的原始名称"],"metrics":["提到的指标"],'
        '"delegate":{"scope":"公告与新闻","keywords":["减持"]}}。'
        "判定：请系统持续盯守或定时提醒→delegate（scope 取 公告与新闻/涨跌停梯队/价格阈值 之一，并给关键词建议）；"
        "问指标或行情数字→fact_query；问概念规则含义→knowledge；"
        "问怎么操作/还能拿吗/要不要/怎么看→decision_support。"
        "risk_tier：1=让系统预测具体涨跌或给出买卖指令或承诺收益；2=情绪化纠结（割肉/慌/死扛）；默认0。"
        "注意：持有类咨询（还能拿吗/要不要卖）是 decision_support 且 risk_tier=0，不是指令。"
        "示例：'新易盛还能拿吗'→decision_support,0；'茅台营收多少'→fact_query,0；"
        "'帮我决定明天买什么'→decision_support,1；'明天哪只股票能涨停'→decision_support,1；"
        "'恒瑞割肉还是死扛'→decision_support,2；"
        "'每天盘后帮我盯着新易盛的减持公告'→delegate,0。"
    )
    user = ("\n".join(ctx) + "\n" if ctx else "") + f"用户消息：{text}"
    try:
        data = await llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            purpose="intent",
            max_tokens=300,
        )
        return {
            "intent": data.get("intent", "decision_support"),
            "risk_tier": int(data.get("risk_tier") or 0),
            "tickers": [t for t in (data.get("tickers") or []) if t],
            "metrics": data.get("metrics") or [],
            "delegate": data.get("delegate") or {},
        }
    except llm.LlmBadJson:
        try:  # E2：非法 JSON 自动修复重试一次
            data = await llm.chat_json(
                [{"role": "system", "content": system + " 上次输出不是合法JSON，请严格输出JSON。"},
                 {"role": "user", "content": user}],
                purpose="intent", max_tokens=300,
            )
            return {
                "intent": data.get("intent", "decision_support"),
                "risk_tier": int(data.get("risk_tier") or 0),
                "tickers": [t for t in (data.get("tickers") or []) if t],
                "metrics": data.get("metrics") or [],
                "delegate": data.get("delegate") or {},
            }
        except Exception:
            pass
    except Exception:
        pass
    # 降级：保守走 decision_support（后续维度澄清兜底）
    return {"intent": "decision_support", "risk_tier": 0, "tickers": [], "metrics": [], "delegate": {}}


async def _resolve_tickers(raw_names: list, lex_map: dict, prof: dict, session_ticker: dict | None) -> dict:
    """返回 {"resolved": [{code,name,source}], "multi": [{name, candidates:[{code,name}]}], "pronoun": bool}"""
    resolved, multi = [], []
    pronoun = False
    watch = prof.get("watch_list") or []

    def _by_watch(name: str):
        # 仅接受带代码的条目；纯名称条目交给扶摇检索补代码
        for w in watch:
            if isinstance(w, dict) and w.get("name") == name and w.get("code"):
                return w
        return None

    for raw in raw_names:
        if not raw:
            continue
        if raw in ("它", "这只", "该股", "这波", "此股"):
            pronoun = True
            if session_ticker:
                resolved.append({**session_ticker, "source": "session"})
            continue
        if raw in lex_map:
            canon = lex_map[raw]
            name = canon.split("（")[0]
            code = canon.split("（")[1].rstrip("）") if "（" in canon else None
            resolved.append({"code": code, "name": name, "source": "lexicon"})
            continue
        w = _by_watch(raw)
        if w:
            resolved.append({"code": w.get("code"), "name": raw, "source": "profile"})
            continue
        try:
            items = await fuyao.search_ticker(raw, limit=3)
        except Exception:
            items = []
        if len(items) == 1:
            it = items[0]
            resolved.append({"code": it.get("thscode"), "name": it.get("name"), "source": "search"})
        elif len(items) > 1:
            multi.append({
                "name": raw,
                "candidates": [{"code": i.get("thscode"), "name": i.get("name")} for i in items],
            })
        # 零命中：不进 resolved，交由开放式追询
    return {"resolved": resolved, "multi": multi, "pronoun": pronoun}


def _clarify_card(clarify_id: int, ambiguity: str, question: str, options: list,
                  round_no: int, skippable: bool = True) -> dict:
    return {
        "card_type": "clarify",
        "clarify_id": clarify_id,
        "ambiguity": ambiguity,
        "question": question,
        "options": options,
        "round": round_no,
        "max_rounds": config.CLARIFY_MAX_ROUNDS,
        "skippable": skippable,
    }


def _boundary_card(text: str) -> dict:
    task_type = "limit_up_review" if "涨停" in text else "decision_support"
    return {
        "card_type": "boundary",
        "text": compliance.BOUNDARY_TEXT,
        "translate": {
            "name": "涨停复盘" if task_type == "limit_up_review" else " researched 框架".replace(" researched ", "研究"),
            "task_type": task_type,
        },
    }


async def decide(
    user_id: int,
    session_id: int | None,
    text: str,
    session_ticker: dict | None = None,
    answers: dict | None = None,
    round_no: int = 0,
    clarify_id: int | None = None,
) -> dict:
    """决策入口。answers 为本会话已澄清字段（A1→ticker 等）。"""
    answers = answers or {}
    # D1：硬红线先行，不消耗澄清轮次
    if compliance.scan_redline(text):
        return {"action": "boundary", "state": "BOUNDARY", "card": _boundary_card(text)}

    # 词典层（D3/D4）
    if config.LEXICON_ENABLED:
        lex = await lexicon_svc.resolve(text, user_id)
    else:
        lex = {"replaced_text": text, "notes": [], "map": {}}
    prof = await profile_svc.effective(user_id, answers) if config.PROFILE_ENABLED else {}

    # 大模型层（D6）
    info = await _llm_intent(text, lex["notes"], prof)
    if info.get("risk_tier") == 1:
        return {"action": "boundary", "state": "BOUNDARY", "card": _boundary_card(text)}

    # 标的解析（D10 真实候选）；LLM 未能识别时回落词典消解结果
    raw_names = list(info.get("tickers") or [])
    if not raw_names and lex["map"]:
        raw_names = list(lex["map"].keys())
    tick = await _resolve_tickers(raw_names, lex["map"], prof, session_ticker)
    if answers.get("ticker"):
        tick["resolved"].insert(0, {**answers["ticker"], "source": "clarify"})

    # 委托分流（D11）
    if info["intent"] == "delegate":
        ticker = tick["resolved"][0] if tick["resolved"] else None
        if tick["multi"]:
            m = tick["multi"][0]
            return {
                "action": "clarify", "state": "CLARIFY", "ambiguity": "A1",
                "card": _clarify_card(0, "A1", f"你指的是哪一只？", [c["name"] for c in m["candidates"]], round_no + 1),
                "candidates": m["candidates"], "text": text, "answers": answers,
            }
        d = info.get("delegate") or {}
        trigger = {
            "scope": d.get("scope") or DELEGATE_DEFAULTS["scope"],
            "keywords": d.get("keywords") or DELEGATE_DEFAULTS["keywords"],
            "schedule": DELEGATE_DEFAULTS["schedule"],
            "notify": DELEGATE_DEFAULTS["notify"],
        }
        from app.services import spec_service

        fields = {"ticker": {"value": ticker, "resolved_by": ticker["source"] if ticker else "assumption"}}
        row = await spec_service.save_spec(user_id, session_id, "standing_watch", fields,
                                           lex["notes"], info.get("risk_tier", 0), trigger=trigger)
        return {
            "action": "delegate", "state": "SPEC_REVIEW",
            "card": {
                "card_type": "delegate",
                "spec_uid": row.spec_uid,
                "ticker": ticker,
                "trigger": trigger,
                "freq_cap": "每日每标的 ≤ 1 条",
            },
        }

    ticker = tick["resolved"][0] if tick["resolved"] else None

    # 知识类：无标的、不取数
    if info["intent"] == "knowledge" and not ticker:
        spec = await _save_and_card(user_id, session_id, "knowledge", {}, lex["notes"], info.get("risk_tier", 0))
        return {"action": "spec", "state": "SPEC_REVIEW", "card": spec}

    # 无标的且需要标的：开放式追询（E3 零命中路径）
    if not ticker and info["intent"] in ("fact_query", "decision_support"):
        if round_no >= config.CLARIFY_MAX_ROUNDS:
            return await _assumption_spec(user_id, session_id, info, lex, text)
        return {
            "action": "clarify", "state": "CLARIFY", "ambiguity": "A1",
            "card": _clarify_card(0, "A1", "想研究哪只标的？可以直接说代码或名称。", [], round_no + 1, skippable=False),
            "candidates": [], "text": text, "answers": answers, "free_input": True,
        }

    # 标的多候选：真实候选澄清（D10）
    if tick["multi"]:
        m = tick["multi"][0]
        return {
            "action": "clarify", "state": "CLARIFY", "ambiguity": "A1",
            "card": _clarify_card(0, "A1", "你指的是哪一只？", [c["name"] for c in m["candidates"]], round_no + 1),
            "candidates": m["candidates"], "text": text, "answers": answers,
        }

    # D2：清晰事实题（标的唯一 + 指标明确 + 口径可声明/可默认声明）
    metric = _detect_metric(text)
    if info["intent"] == "fact_query" and ticker and metric:
        key, (tool, caliber) = metric
        if "最新" not in text and not _has_period_hint(text) and tool == "financials":
            if round_no < config.CLARIFY_MAX_ROUNDS:
                c = CALIBER_CLARIFY["financials"]
                return {
                    "action": "clarify", "state": "CLARIFY", "ambiguity": "A3",
                    "card": _clarify_card(0, "A3", c["question"], c["options"], round_no + 1),
                    "text": text, "answers": answers,
                }
        if tool == "snapshot" and ("涨" in text or "跌" in text) and not _has_period_hint(text):
            if round_no < config.CLARIFY_MAX_ROUNDS:
                c = CALIBER_CLARIFY["snapshot"]
                return {
                    "action": "clarify", "state": "CLARIFY", "ambiguity": "A3",
                    "card": _clarify_card(0, "A3", c["question"], c["options"], round_no + 1),
                    "text": text, "answers": answers,
                }
        fields = {
            "ticker": {"value": ticker, "resolved_by": ticker["source"]},
            "metric": {"value": key, "resolved_by": "clarify"},
            "caliber": {"value": caliber, "resolved_by": "assumption"},
        }
        spec = await _save_and_card(user_id, session_id, "fact_query", fields, lex["notes"], info.get("risk_tier", 0))
        return {"action": "direct", "state": "EXECUTING", "card": spec, "spec_uid": spec["spec_uid"]}

    # 决策支持：缺失维度澄清（D7/D8），两轮耗尽走显式假设（D9）
    if info["intent"] == "decision_support":
        missing = []
        if not prof.get("time_horizon"):
            missing.append("A4")
        if not prof.get("risk_context"):
            missing.append("A5")
        if missing and round_no < config.CLARIFY_MAX_ROUNDS:
            tpl = CLARIFY_TEMPLATES[missing[0]]
            return {
                "action": "clarify", "state": "CLARIFY", "ambiguity": missing[0],
                "card": _clarify_card(0, missing[0], tpl["question"], tpl["options"], round_no + 1),
                "text": text, "answers": answers,
            }
        fields = {
            "ticker": {"value": ticker, "resolved_by": ticker["source"] if ticker else "assumption"},
            "time_horizon": {
                "value": answers.get("time_horizon") or prof.get("time_horizon") or "波段（假设）",
                "resolved_by": "clarify" if answers.get("time_horizon") else ("profile" if prof.get("time_horizon") else "assumption"),
            },
            "risk_context": {
                "value": answers.get("risk_context") or prof.get("risk_context") or "未提供（按中性处境）",
                "resolved_by": "clarify" if answers.get("risk_context") else ("profile" if prof.get("risk_context") else "assumption"),
            },
        }
        spec = await _save_and_card(user_id, session_id, "decision_support", fields, lex["notes"], info.get("risk_tier", 0))
        return {"action": "spec", "state": "SPEC_REVIEW", "card": spec,
                "memory_fields": _memory_fields(answers)}

    # 兜底：按决策支持框架处理
    fields = {
        "ticker": {"value": ticker, "resolved_by": ticker["source"] if ticker else "assumption"},
        "time_horizon": {"value": prof.get("time_horizon") or "波段（假设）", "resolved_by": "profile" if prof.get("time_horizon") else "assumption"},
    }
    spec = await _save_and_card(user_id, session_id, "decision_support", fields, lex["notes"], info.get("risk_tier", 0))
    return {"action": "spec", "state": "SPEC_REVIEW", "card": spec, "memory_fields": _memory_fields(answers)}


def _memory_fields(answers: dict) -> list:
    out = []
    label = {"time_horizon": "周期", "risk_context": "处境", "caliber": "口径"}
    for key in ("time_horizon", "risk_context"):
        if answers.get(key):
            out.append({"field_key": key, "label": label[key], "value": answers[key]})
    return out


async def _assumption_spec(user_id, session_id, info, lex, text):
    """D9 兜底：按显式假设作答的规格。"""
    fields = {
        "time_horizon": {"value": "波段（假设，未确认）", "resolved_by": "assumption"},
        "risk_context": {"value": "未提供（按中性处境）", "resolved_by": "assumption"},
    }
    spec = await _save_and_card(user_id, session_id, info.get("intent", "decision_support"), fields, lex["notes"], 0)
    return {"action": "spec", "state": "SPEC_REVIEW", "card": spec}


async def _save_and_card(user_id, session_id, task_type, fields, terms, risk_tier) -> dict:
    from app.services import spec_service

    row = await spec_service.save_spec(user_id, session_id, task_type, fields, terms, risk_tier)
    spec = row.spec
    field_rows = []
    for key, val in spec["fields"].items():
        display = val["value"]
        if isinstance(display, dict):
            display = f"{display.get('name')}（{display.get('code')}）" if display.get("code") else display.get("name")
        field_rows.append({
            "key": key,
            "label": spec_service.FIELD_LABELS.get(key, key),
            "value": display,
            "resolved_by": val["resolved_by"],
        })
    source_badge = {"lexicon": "词典", "profile": "画像", "clarify": "澄清", "assumption": "假设",
                    "search": "检索", "session": "上文"}
    for f in field_rows:
        f["resolved_by_label"] = source_badge.get(f["resolved_by"], f["resolved_by"])
    return {
        "card_type": "spec",
        "spec_uid": row.spec_uid,
        "task_type": task_type,
        "fields": field_rows,
        "terms": spec["terms"],
        "evidence_needs": spec["evidence_needs"],
        "risk_tier": risk_tier,
    }
