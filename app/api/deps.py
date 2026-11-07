from fastapi import Cookie

from app.core import security


async def require_user(zhiyin_session: str | None = Cookie(default=None, alias="zhiyin_session")) -> int:
    user_id = await security.get_user_id(zhiyin_session)
    if not user_id:
        from app.core.responses import ApiError

        raise ApiError(40402, "未登录", status_code=401)
    return user_id
