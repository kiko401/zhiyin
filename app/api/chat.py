import json
import time
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import config, security
from app.core.db import SessionLocal
from app.core.responses import ApiError, ok
from app.api.deps import require_user
from app.models import Clarification, ClarificationChoice, Message, ResearchSpec, Session as ChatSession
from app.services import decision as decision_svc
from app.services import profile as profile_svc
from app.services import spec_service
from app.tools import fuyao

router = APIRouter(tags=["chat"])

CLARIFY_TTL = 1800  # 与会话 30 分钟过期一致

ANSWER_FIELD = {"A3": "caliber", "A4": "time_horizon", "A5": "risk_context"}
STATE_BY_ACTION = {"boundary": "BOUNDARY", "clarify": "CLARIFY", "spec": "SPEC_REVIEW",
                   "delegate": "SPEC_REVIEW", "direct": "EXECUTING"}


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    session_uid: str | None = None


class ChoiceBody(BaseModel):
    choice: str | None = None
    skip: bool = False


class MemoryBody(BaseModel):
    field_key: str
    state: str = Field(pattern="^(granted|session_only|denied)$")


async def _get_or_create_session(db, user_id: int, session_uid: str | None) -> ChatSession:
    if session_uid:
        row = await db.execute(
            select(ChatSession).where(
                ChatSession.session_uid == session_uid, ChatSession.user_id == user_id
            )
        )
        s = row.scalar_one_or_none()
        if not s:
            raise ApiError(40401, "会话不存在", status_code=404)
        return s
    s = ChatSession(session_uid=str(uuid.uuid4()), user_id=user_id, state="IDLE")
    db.add(s)
    await db.flush()
    return s


def _persist_card(db, session_row, card: dict, task_uid: str | None = None) -> None:
    db.add(Message(
        session_id=session_row.id,
        role="system",
        card_type=card.get("card_type"),
        content=card,
        task_uid=task_uid,
    ))


async def _save_clarify_context(card: dict, ctx: dict) -> None:
    r = security.redis_client()
    await r.set(f"clarify:{card['clarify_id']}", json.dumps(ctx, ensure_ascii=False), ex=CLARIFY_TTL)


async def _session_ticker(session_id: int) -> dict | None:
    return await spec_service.last_ticker_of_session(session_id)


@router.post("/api/chat")
async def chat(body: ChatBody, user_id: int = Depends(require_user)):
    text = body.text.strip()
    if not text:
        raise ApiError(40001, "内容不能为空")
    truncated = len(text) > config.MAX_INPUT_CHARS
    if truncated:
        text = text[: config.MAX_INPUT_CHARS]

    r = security.redis_client()
    minute_key = f"chat_rate:{user_id}:{int(time.time() // 60)}"
    n = await r.incr(minute_key)
    await r.expire(minute_key, 60)
    if n > config.CHAT_RATE_PER_MIN:
        raise ApiError(42901, "提问太频繁，请稍后再试", status_code=429)

    async with SessionLocal() as db:
        s = await _get_or_create_session(db, user_id, body.session_uid)
        db.add(Message(session_id=s.id, role="user", content={"text": body.text}))
        await db.commit()
        session_uid, session_id = s.session_uid, s.id

    st = await _session_ticker(session_id)
    result = await decision_svc.decide(user_id, session_id, text, session_ticker=st)
    card = result["card"]
    cards = []
    if truncated:
        cards.append({"card_type": "system_banner", "level": "warn",
                      "text": f"输入超过{config.MAX_INPUT_CHARS}字，已截断处理"})

    if result["action"] == "direct":
        from app.services import engine

        spec_row = await spec_service.get_by_uid(result["spec_uid"])
        task = await engine.create_task(user_id=user_id, session_id=session_id,
                                        spec_row=spec_row, auto_confirmed=True)
        card = {"card_type": "work", "task_uid": task.task_uid,
                "state": task.state, "task_type": spec_row.task_type}

    async with SessionLocal() as db:
        row = await db.execute(
            select(ChatSession).where(ChatSession.session_uid == session_uid)
        )
        s = row.scalar_one_or_none()
        if card["card_type"] == "clarify":
            cl = Clarification(
                session_id=s.id,
                round_no=card.get("round", 1),
                question=card["question"],
                options={"options": card.get("options", []), "free_input": bool(result.get("free_input"))},
                ambiguity_type=card.get("ambiguity"),
                skippable=card.get("skippable", True),
            )
            db.add(cl)
            await db.commit()
            await db.refresh(cl)
            card["clarify_id"] = cl.id
            await _save_clarify_context(card, {
                "text": text, "answers": result.get("answers", {}),
                "round": card.get("round", 1), "ambiguity": card.get("ambiguity"),
                "session_uid": session_uid, "session_id": session_id, "user_id": user_id,
                "session_ticker": st, "candidates": result.get("candidates", []),
                "free_input": bool(result.get("free_input")),
            })
        _persist_card(db, s, card)
        if result["action"] != "direct":
            s.state = result["state"]
        s.last_active_at = __import__("datetime").datetime.now()
        await db.commit()

    cards.append(card)
    return ok({"session_uid": session_uid, "state": result["state"], "cards": cards})


