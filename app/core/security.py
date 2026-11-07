import secrets
from datetime import date

import redis.asyncio as aioredis
from passlib.context import CryptContext

from . import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_redis: aioredis.Redis | None = None


def redis_client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    return _redis


async def check_redis() -> bool:
    try:
        return bool(await redis_client().ping())
    except Exception:
        return False


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


async def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    await redis_client().set(f"session:{token}", str(user_id), ex=config.SESSION_TTL_DAYS * 86400)
    return token


async def get_user_id(token: str | None) -> int | None:
    if not token:
        return None
    value = await redis_client().get(f"session:{token}")
    return int(value) if value else None


async def destroy_session(token: str | None) -> None:
    if token:
        await redis_client().delete(f"session:{token}")


async def incr_daily(key: str) -> int:
    """按自然日计数的计数器，返回当日累计值。"""
    r = redis_client()
    full_key = f"{key}:{date.today().isoformat()}"
    count = await r.incr(full_key)
    if count == 1:
        await r.expire(full_key, 86400 * 2)
    return int(count)
