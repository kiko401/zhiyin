"""扶摇 REST 数据面。M2 提供标的检索；行情/财报/估值工具随任务引擎接入。"""
import httpx

from app.core import config


class FuyaoError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"fuyao code={code} {message}")
        self.code = code


def _headers() -> dict:
    return {"X-api-key": config.FUYAO_API_KEY}


async def _get(path: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as cli:
        resp = await cli.get(f"{config.FUYAO_BASE_URL}{path}", params=params, headers=_headers())
    body = resp.json()
    if body.get("code") == 0:
        return body.get("data") or {}
    raise FuyaoError(body.get("code"), body.get("message"))


async def search_ticker(q: str, limit: int = 3) -> list[dict]:
    """标的检索。必须按 a-share 过滤：同代码基金/指数会排在前面。"""
    data = await _get("/api/meta/tickers/search", {"q": q, "asset_type": "a-share", "limit": limit})
    return data.get("item") or []
