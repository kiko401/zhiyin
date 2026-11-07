from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.core.responses import ApiError, ok
from app.services import spec_service

router = APIRouter(tags=["spec"])


@router.get("/api/spec/{spec_uid}")
async def get_spec(spec_uid: str, user_id: int = Depends(require_user)):
    row = await spec_service.get_by_uid(spec_uid)
    if not row or row.user_id != user_id:
        raise ApiError(40401, "规格不存在", status_code=404)
    return ok({
        "spec_uid": row.spec_uid,
        "task_type": row.task_type,
        "version": row.version,
        "spec": row.spec,
        "status": row.status,
    })


# 确认即建任务（202 + task_id）在任务引擎接入时实现（api/task.py）
