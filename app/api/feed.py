"""动态页简报流与反馈（降噪闭环入口）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import Briefing, BriefingFeedback, StandingTask

router = APIRouter(tags=["feed"])


@router.get("/api/feed")
async def feed(page: int = 1, size: int = 20, user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        rows = await db.execute(
            select(Briefing).where(Briefing.status == "published")
            .order_by(Briefing.id.desc()).offset((page - 1) * size).limit(size))
        items = []
        for b in rows.scalars():
            st = await db.get(StandingTask, b.standing_task_id)
            items.append({
                "briefing_uid": b.briefing_uid, "headline": b.headline,
                "fact_text": b.fact_text, "impact_text": b.impact_text,
                "evidence": b.evidence, "created_at": str(b.created_at),
                "task_name": st.name if st else "", "ticker": st.ticker if st else None,
            })
    return ok({"items": items})


class FeedbackBody(BaseModel):
    feedback: str


@router.post("/api/briefing/{briefing_uid}/feedback")
async def briefing_feedback(briefing_uid: str, body: FeedbackBody, user_id: int = Depends(require_user)):
    if body.feedback not in ("useful", "not_important"):
        raise ApiError(40001, "反馈取值非法")
    async with SessionLocal() as db:
        row = await db.execute(select(Briefing).where(Briefing.briefing_uid == briefing_uid))
        b = row.scalar_one_or_none()
        if not b:
            raise ApiError(40401, "简报不存在", status_code=404)
        db.add(BriefingFeedback(briefing_id=b.id, user_id=user_id, feedback=body.feedback))
        if body.feedback == "not_important":
            # 负反馈降噪：词表收紧一档（移除末位宽泛词，简化策略）
            st = await db.get(StandingTask, b.standing_task_id)
            if st:
                cfg = dict(st.trigger_config or {})
                kw = cfg.get("keywords") or []
                if len(kw) > 1:
                    cfg["keywords"] = kw[:-1]
                    st.trigger_config = cfg
        await db.commit()
    return ok({"feedback": body.feedback})
