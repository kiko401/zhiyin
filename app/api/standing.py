"""持续任务管理（盯与追页/委托确认共用契约）。"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import StandingTask
from app.services import scheduler

router = APIRouter(tags=["standing"])


class StandingBody(BaseModel):
    task_type: str = "watch"
    name: str
    ticker: str | None = None
    trigger: dict


@router.get("/api/standing")
async def list_standing(user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        rows = await db.execute(
            select(StandingTask)
            .where(StandingTask.user_id == user_id, StandingTask.status != "deleted")
            .order_by(StandingTask.id.desc())
        )
        items = [{"standing_uid": s.standing_uid, "task_type": s.task_type, "name": s.name,
                  "ticker": s.ticker, "status": s.status, "freq_cap": s.freq_cap,
                  "trigger": s.trigger_config, "last_check_at": str(s.last_check_at or "")}
                 for s in rows.scalars()]
    return ok({"items": items})


@router.post("/api/standing")
async def create_standing(body: StandingBody, user_id: int = Depends(require_user)):
    if body.task_type == "watch" and not body.ticker:
        raise ApiError(40001, "盯盘任务需指定标的")
    async with SessionLocal() as db:
        st = StandingTask(standing_uid=str(uuid.uuid4()), user_id=user_id,
                          task_type=body.task_type, name=body.name, ticker=body.ticker,
                          trigger_config=body.trigger, freq_cap=1, status="active")
        db.add(st)
        await db.commit()
        await db.refresh(st)
    return ok({"standing_uid": st.standing_uid})


class StandingPatch(BaseModel):
    status: str | None = None
    trigger: dict | None = None


@router.patch("/api/standing/{standing_uid}")
async def patch_standing(standing_uid: str, body: StandingPatch, user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        row = await db.execute(select(StandingTask).where(
            StandingTask.standing_uid == standing_uid, StandingTask.user_id == user_id))
        st = row.scalar_one_or_none()
        if not st:
            raise ApiError(40401, "任务不存在", status_code=404)
        if body.status in ("active", "paused"):
            st.status = body.status
        if body.trigger is not None:
            st.trigger_config = body.trigger
        await db.commit()
        return ok({"standing_uid": standing_uid, "status": st.status})


@router.delete("/api/standing/{standing_uid}")
async def delete_standing(standing_uid: str, user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        row = await db.execute(select(StandingTask).where(
            StandingTask.standing_uid == standing_uid, StandingTask.user_id == user_id))
        st = row.scalar_one_or_none()
        if not st:
            raise ApiError(40401, "任务不存在", status_code=404)
        st.status = "deleted"
        await db.commit()
    return ok()


@router.post("/api/standing/{standing_uid}/check")
async def manual_check(standing_uid: str, user_id: int = Depends(require_user)):
    """E11：立即检查（调度器停摆或待手动检查时使用）。"""
    async with SessionLocal() as db:
        row = await db.execute(select(StandingTask).where(
            StandingTask.standing_uid == standing_uid, StandingTask.user_id == user_id))
        st = row.scalar_one_or_none()
        if not st:
            raise ApiError(40401, "任务不存在", status_code=404)
        if st.status == "paused":
            raise ApiError(40001, "任务已暂停，请先恢复")
    task_uid = await scheduler.run_check(st)
    return ok({"task_uid": task_uid})
