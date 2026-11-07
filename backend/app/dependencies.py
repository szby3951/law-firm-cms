"""FastAPI 依赖注入：数据库会话、JWT 鉴权、角色校验。"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User

# auto_error=False：缺少 Token 时返回 None，由我们自行抛出 401，
# 这样可以给出更贴合业务的中文提示
bearer_scheme = HTTPBearer(auto_error=False)

# 便捷别名
DbSession = Annotated[AsyncSession, Depends(get_db)]
BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def client_ip(request: Request) -> str | None:
    """取客户端 IP，优先使用反向代理透传的 X-Forwarded-For。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_current_user(db: DbSession, credentials: BearerToken) -> User:
    """解析 JWT 并返回当前登录用户。"""
    if credentials is None or not credentials.credentials:
        raise Unauthorized("请先登录")

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise Unauthorized("登录状态无效或已过期")

    subject = payload.get("sub")
    if not subject:
        raise Unauthorized("登录状态无效")

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise Unauthorized("登录状态无效")

    user = await db.get(User, user_id)
    if user is None:
        raise Unauthorized("用户不存在")
    if user.status != 1:
        raise Forbidden("账号已被禁用，请联系管理员")
    return user


# 便捷别名，供路由使用
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """生成角色校验依赖。

    用法::

        @router.get("/clients")
        async def list_clients(user: Annotated[User, Depends(require_role("lawyer", "admin"))]):
            ...
    """

    async def _role_checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise Forbidden("没有操作权限")
        return user

    return _role_checker
