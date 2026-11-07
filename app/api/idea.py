"""点子货架：读取配置与发起预填规格。"""
import uuid

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pathlib import Path

from app.api.deps import require_user
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.models import ResearchSpec
from app.services import spec_service

router = APIRouter(tags=["idea"])

ROOT = Path(__file__).resolve().parents[2]
_ideas_cache = None


def _load_ideas():
    global _ideas_cache
    if _ideas_cache is None:
        path = ROOT / "data" / "ideas.yaml"
        _ideas_cache = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return _ideas_cache


@router.get("/api/ideas")
async def list_ideas(user_id: int = Depends(require_user)):
    ideas = _load_ideas()
    return ok(ideas)


class LaunchBody(BaseModel):
    ticker: str | None = None
    ticker_name: str | None = None


@router.post("/api/idea/{idea_id}/launch")
async def launch_idea(idea_id: str, body: LaunchBody | None = None, user_id: int = Depends(require_user)):
    ideas = _load_ideas()
    idea = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        raise ApiError(40401, "点子不存在", status_code=404)

    task_type = idea.get("task_type", "decision_support")
    fields = {}
    ticker = None
    if body and body.ticker:
        code = body.ticker
        name = body.ticker_name or code
        ticker = {"code": code, "name": name}
        fields["ticker"] = {"value": ticker, "resolved_by": "clarify"}
    if task_type == "decision_support" and idea.get("id") == "trapped_research":
        fields["risk_context"] = {"value": "被套中", "resolved_by": "assumption"}

    row = await spec_service.save_spec(
        user_id=user_id, session_id=None, task_type=task_type,
        fields=fields, terms=[], risk_tier=0,
    )
    return ok({"spec_uid": row.spec_uid, "task_type": row.task_type, "idea": idea})
