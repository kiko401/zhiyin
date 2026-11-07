"""画像字段白名单读写与注入（D5 / R6）。"""
import re

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import ProfileField, ProfileHit

# 白名单：仅允许这五个画像字段入库与注入
PROFILE_KEYS = ("time_horizon", "risk_context", "unit_pref", "watch_list", "knowledge_level")


def _check_key(field_key: str) -> None:
    if field_key not in PROFILE_KEYS:
        raise ValueError(f"field_key 不在白名单: {field_key}")


async def get_fields(user_id: int) -> dict:
    """返回 {field_key: {"value": any, "value_source": str|None, "auth_state": str}}。"""
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(ProfileField).where(ProfileField.user_id == user_id))
        ).scalars().all()
    fields: dict = {}
    for row in rows:
        fields[row.field_key] = {
            "value": row.value,
            "value_source": row.value_source,
            "auth_state": row.auth_state,
        }
    return fields


async def upsert_field(
    user_id: int,
    field_key: str,
    value,
    value_source: str = "declared",
    auth_state: str = "session_only",
) -> None:
    _check_key(field_key)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(ProfileField).where(
                    ProfileField.user_id == user_id,
                    ProfileField.field_key == field_key,
                )
            )
        ).scalars().first()
        if row is None:
            session.add(
                ProfileField(
                    user_id=user_id,
                    field_key=field_key,
                    value=value,
                    value_source=value_source,
                    auth_state=auth_state,
                )
            )
        else:
            row.value = value
            row.value_source = value_source
            row.auth_state = auth_state
        await session.commit()


async def delete_all(user_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(ProfileField).where(ProfileField.user_id == user_id))
        await session.commit()


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[,，、;；\s]+", value) if p.strip()]
    return [value]


async def effective(user_id: int, session_fields: dict | None = None) -> dict:
    """合并规则：granted 字段为基底，会话澄清所得覆盖同名，denied 排除。"""
    merged: dict = {}
    stored = await get_fields(user_id)
    for key, info in stored.items():
        if info["auth_state"] == "granted":
            merged[key] = info["value"]
    for key, value in (session_fields or {}).items():
        if key in PROFILE_KEYS:
            merged[key] = (
                value.get("value") if isinstance(value, dict) and "value" in value else value
            )
    for key, info in stored.items():
        if info["auth_state"] == "denied":
            merged.pop(key, None)
    # watch_list 注入下游时恒为列表
    return {k: (_as_list(v) if k == "watch_list" else v) for k, v in merged.items()}


async def record_hit(
    user_id: int,
    field_key: str,
    purpose: str,
    session_id: int | None = None,
    accepted: bool | None = None,
) -> None:
    async with SessionLocal() as session:
        session.add(
            ProfileHit(
                user_id=user_id,
                field_key=field_key,
                purpose=purpose,
                session_id=session_id,
                accepted=accepted,
            )
        )
        await session.commit()
