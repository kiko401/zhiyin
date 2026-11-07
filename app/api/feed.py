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
       
