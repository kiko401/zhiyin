"""页面路由：薄壳渲染，数据经页面加载时注入或前端 API 拉取。"""
import csv
from pathlib import Path

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.core import security
from app.core.db import SessionLocal
from app.models import Briefing, StandingTask

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))

router = APIRouter(tags=["pages"])


async def _uid(request: Request):
    return await security.get_user_id(request.cookies.get("zhiyin_session"))


def _authed(request: Request, uid):
    if not uid:
        return RedirectResponse("/login", status_code=302)
    return None


@router.get("/login")
async def login_page(request: Request):
    uid = await _uid(request)
    if uid:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@router.get("/")
async def chat_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    return templates.TemplateResponse(request, "chat.html")


@router.get("/ideas")
async def ideas_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    ideas = yaml.safe_load((ROOT / "data" / "ideas.yaml").read_text(encoding="utf-8"))
    return templates.TemplateResponse(request, "ideas.html", {"ideas": ideas})


@router.get("/feed")
async def feed_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    uid = await _uid(request)
    async with SessionLocal() as db:
        rows = await db.execute(select(Briefing).where(Briefing.status == "published")
                                .order_by(Briefing.id.desc()).limit(50))
        briefings = [b for b in rows.scalars()]
    return templates.TemplateResponse(request, "feed.html", {"briefings": briefings})


@router.get("/tasks")
async def tasks_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    uid = await _uid(request)
    async with SessionLocal() as db:
        rows = await db.execute(select(StandingTask).where(
            StandingTask.user_id == uid, StandingTask.status != "deleted")
            .order_by(StandingTask.id.desc()))
        standings = rows.scalars().all()
    return templates.TemplateResponse(request, "tasks.html", {"standings": standings})


@router.get("/profile")
async def profile_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    return templates.TemplateResponse(request, "profile.html")


@router.get("/golden")
async def golden_page(request: Request):
    path = ROOT / "data" / "golden_60.csv"
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("gid")]
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    return templates.TemplateResponse(request, "golden.html", {"groups": groups})


@router.get("/eval")
async def eval_page(request: Request):
    guard = _authed(request, await _uid(request))
    if guard:
        return guard
    return templates.TemplateResponse(request, "eval.html", {"latest": None})


@router.get("/about")
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html")
