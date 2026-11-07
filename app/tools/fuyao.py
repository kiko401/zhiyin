"""扶摇 REST 数据面：个股与标的事实面工具（检索/快照/K线/估值/利润表/涨停池/热榜）。

统一返回 {"as_of": 日期, ...业务数据}；调用失败抛 FuyaoError，由引擎走降级。
"""
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core import config

TZ = timezone(timedelta(hours=8))


class FuyaoError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"fuyao code={code} {message}")
        self.code = code


_cache: dict[tuple, tuple[float, object]] = {}


def _fmt_ms(v) -> str | None:
    return datetime.fromtimestamp(v / 1000, tz=TZ).strftime("%Y-%m-%d") if v else None


async def _get(path: str, params: dict, cache_ttl: int = 0) -> dict:
    key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
    if cache_ttl:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < cache_ttl:
            return hit[1]
    async with httpx.AsyncClient(timeout=15) as cli:
        resp = await cli.get(f"{config.FUYAO_BASE_URL}{path}", params=params,
                             headers={"X-api-key": config.FUYAO_API_KEY})
    body = resp.json()
    if body.get("code") != 0:
        raise FuyaoError(body.get("code"), body.get("message"))
    data = body.get("data") or {}
    if cache_ttl:
        _cache[key] = (time.time(), data)
    return data


async def search_ticker(q: str, limit: int = 3) -> list[dict]:
    """标的检索。必须按 a-share 过滤：同代码基金/指数会排在前面。"""
    data = await _get("/api/meta/tickers/search", {"q": q, "asset_type": "a-share", "limit": limit})
    return data.get("item") or []


async def snapshot(thscodes: list[str]) -> dict:
    data = await _get("/api/a-share/prices/snapshot", {"thscodes": ",".join(thscodes)},
                      cache_ttl=config.FUYAO_CACHE_TTL)
    items = {i.get("thscode"): i for i in data.get("item", [])}
    return {"as_of": _fmt_ms(data.get("timestamp")), "items": items,
            "unit": "元（CNY），成交量单位为股", "caliber": "行情快照，按请求时点返回盘中/收盘口径"}


async def kline(thscode: str, days: int = 60) -> dict:
    now = datetime.now(TZ)
    start = int((now - timedelta(days=int(days * 1.6))).timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    data = await _get("/api/a-share/prices/historical", {
        "thscode": thscode, "interval": "1d", "start": start, "end": end, "adjust": "forward",
    }, cache_ttl=config.FUYAO_CACHE_TTL)
    bars = data.get("item", [])[-days:]
    return {"as_of": _fmt_ms(data.get("timestamp")), "bars": bars,
            "unit": "元（CNY）", "caliber": f"日线前复权，近{len(bars)}个交易日"}


async def valuations(thscodes: list[str]) -> dict:
    data = await _get("/api/a-share/valuations/snapshot", {"thscodes": ",".join(thscodes)},
                      cache_ttl=config.FUYAO_CACHE_TTL)
    items = {i.get("thscode"): i for i in data.get("item", [])}
    return {"as_of": _fmt_ms(data.get("timestamp")), "items": items,
            "unit": "倍", "caliber": "PE_TTM/PE_MRQ、PB_MRQ、PS_TTM、PCF_TTM，口径见字段"}


async def income_statements(thscode: str, limit: int = 8) -> dict:
    data = await _get("/api/a-share/financials/income-statements",
                      {"thscode": thscode, "period": "quarterly", "limit": limit})
    items = data.get("item", [])
    # 最近单季同比（第 5 项为上年同期）
    yoy = None
    if len(items) >= 5 and items[0].get("operating_income") and items[4].get("operating_income"):
        yoy = round((items[0]["operating_income"] / items[4]["operating_income"] - 1) * 100, 2)
    return {"items": items, "latest_yoy_pct": yoy,
            "unit": "元（CNY）", "caliber": "整体合并利润表，报告期降序；累计口径，单季值需相邻期差分"}


async def limit_up_pool(size: int = 50) -> dict:
    data = await _get("/api/a-share/special-data/limit-up-pool",
                      {"page": 1, "size": size, "sort_field": "continue_day_cnt", "sort_dir": "desc"})
    return {"as_of": _fmt_ms(data.get("timestamp")), "items": data.get("item", []),
            "unit": "元", "caliber": "当日涨停池，按连板天数降序"}


async def hot_stock_list(limit: int = 20) -> dict:
    data = await _get("/api/a-share/special-data/hot-stock-list", {"period": "day", "limit": limit})
    return {"as_of": _fmt_ms(data.get("timestamp")), "items": data.get("item", []),
            "unit": "热度值（上游原始口径）", "caliber": "24小时级别热股榜"}
