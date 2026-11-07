from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import auth, chat, extras, feed, idea, pages, profile, spec, standing, task
from app.core import config, security
from app.core.db import check_db
from app.core.responses import api_error_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import lexicon as lexicon_svc
    from app.services import scheduler

    await lexicon_svc.warmup()
    scheduler.start()
    yield


app = FastAPI(title="知音 Zhiyin", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(spec.router)
app.include_router(task.router)
app.include_router(standing.router)
app.include_router(idea.router)
app.include_router(extras.router)
app.include_router(feed.router)
app.include_router(profile.router)
app.include_router(pages.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_exception_handler(HTTPException, api_error_handler)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"code": 40401, "message": "资源不存在", "data": None})


async def _demo_ready() -> bool:
    try:
        from app.core.db import engine

        async with engine.connect() as conn:
            from sqlalchemy import text as _t

            row = await conn.execute(_t("SELECT 1 FROM user WHERE username = 'demo' LIMIT 1"))
            return row.first() is not None
    except Exception:
        return False


async def _count_lexicon() -> int:
    try:
        from app.core.db import engine

        async with engine.connect() as conn:
            row = await conn.execute(
                text("SELECT COUNT(*) FROM lexicon_term WHERE governance = 'published'")
            )
            return int(row.scalar() or 0)
    except Exception:
        return 0


@app.get("/healthz")
async def healthz():
    db_ok = await check_db()
    redis_ok = await security.check_redis()
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": "ok" if db_ok else "fail",
        "redis": "ok" if redis_ok else "fail",
        "lexicon": await _count_lexicon(),
        "scheduler": "on" if config.SCHEDULER_ENABLED else "off",
        "demo": "ready" if await _demo_ready() else "pending",
    }
