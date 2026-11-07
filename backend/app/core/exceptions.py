"""业务异常定义：服务层抛业务异常，接口层统一转成 HTTP 响应。"""

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    message = "请求处理失败"

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class BadRequest(AppError):
    status_code = 400
    message = "请求参数有误"


class Unauthorized(AppError):
    status_code = 401
    message = "未认证或登录已过期"


class Forbidden(AppError):
    status_code = 403
    message = "没有操作权限"


class NotFound(AppError):
    status_code = 404
    message = "资源不存在"


class Conflict(AppError):
    status_code = 409
    message = "资源已存在"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """全局异常处理：统一返回 {"detail": "..."}，与前端拦截器约定一致。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