@router.post("/api/clarify/{clarify_id}/choice")
async def clarify_choice(clarify_id: int, body: ChoiceBody, user_id: int = Depends(require_user)):
    r = security.redis_client()
    raw = await r.get(f"clarify:{clarify_id}")
    if not raw:
        raise ApiError(40401, "澄清已过期或不存在", status_code=404)
    ctx = json.loads(raw)

    async with SessionLocal() as db:
        row = await db.execute(
            Clarification.__table__.select().where(Clarification.id == clarify_id)
        )
        cl = row.first()
        if not cl:
            raise ApiError(40401, "澄清不存在", status_code=404)
        db.add(ClarificationChoice(
            clarification_id=clarify_id,
            choice=body.choice or "",
            is_skip=body.skip,
        ))
        await db.execute(
            Clarification.__table__.update()
            .where(Clarification.id == clarify_id)
            .values(status="closed")
        )
        await db.commit()

    answers = dict(ctx.get("answers") or {})
    ambiguity = ctx.get("ambiguity")
    session_ticker = ctx.get("session_ticker")
    if not body.skip and body.choice:
        if ambiguity == "A1":
            if ctx.get("candidates"):
                hit = next((c for c in ctx["candidates"] if c["name"] == body.choice), None)
                if hit:
                    answers["ticker"] = hit
                    session_ticker = hit
            else:  # 自由输入：按代码/名称检索
                try:
                    items = await fuyao.search_ticker(body.choice, limit=3)
                except Exception:
                    items = []
                if len(items) == 1:
                    answers["ticker"] = {"code": items[0].get("thscode"), "name": items[0].get("name")}
                    session_ticker = answers["ticker"]
                elif len(items) > 1:
                    new_card = decision_svc._clarify_card(0, "A1", "你指的是哪一只？",
                                                          [i.get("name") for i in items], ctx["round"] + 1)
                    async with SessionLocal() as db:
                        srow = await db.execute(select(ChatSession).where(
                            ChatSession.session_uid == ctx["session_uid"]))
                        s = srow.scalar_one_or_none()
                        cl2 = Clarification(session_id=s.id, round_no=ctx["round"] + 1,
                                            question=new_card["question"],
                                            options={"options": new_card["options"], "free_input": False},
                                            ambiguity_type="A1", skippable=True)
                        db.add(cl2)
                        await db.commit()
                        await db.refresh(cl2)
                        new_card["clarify_id"] = cl2.id
                        db.add(Message(session_id=s.id, role="system", card_type="clarify", content=new_card))
                        await db.commit()
                    await _save_clarify_context(new_card, {**ctx, "round": ctx["round"] + 1,
                                                           "ambiguity": new_card["ambiguity"]})
                    return ok({"session_uid": ctx["session_uid"], "state": "CLARIFY", "cards": [new_card]})
                else:
                    new_card = decision_svc._clarify_card(0, "A1", "没有检索到该标的，换个说法或直接输入代码。",
                                                          [], ctx["round"] + 1, skippable=False)
                    return ok({"session_uid": ctx["session_uid"], "state": "CLARIFY", "cards": [new_card]})
        else:
            field = ANSWER_FIELD.get(ambiguity)
            if field:
                answers[field] = body.choice

    round_no = ctx.get("round", 1)
    result = await decision_svc.decide(
        ctx["user_id"], ctx.get("session_id"), ctx["text"],
        session_ticker=session_ticker, answers=answers, round_no=round_no,
    )
    card = result["card"]
    cards = []

    async with SessionLocal() as db:
        srow = await db.execute(
            select(ChatSession).where(ChatSession.session_uid == ctx["session_uid"])
        )
        s = srow.scalar_one_or_none()
        if card["card_type"] == "clarify":
            cl2 = Clarification(
                session_id=s.id, round_no=card.get("round", round_no + 1),
                question=card["question"],
                options={"options": card.get("options", []), "free_input": bool(result.get("free_input"))},
                ambiguity_type=card.get("ambiguity"), skippable=card.get("skippable", True),
            )
            db.add(cl2)
            await db.commit()
            await db.refresh(cl2)
            card["clarify_id"] = cl2.id
            await _save_clarify_context(card, {**ctx, "answers": answers,
                                               "round": card.get("round", round_no + 1),
                                               "ambiguity": card.get("ambiguity"),
                                               "session_ticker": session_ticker})
        _persist_card(db, s, card)
        s.state = result["state"]
        await db.commit()

    if card["card_type"] in ("spec", "delegate"):
        memory = decision_svc._memory_fields(answers)
        if memory:
            cards.append({"card_type": "memory_note", "clarify_id": clarify_id, "fields": memory})
    cards.append(card)
    return ok({"session_uid": ctx["session_uid"], "state": result["state"], "cards": cards})


