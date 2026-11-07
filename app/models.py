from datetime import datetime
from typing import Any

from sqlalchemy import BIGINT, Boolean, Date, DateTime, DECIMAL, INT, String, Text, text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .core.db import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")
    )


class Session(Base):
    __tablename__ = "session"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_uid: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    state: Mapped[str] = mapped_column(String(16), default="IDLE")
    last_active_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BIGINT, index=True)
    role: Mapped[str] = mapped_column(String(8))
    card_type: Mapped[str | None] = mapped_column(String(16))
    content: Mapped[dict] = mapped_column(JSON)
    task_uid: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Clarification(Base):
    __tablename__ = "clarification"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BIGINT, index=True)
    round_no: Mapped[int] = mapped_column(default=1)
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    ambiguity_type: Mapped[str | None] = mapped_column(String(2))
    skippable: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ClarificationChoice(Base):
    __tablename__ = "clarification_choice"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    clarification_id: Mapped[int] = mapped_column(BIGINT, index=True)
    choice: Mapped[str] = mapped_column(String(255))
    is_skip: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ResearchSpec(Base):
    __tablename__ = "research_spec"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    spec_uid: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    session_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    version: Mapped[int] = mapped_column(default=1)
    task_type: Mapped[str] = mapped_column(String(24))
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ResearchTask(Base):
    __tablename__ = "research_task"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_uid: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    session_id: Mapped[int | None] = mapped_column(BIGINT)
    standing_task_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    spec_id: Mapped[int] = mapped_column(BIGINT)
    spec_version: Mapped[int] = mapped_column(INT)
    task_type: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    blueprint: Mapped[str | None] = mapped_column(String(32))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    queued_position: Mapped[int | None] = mapped_column()
    error_note: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class TaskEvent(Base):
    __tablename__ = "task_event"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BIGINT, index=True)
    event_type: Mapped[str] = mapped_column(String(24))
    stage: Mapped[str | None] = mapped_column(String(16))
    payload: Mapped[dict | None] = mapped_column(JSON)
    elapsed_ms: Mapped[int | None] = mapped_column(INT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ToolCall(Base):
    __tablename__ = "tool_call"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BIGINT, index=True)
    tool_name: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(8))
    input_digest: Mapped[str | None] = mapped_column(String(255))
    output_count: Mapped[int | None] = mapped_column(INT)
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[int | None] = mapped_column(INT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class EvidenceItem(Base):
    __tablename__ = "evidence_item"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BIGINT, index=True)
    layer: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(32))
    caliber: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Answer(Base):
    __tablename__ = "answer"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BIGINT, index=True)
    answer_uid: Mapped[str] = mapped_column(String(36), unique=True)
    content: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[str] = mapped_column(String(8))
    feedback: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class AiUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(BIGINT, index=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(32))
    prompt_tokens: Mapped[int | None] = mapped_column(INT)
    completion_tokens: Mapped[int | None] = mapped_column(INT)
    latency_ms: Mapped[int | None] = mapped_column(INT)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class StandingTask(Base):
    __tablename__ = "standing_task"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    standing_uid: Mapped[str] = mapped_column(String(36), unique=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    task_type: Mapped[str] = mapped_column(String(16))  # watch / routine
    name: Mapped[str] = mapped_column(String(64))
    ticker: Mapped[str | None] = mapped_column(String(16))
    trigger_config: Mapped[dict] = mapped_column(JSON)
    freq_cap: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class Briefing(Base):
    __tablename__ = "briefing"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    briefing_uid: Mapped[str] = mapped_column(String(36), unique=True)
    standing_task_id: Mapped[int] = mapped_column(BIGINT, index=True)
    task_id: Mapped[int] = mapped_column(BIGINT)
    headline: Mapped[str | None] = mapped_column(String(64))
    fact_text: Mapped[str] = mapped_column(String(255))
    impact_text: Mapped[str | None] = mapped_column(String(128))
    evidence: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="published")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), index=True)


class BriefingFeedback(Base):
    __tablename__ = "briefing_feedback"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    briefing_id: Mapped[int] = mapped_column(BIGINT, index=True)
    user_id: Mapped[int] = mapped_column(BIGINT)
    feedback: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class LexiconTerm(Base):
    __tablename__ = "lexicon_term"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(32))
    layer: Mapped[str] = mapped_column(String(2), index=True)
    canonical: Mapped[str] = mapped_column(String(128))
    definition: Mapped[str | None] = mapped_column(String(255))
    caliber_note: Mapped[str | None] = mapped_column(String(128))
    risk_flag: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float] = mapped_column(DECIMAL(3, 2))
    source: Mapped[str | None] = mapped_column(String(32))
    reviewer: Mapped[str | None] = mapped_column(String(16))
    owner_id: Mapped[int | None] = mapped_column(BIGINT)
    governance: Mapped[str] = mapped_column(String(16), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class LexiconHit(Base):
    __tablename__ = "lexicon_hit"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    term: Mapped[str] = mapped_column(String(32))
    resolved_to: Mapped[str] = mapped_column(String(128))
    overridden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ProfileField(Base):
    __tablename__ = "profile_field"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    field_key: Mapped[str] = mapped_column(String(24))
    value: Mapped[Any | None] = mapped_column(JSON)
    value_source: Mapped[str | None] = mapped_column(String(16))
    auth_state: Mapped[str] = mapped_column(String(12), default="session_only")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")
    )


class ProfileHit(Base):
    __tablename__ = "profile_hit"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, index=True)
    field_key: Mapped[str] = mapped_column(String(24))
    purpose: Mapped[str] = mapped_column(String(16))
    accepted: Mapped[bool | None] = mapped_column(Boolean)
    session_id: Mapped[int | None] = mapped_column(BIGINT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class EvalBatch(Base):
    __tablename__ = "eval_batch"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    batch_uid: Mapped[str] = mapped_column(String(36), unique=True)
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="running")
    result: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class EvalItem(Base):
    __tablename__ = "eval_item"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(BIGINT, index=True)
    gid: Mapped[str] = mapped_column(String(8))
    baseline_answer: Mapped[dict | None] = mapped_column(JSON)
    zhiyin_answer: Mapped[dict | None] = mapped_column(JSON)
    baseline_score: Mapped[dict | None] = mapped_column(JSON)
    zhiyin_score: Mapped[dict | None] = mapped_column(JSON)
    diff_note: Mapped[str | None] = mapped_column(String(255))
