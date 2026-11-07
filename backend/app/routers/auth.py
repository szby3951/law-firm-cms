"""认证与权限路由：注册、登录、获取当前用户。"""

from fastapi import APIRouter, Request

from app.dependencies import CurrentUser, DbSession, client_ip
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services import audit_service, auth_service

router = APIRouter()


@router.post(
    "/register",
    response_model=UserOut,
    summary="客户端注册",
    tags=["认证与权限"],
)
async def register(payload: RegisterIn, request: Request, db: DbSession) -> UserOut:
    """客户自助注册，账号角色固定为 client。"""
    user = await auth_service.register(db, payload)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_REGISTER,
        target=f"user:{user.id}",
        detail=f"注册账号 {user.username}",
        ip=client_ip(request),
    )
    return user


@router.post(
    "/login",
    response_model=TokenOut,
    summary="登录",
    tags=["认证与权限"],
)
async def login(payload: LoginIn, request: Request, db: DbSession) -> TokenOut:
    """校验账号密码，返回 JWT 令牌与用户信息。"""
    user = await auth_service.authenticate(db, payload)
    token = auth_service.build_token(user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_LOGIN,
        target=f"user:{user.id}",
        detail=f"角色 {user.role}",
        ip=client_ip(request),
    )
    return token


@router.get(
    "/me",
    response_model=UserOut,
    summary="获取当前登录用户",
    tags=["认证与权限"],
)
async def read_me(user: CurrentUser) -> UserOut:
    """校验令牌并返回当前用户信息。"""
    return user
