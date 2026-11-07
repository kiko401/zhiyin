#!/usr/bin/env python3
"""demo 熟客态生成：真实引擎回放（注册 demo 账号 → 画像授权 → 两会话交互 → 委托与首次检查）。幂等：存在即跳过。

用法：docker exec zhiyin-fastapi python scripts/seed_demo.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

BASE = "http://127.0.0.1:8000"


async def demo_ready() -> bool:
    from app.models import StandingTask

    async with SessionLocal() as db:
        row = await db.execute(select(User).where(User.username == "demo"))
        user = row.scalar_one_or_none()
        if not user:
            return False
        st = await db.execute(select(StandingTask).where(StandingTask.user_id == user.id))
        return st.first() is not None


async def main():
    if await demo_ready():
        print(json_result(skip=True))
        return
    async with SessionLocal() as db:
        row = await db.execute(select(User).where(User.username == "demo"))
        exists = row.scalar_one_or_none() is not None
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as c:
        if not exists:
            r = await c.post("/api/auth/register", json={"username": "demo", "password": "demo123456"})
            r.raise_for_status()
        await c.post("/api/auth/login", json={"username": "demo", "password": "demo123456"})
        for key, value in (("time_horizon", "短线"), ("risk_context", "被套中"),
                           ("knowledge_level", "veteran")):
            await c.patch(f"/api/profile/field/{key}", json={"value": value, "auth_state": "granted"})
        c.patch("/api/profile/field/watch_list",
                json={"value": ["宁德时代", "新易盛", "天孚通信", "中际旭创", "贵州茅台"],
                      "auth_state": "granted"})

        # 会话一：词典+画像零澄清（熟客体验）
        d = await c.post("/api/chat", json={"text": "宁王这波断板了还能拿吗"}).json()["data"]
        spec_card = d["cards"][-1]
        if spec_card["card_type"] == "spec":
            await c.post(f"/api/spec/{spec_card['spec_uid']}/confirm", json=None)

        # 会话二：委托值守（委托卡 → 确认 → 首检简报）
        d = await c.post("/api/chat", json={"text": "帮我盯着新易盛的减持公告，有动静告诉我"}).json()["data"]
        card = d["cards"][-1]
        if card["card_type"] == "delegate":
            await c.post(f"/api/spec/{card['spec_uid']}/confirm", json=None)

        # 会话三：点子式清晰题
        await c.post("/api/chat", json={"text": "贵州茅台最新收盘价是多少"})
    print(json_result(skip=False))


def json_result(skip: bool) -> str:
    import json
    return json.dumps({"demo": "ready" if not skip else "already", "replay": "engine"}, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
