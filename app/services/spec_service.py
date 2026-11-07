"""研究规格构建与版本化落库（PRD 2.5）。"""
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import ResearchSpec

FIELD_LABELS = {
    "ticker": "研究哪只股票",
    "time_horizon": "周期",
    "risk_context": "你目前是",
    "caliber": "口径",
}

# 任务类型到证据蓝图（PRD 2.6，确定性映射）
BLUEPRINT_EVIDENCE = {
    "fact_query": ["snapshot", "kline", "valuation", "financials"],
    "decision_support": ["snapshot", "kline", "valuation", "financials", "breadth", "capital", "news"],
    "limit_up_review": ["snapshot", "limit_up", "hot_list", "news", "capital", "breadth"],
    "sector_review": ["snapshot", "index", "hot_list", "breadth", "capital"],
    "capital_perspective": ["snapshot", "capital", "news"],
    "standing_watch": ["snapshot", "limit_up", "hot_list", "news"],
    "routine_review": ["snapshot", "kline", "valuation", "financials", "breadth", "capital", "news"],
    "knowledge": [],
}


async def save_spec(
    user_id: int,
    session_id: int | None,
    task_type: str,
    fields: dict,
    terms: list | None = None,
    risk_tier: int = 0,
    trigger: dict | None = None,
) -> ResearchSpec:
    spec = {
        "spec_version": 1,
        "task_type": task_type,
        "fields": {k: {"value": v["value"], "resolved_by": v["resolved_by"]} for k, v in fields.items()},
        "terms": terms or [],
        "evidence_needs": BLUEPRINT_EVIDENCE.get(task_type, []),
        "compliance": {"risk_tier": risk_tier},
    }
    if trigger:
        spec["trigger"] = trigger

    async with SessionLocal() as db:
        row = ResearchSpec(
            spec_uid=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            version=1,
            task_type=task_type,
            spec=spec,
            status="draft",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_by_uid(spec_uid: str) -> ResearchSpec | None:
    async with SessionLocal() as db:
        row = await db.execute(select(ResearchSpec).where(ResearchSpec.spec_uid == spec_uid))
        return row.scalar_one_or_none()


async def last_ticker_of_session(session_id: int) -> dict | None:
    """会话内最近一次规格的标的，用于指代解析（它/这只）。"""
    async with SessionLocal() as db:
        row = await db.execute(
            select(ResearchSpec)
            .where(ResearchSpec.session_id == session_id)
            .order_by(ResearchSpec.id.desc())
            .limit(1)
        )
        spec = row.scalar_one_or_none()
    if not spec:
        return None
    t = (spec.spec or {}).get("fields", {}).get("ticker", {}).get("value")
    if isinstance(t, dict) and t.get("code"):
        return t
    return None


async def get_uid_by_id(spec_id: int) -> str | None:
    async with SessionLocal() as db:
        row = await db.get(ResearchSpec, spec_id)
        return row.spec_uid if row else None
