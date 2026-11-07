"""补充接口：金标题库 / 词典检索 / AI 使用记录导出。"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ok
from app.models import AiUsageLog, LexiconTerm

router = APIRouter(tags=["extras"])

ROOT = Path(__file__).resolve().parents[2]
_golden_cache = None


@router.get("/api/eval/golden")
async def eval_golden(user_id: int = Depends(require_user)):
    global _golden_cache
    if _golden_cache is None:
        path = ROOT / "data" / "golden_60.csv"
        with path.open(encoding="utf-8") as f:
            _golden_cache = [r for r in csv.DictReader(f) if r.get("gid")]
    return ok(_golden_cache)


@router.get("/api/lexicon")
async def list_lexicon(page: int = 1, size: int = 50, q: str = "", user_id: int = Depends(require_user)):
    from app.models import LexiconTerm as LT

    async with SessionLocal() as db:
        query = select(LT).where(LT.owner_id.is_(None), LT.governance == "published")
        if q:
            query = query.where(LT.term.contains(q) | LT.canonical.contains(q))
        rows = await db.execute(query.offset((page - 1) * size).limit(size))
        items = [{"term": t.term, "layer": t.layer, "canonical": t.canonical,
                  "definition": t.definition, "risk_flag": t.risk_flag,
                  "confidence": float(t.confidence)} for t in rows.scalars()]
    return ok({"items": items})


@router.get("/api/ai-usage/export")
async def export_ai_usage(user_id: int = Depends(require_user)):
    from app.models import AiUsageLog as AUL

    async with SessionLocal() as db:
        rows = await db.execute(select(AUL).order_by(AUL.id))
        logs = rows.scalars().all()

    buf = io.StringIO()
    buf.write("id,task_id,purpose,model,prompt_tokens,completion_tokens,latency_ms,status,created_at\n")
    for log in logs:
        buf.write(f"{log.id},{log.task_id or ''},{log.purpose},{log.model},"
                  f"{log.prompt_tokens or ''},{log.completion_tokens or ''},"
                  f"{log.latency_ms or ''},{log.status},{log.created_at}\n")
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ai_usage.csv"},
    )
