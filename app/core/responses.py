from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def ok(data=None):
    return {"code": 0, "message": "success", "data": data}


class ApiError(HTTPException):
    """业务错误：按错误码表返回统一包络。"""

    def __init__(self, code: int, message: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


async def api_error_handler(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": 40000, "message": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": detail["code"], "message": detail["message"], "data": None},
    )
