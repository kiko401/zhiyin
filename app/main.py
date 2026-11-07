from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import auth, chat, spec, task
from app.core import config, security
from app.core.db import check_db
from app.core.responses import api_error_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services import lexicon as lexicon_svc

    await lexicon_svc.warmup()
    yield


app = FastAPI(title="知音 Zhiyin", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(spec.router)
app.include_router(task.router)
app.add_exception_handler(HTTPException, api_error_handler)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"code": 40401, "message": "资源不存在", "data": None})


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
        "demo": "pending",
    }
