import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import ResearchSpec, ResearchTask, TaskEvent
from app.services import engine, spec_service
from sqlalchemy import select

router = APIRouter(tags=["task"])


class ConfirmBody(BaseModel):
    spec: dict | None = None  # 编辑后的规格字段（可选，全量落库版本+1）


@router.post("/api/spec/{spec_uid}/confirm")
async def confirm_spec(spec_uid: str, body: ConfirmBody | None = None, user_id: int = Depends(require_user)):
    """规格确认断点：一次性任务 → 建研究任务；委托类 → 建持续任务并立即首次检查。"""
    row = await spec_service.get_by_uid(spec_uid)
    if not row or row.user_id != user_id:
        raise ApiError(40401, "规格不存在", status_code=404)
    if row.status == "cancelled":
        raise ApiError(40001, "规格已取消")

    if body and body.spec:
        edits = body.spec.get("fields")
        if edits:
            merged = dict(row.spec)
            merged["fields"] = {**merged.get("fields", {}), **edits}
            row.spec = merged
            row.version += 1
        if body.spec.get("trigger"):
            merged = dict(row.spec)
            merged["trigger"] = body.spec["trigger"]
            row.spec = merged
            row.version += 1

    if row.task_type == "standing_watch":
        task = await _confirm_delegate(row, user_id)
    else:
        row.status = "confirmed"
        async with SessionLocal() as db:
            await db.merge(row)
            await db.commit()
        task = await engine.create_task(user_id=user_id, session_id=row.session_id,
                                        spec_row=row, idempotency_key=f"spec:{row.spec_uid}:v{row.version}")

    from fastapi import Response
    import json as _json
    return Response(
        status_code=202,
        media_type="application/json",
        content=_json.dumps({"code": 0, "message": "accepted",
                             "data": {"task_uid": task.task_uid, "state": task.state}}),
    )


async def _confirm_delegate(spec_row: ResearchSpec, user_id: int):
    """委托确认：创建持续任务并立即执行首次检查（CH-09）。"""
    import uuid as _uuid

    from app.models import StandingTask

    trigger = (spec_row.spec or {}).get("trigger", {})
    tk = (spec_row.spec or {}).get("fields", {}).get("ticker", {}).get("value", {})
    async with SessionLocal() as db:
        st = StandingTask(
            standing_uid=str(_uuid.uuid4()),
            user_id=user_id,
            task_type="watch",
            name=f"{tk.get('name', '')}盯盘",
            ticker=tk.get("code"),
            trigger_config=trigger,
            freq_cap=1,
            status="active",
        )
        db.add(st)
        await db.commit()
        await db.refresh(st)

        # 首次检查任务：以 standing_watch 蓝图执行
        check_spec = ResearchSpec(
            spec_uid=str(_uuid.uuid4()), user_id=user_id, session_id=spec_row.session_id,
            version=1, task_type="standing_watch",
            spec={"spec_version": 1, "task_type": "standing_watch",
                  "fields": {"ticker": {"value": tk, "resolved_by": "clarify"}},
                  "terms": [], "evidence_needs": ["snapshot", "limit_up", "hot_list", "news"],
                  "compliance": {"risk_tier": 0}},
            status="confirmed",
        )
        db.add(check_spec)
        await db.commit()
        await db.refresh(check_spec)

    return await engine.create_task(user_id=user_id, session_id=spec_row.session_id,
                                    spec_row=check_spec, standing_task_id=st.id, auto_confirmed=True)


@router.get("/api/task/{task_uid}")
async def get_task(task_uid: str, user_id: int = Depends(require_user)):
    view = await engine.get_task_view(task_uid, user_id)
    if not view:
        raise ApiError(40401, "任务不存在", status_code=404)
    return ok(view)


@router.get("/api/task/{task_uid}/events")
async def task_events(task_uid: str, user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        trow = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        t = trow.scalar_one_or_none()
        if not t or t.user_id != user_id:
            raise ApiError(40401, "任务不存在", status_code=404)
        rows = await db.execute(select(TaskEvent).where(TaskEvent.task_id == t.id).order_by(TaskEvent.id))
        events = [{"id": e.id, "event_type": e.event_type, "stage": e.stage,
                   "payload": e.payload, "elapsed_ms": e.elapsed_ms, "created_at": str(e.created_at)}
                  for e in rows.scalars()]
    return ok({"task_uid": task_uid, "events": events})


@router.post("/api/task/{task_uid}/retry")
async def retry_task(task_uid: str, user_id: int = Depends(require_user)):
    async with SessionLocal() as db:
        trow = await db.execute(select(ResearchTask).where(ResearchTask.task_uid == task_uid))
        t = trow.scalar_one_or_none()
        if not t or t.user_id != user_id:
            raise ApiError(40401, "任务不存在", status_code=404)
        if t.state != "FAILED":
            raise ApiError(40001, "仅失败任务可重跑")
        spec_row = await db.get(ResearchSpec, t.spec_id)
    task = await engine.create_task(user_id=user_id, session_id=t.session_id, spec_row=spec_row)
    return ok({"task_uid": task.task_uid, "state": task.state})


@router.get("/api/tasks")
async def list_tasks(page: int = 1, size: int = 20, user_id: int = Depends(require_user)):
    from sqlalchemy import func

    async with SessionLocal() as db:
        total_row = await db.execute(
            select(func.count()).select_from(ResearchTask).where(ResearchTask.user_id == user_id))
        total = int(total_row.scalar() or 0)
        rows = await db.execute(
            select(ResearchTask).where(ResearchTask.user_id == user_id)
            .order_by(ResearchTask.id.desc()).offset((page - 1) * size).limit(size))
        items = [{"task_uid": t.task_uid, "task_type": t.task_type, "state": t.state,
                  "created_at": str(t.created_at)} for t in rows.scalars()]
    return ok({"items": items, "total": total})
