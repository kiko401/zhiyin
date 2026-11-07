"""画像接口：读取/授权与值更新/删除/导出（PR-01~04）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import ProfileField, StandingTask
from app.services import profile as profile_svc

router = APIRouter(tags=["profile"])


class FieldBody(BaseModel):
    value: object = None
    auth_state: str = "granted"


@router.get("/api/profile")
async def get_profile(user_id: int = Depends(require_user)):
    fields = await profile_svc.get_fields(user_id)
    return ok({"fields": fields})


@router.patch("/api/profile/field/{key}")
async def patch_field(key: str, body: FieldBody, user_id: int = Depends(require_user)):
    if body.auth_state not in ("granted", "session_only", "denied"):
        raise ApiError(40001, "授权状态非法")
    try:
        await profile_svc.upsert_field(user_id, key, body.value, "declared", body.auth_state)
    except ValueError:
        raise ApiError(40001, "字段不在画像白名单")
    await profile_svc.record_hit(user_id, key, "personalize", accepted=body.auth_state == "granted")
    return ok({"field_key": key, "auth_state": body.auth_state})


@router.delete("/api/profile")
async def delete_profile(user_id: int = Depends(require_user)):
    await profile_svc.delete_all(user_id)
    return ok()


@router.get("/api/profile/export")
async def export_profile(user_id: int = Depends(require_user)):
    fields = await profile_svc.get_fields(user_id)
    async with SessionLocal() as db:
        rows = await db.execute(select(StandingTask).where(StandingTask.user_id == user_id))
        standings = [{"standing_uid": s.standing_uid, "task_type": s.task_type, "name": s.name,
                      "ticker": s.ticker, "trigger": s.trigger_config} for s in rows.scalars()]
    return ok({"profile": fields, "standing_tasks": standings})
