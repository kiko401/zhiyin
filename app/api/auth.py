import re

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, Field

from app.core import config, security
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$")
LOGIN_FAIL_LOCK = 5
COOKIE_MAX_AGE = 7 * 86400


class AuthBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="zhiyin_session",
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/register")
async def register(body: AuthBody, request: Request, response: Response):
    if not USERNAME_RE.fullmatch(body.username):
        raise ApiError(40001, "用户名须为3-20位字母、数字、下划线或中文")
    if len(body.password) < 8:
        raise ApiError(40001, "密码至少8位")

    # 注册限流：每 IP 每日上限，防灌
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "local")
    count = await security.incr_daily(f"reg_limit:{client_ip}")
    if count > config.REGISTER_DAILY_LIMIT:
        raise ApiError(42901, "今日注册次数已达上限", status_code=429)

    async with SessionLocal() as db:
        exists = await db.execute(User.__table__.select().where(User.username == body.username))
        if exists.first():
            raise ApiError(40001, "用户名已存在")
        user = User(username=body.username, password_hash=security.hash_password(body.password))
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = await security.create_session(user.id)
    _set_cookie(response, token)
    return ok({"user_id": user.id, "username": user.username})


@router.post("/login")
async def login(body: AuthBody, response: Response):
    r = security.redis_client()
    lock_key = f"login_lock:{body.username}"
    if await r.get(lock_key):
        raise ApiError(42901, "失败次数过多，请10分钟后再试", status_code=429)

    async with SessionLocal() as db:
        row = await db.execute(User.__table__.select().where(User.username == body.username))
        user = row.first()
        if not user or not security.verify_password(body.password, user.password_hash):
            fails = await r.incr(f"login_fail:{body.username}")
            await r.expire(f"login_fail:{body.username}", 600)
            if fails >= LOGIN_FAIL_LOCK:
                await r.set(lock_key, "1", ex=600)
                await r.delete(f"login_fail:{body.username}")
            raise ApiError(40001, "用户名或密码错误")

    await r.delete(f"login_fail:{body.username}")
    token = await security.create_session(user.id)
    _set_cookie(response, token)
    return ok({"user_id": user.id, "username": user.username})


@router.post("/logout")
async def logout(response: Response, zhiyin_session: str | None = Cookie(default=None, alias="zhiyin_session")):
    await security.destroy_session(zhiyin_session)
    response.delete_cookie("zhiyin_session", path="/")
    return ok()
