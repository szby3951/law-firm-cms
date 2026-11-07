"""认证业务逻辑：注册、登录、获取当前用户。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, Forbidden, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    token_expire_seconds,
    verify_password,
)
from app.models.client import ClientProfile
from app.models.user import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

# 律所内部账号由管理员开通，不允许自助注册
STAFF_ROLES = ("lawyer", "admin")


async def register(db: AsyncSession, payload: RegisterIn) -> User:
    """客户端注册：创建 role=client 的账号，并同步建立客户档案。

    注册即建档（口径要求）：账号与档案在同一事务里落库，客户登录后即可被
    律师在客户列表中检索到，不会出现「有账号、无档案」的孤立状态。
    档案的负责律师留空，由管理员在客户管理里指派；来源记为「网络」，
    备注写清是自助注册，便于律师区分线索来源。
    """
    existing = await db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise Conflict("该账号已被注册")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name or payload.username,
        role="client",
        phone=payload.phone
        or (payload.username if payload.username.isdigit() else None),
        email=payload.email,
        status=1,
    )
    db.add(user)
    # flush 先拿到自增 id，档案才能绑定 user_id；随后与账号一起 commit
    await db.flush()

    # 律师可能已经手工录入过这位客户（档案 exists 但无账号），此处直接绑定，
    # 不再重复建档；只有确实没有档案时才新建。
    linked = None
    if user.phone:
        linked = await db.scalar(
            select(ClientProfile)
            .where(
                ClientProfile.phone == user.phone,
                ClientProfile.user_id.is_(None),
            )
            .order_by(ClientProfile.id.asc())
        )
    if linked is not None:
        linked.user_id = user.id
    else:
        db.add(
            ClientProfile(
                user_id=user.id,
                name=user.real_name,
                client_type="personal",
                phone=user.phone,
                source_channel="网络",
                level="normal",
                status="potential",
                remark="客户自助注册，系统自动建档",
            )
        )
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, payload: LoginIn) -> User:
    """校验账号密码，返回用户对象。"""
    user = await db.scalar(select(User).where(User.username == payload.username))
    # 用户不存在与密码错误返回同一提示，避免账号枚举
    if user is None or not verify_password(payload.password, user.password_hash):
        raise Unauthorized("账号或密码错误")
    if user.status != 1:
        raise Forbidden("账号已被禁用，请联系管理员")
    return user


def build_token(user: User) -> TokenOut:
    """签发令牌并组装响应体。"""
    token = create_access_token(user.id, user.role)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        expires_in=token_expire_seconds(),
        user=UserOut.model_validate(user),
    )


async def get_current_user(db: AsyncSession, user_id: int) -> User:
    """按 ID 读取用户（供依赖注入使用）。"""
    user = await db.get(User, user_id)
    if user is None:
        raise Unauthorized("用户不存在")
    return user