@router.post("/api/clarify/{clarify_id}/memory")
async def clarify_memory(clarify_id: int, body: MemoryBody, user_id: int = Depends(require_user)):
    r = security.redis_client()
    raw = await r.get(f"clarify:{clarify_id}")
    if not raw:
        raise ApiError(40401, "澄清已过期或不存在", status_code=404)
    ctx = json.loads(raw)
    field_key = body.field_key
    value = (ctx.get("answers") or {}).get(field_key)
    if value is None:
        # 周期/处境以外的字段（如口径）不落画像
        raise ApiError(40001, "该字段不在画像白名单")
    if isinstance(value, dict):
        value = value.get("name")
    if body.state == "denied":
        await profile_svc.upsert_field(user_id, field_key, None, "declared", "denied")
    else:
        state = "granted" if body.state == "granted" else "session_only"
        await profile_svc.upsert_field(user_id, field_key, value, "clarified", state)
    await profile_svc.record_hit(user_id, field_key, "personalize", accepted=body.state == "granted")
    return ok({"field_key": field_key, "auth_state": body.state})


@router.get("/api/sessions")
async def sessions(page: int = 1, size: int = 20, user_id: int = Depends(require_user)):
    from sqlalchemy import select, func

    async with SessionLocal() as db:
        total_row = await db.execute(
            select(func.count()).select_from(ChatSession).where(ChatSession.user_id == user_id)
        )
        total = int(total_row.scalar() or 0)
        rows = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.last_active_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        items = []
        for s in rows.scalars():
            first = await db.execute(
                select(Message).where(Message.session_id == s.id, Message.role == "user")
                .order_by(Message.id.asc()).limit(1)
            )
            fm = first.scalar_one_or_none()
            items.append({
                "session_uid": s.session_uid,
                "title": ((fm.content or {}).get("text", "")[:24] if fm else "空会话"),
                "state": s.state,
                "last_active_at": str(s.last_active_at),
            })
    return ok({"items": items, "total": total})


@router.get("/api/session/{session_uid}/history")
async def session_history(session_uid: str, user_id: int = Depends(require_user)):
    from sqlalchemy import select

    async with SessionLocal() as db:
        srow = await db.execute(
            ChatSession.__table__.select().where(
                ChatSession.session_uid == session_uid, ChatSession.user_id == user_id
            )
        )
        s = srow.first()
        if not s:
            raise ApiError(40401, "会话不存在", status_code=404)
        rows = await db.execute(
            select(Message).where(Message.session_id == s.id).order_by(Message.id.asc())
        )
        cards = []
        for m in rows.scalars():
            content = m.content or {}
            if m.role == "user":
                cards.append({"card_type": "user", "text": content.get("text", "")})
            else:
                content.setdefault("card_type", m.card_type or "system_banner")
                cards.append(content)
    return ok({"session_uid": session_uid, "state": s.state, "cards": cards})
