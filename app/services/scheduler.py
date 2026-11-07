"""持续任务调度器：单容器 asyncio 循环 + Redis 锁防重入（PRD 2.12/2.13）。

交易日历：优先扶摇交易日历工具，故障按周一至周五兜底（PRD 2.13/EX-3 注记）。
"""
import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select

from app.core import config, security
from app.core.db import SessionLocal
from app.models import StandingTask
from app.services import engine

TICK_SECONDS = 300  # 5 分钟巡检粒度


async def _is_trading_day(today: datetime) -> bool:
    # 交易日历工具故障时按周一至周五兜底（E 系降级口径）
    try:
        from app.tools import fuyao

        data = await fuyao._get("/api/a-share/calendar/trading-days", {"limit": 5})
        days = data.get("item") or data.get("days") or []
        today_str = today.strftime("%Y-%m-%d")
        if days:
            return any(today_str in str(d) for d in days)
    except Exception:
        pass
    return today.weekday() < 5


def _due(now: datetime, last_check, schedule: str | None) -> bool:
    """检查窗口判定：小时内每小时一次；15:30 例行窗口。"""
    if schedule == "收盘后15:30" or schedule == "交易日15:30":
        return now.hour == 15 and 30 <= now.minute < 45
    # 默认小时级：距上次检查 ≥ 55 分钟
    if last_check is None:
        return True
    return (now - last_check).total_seconds() >= 55 * 60


async def run_check(standing: StandingTask) -> str | None:
    """立即检查：为持续任务创建一次 standing_watch 检查任务。"""
    tk = {"code": standing.ticker, "name": standing.name.replace("盯盘", "")}
    spec = {
        "spec_version": 1, "task_type": "standing_watch",
        "fields": {"ticker": {"value": tk, "resolved_by": "profile"}},
        "terms": [], "evidence_needs": ["snapshot", "limit_up", "hot_list", "news"],
        "compliance": {"risk_tier": 0},
    }
    from app.core.db import SessionLocal as SL
    from app.models import ResearchSpec

    async with SL() as db:
        row = ResearchSpec(spec_uid=str(uuid.uuid4()), user_id=standing.user_id,
                           session_id=None, version=1, task_type="standing_watch",
                           spec=spec, status="confirmed")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    task = await engine.create_task(user_id=standing.user_id, session_id=None,
                                    spec_row=row, standing_task_id=standing.id,
                                    auto_confirmed=True, check_quota=True)
    return task.task_uid


async def _tick():
    now = datetime.now()
    r = security.redis_client()
    got = await r.set("scheduler:lock", "1", nx=True, ex=TICK_SECONDS - 30)
    if not got:
        return
    trading = await _is_trading_day(now)
    async with SessionLocal() as db:
        rows = await db.execute(select(StandingTask).where(StandingTask.status == "active"))
        standings = rows.scalars().all()
        for st in standings:
            try:
                if st.task_type == "watch" and not trading:
                    continue
                if st.task_type == "routine" and not trading:
                    continue
                if _due(now, st.last_check_at, (st.trigger_config or {}).get("schedule")):
                    await run_check(st)
                    st.last_check_at = now
            except Exception:
                # E11：单任务异常不阻断巡检；连续失败置待手动检查由任务侧标记
                continue
        await db.commit()


async def _loop():
    while True:
        try:
            await _tick()
        except Exception:
            pass
        await asyncio.sleep(TICK_SECONDS)


def start():
    if config.SCHEDULER_ENABLED:
        asyncio.get_event_loop().create_task(_loop())
