"""系统管理服务：账号管理（律师开通/禁用/重置密码）与操作日志查询。"""

from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.core.security import hash_password
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.log import OperationLog
from app.models.user import User
from app.schemas.admin import OperationLogOut

# 允许查询/操作的角色，防止前端传入脏数据把结果集清空
VALID_ROLES = ("client", "lawyer", "admin")


def _escape_like(keyword: str) -> str:
    """转义 LIKE 通配符，避免用户输入的 % _ 把查询放大。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    db: AsyncSession,
    *,
    role: str | None = None,
    keyword: str | None = None,
    status: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[User]]:
    """分页查询账号，可按角色/状态筛选，关键词匹配账号、姓名、手机。"""
    if role and role not in VALID_ROLES:
        raise BadRequest("角色参数不正确")

    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status is not None:
        stmt = stmt.where(User.status == status)
    if keyword:
        like = f"%{_escape_like(keyword)}%"
        stmt = stmt.where(
            or_(
                User.username.like(like),
                User.real_name.like(like),
                User.phone.like(like),
            )
        )

    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(User.created_at.desc(), User.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return total, list(rows)


async def lawyer_case_counts(db: AsyncSession, user_ids: list[int]) -> dict[int, int]:
    """批量取律师的承办案件数（主办+协办），避免列表 N+1。"""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(CaseLawyer.lawyer_id, func.count(CaseLawyer.case_id))
            .where(CaseLawyer.lawyer_id.in_(user_ids))
            .group_by(CaseLawyer.lawyer_id)
        )
    ).all()
    return {int(lawyer_id): int(count) for lawyer_id, count in rows}


async def client_profile_map(
    db: AsyncSession, users: list[User]
) -> dict[int, tuple[int, str]]:
    """批量取客户账号对应的客户档案：user_id 优先，手机号兜底。

    返回 ``{user_id: (profile_id, profile_name)}``。客户自助注册不建档，
    律师在客户管理按手机号建档后才产生档案，这里用来标记「待建档」。
    """
    clients = [u for u in users if u.role == "client"]
    if not clients:
        return {}

    ids = [u.id for u in clients]
    phones = [u.phone for u in clients if u.phone]
    cond = ClientProfile.user_id.in_(ids)
    if phones:
        cond = or_(cond, ClientProfile.phone.in_(phones))

    rows = (
        await db.execute(
            select(
                ClientProfile.user_id, ClientProfile.phone, ClientProfile.id, ClientProfile.name
            )
            .where(cond)
            .order_by(ClientProfile.id.asc())
        )
    ).all()

    by_user: dict[int, tuple[int, str]] = {}
    by_phone: dict[str, tuple[int, str]] = {}
    for user_id, phone, profile_id, name in rows:
        if user_id:
            by_user.setdefault(int(user_id), (profile_id, name))
        if phone:
            by_phone.setdefault(phone, (profile_id, name))

    result: dict[int, tuple[int, str]] = {}
    for user in clients:
        hit = by_user.get(user.id) or (by_phone.get(user.phone) if user.phone else None)
        if hit:
            result[user.id] = hit
    return result


async def create_lawyer(
    db: AsyncSession, *, username: str, password: str, real_name: str,
    phone: str | None, email: str | None,
) -> User:
    """开通律师账号，初始状态为启用。"""
    exists = await db.scalar(select(User.id).where(User.username == username))
    if exists:
        raise Conflict("账号已存在，请更换工号")

    user = User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        role="lawyer",
        phone=phone,
        email=email,
        status=1,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user(db: AsyncSession, user_id: int) -> User:
    """按 ID 取账号，不存在抛 404。"""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("账号不存在")
    return user


async def set_user_status(
    db: AsyncSession, *, user_id: int, status: int, current: User
) -> User:
    """启用/禁用账号。

    - 不能操作自己，避免管理员把自己锁在门外
    - 不能把最后一个启用的管理员禁用掉
    """
    user = await get_user(db, user_id)
    if user.id == current.id:
        raise BadRequest("不能修改自己的账号状态")

    if user.role == "admin" and status == 0:
        active_admins = int(
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.status == 1)
            )
            or 0
        )
        if active_admins <= 1:
            raise BadRequest("系统至少需要保留一个启用的管理员")

    user.status = status
    await db.commit()
    await db.refresh(user)
    return user


async def reset_password(
    db: AsyncSession, *, user_id: int, new_password: str, current: User
) -> User:
    """重置他人密码（管理员不能在此重置其他管理员的密码）。"""
    user = await get_user(db, user_id)
    if user.role == "admin" and user.id != current.id:
        raise BadRequest("不能重置其他管理员的密码")

    user.password_hash = hash_password(new_password)
    await db.commit()
    await db.refresh(user)
    return user


async def list_logs(
    db: AsyncSession,
    *,
    action: str | None = None,
    keyword: str | None = None,
    user_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[OperationLogOut]]:
    """分页查询操作日志，关联操作人账号与姓名。"""
    stmt = select(OperationLog, User.username, User.real_name).outerjoin(
        User, User.id == OperationLog.user_id
    )
    if action:
        stmt = stmt.where(OperationLog.action == action)
    if user_id:
        stmt = stmt.where(OperationLog.user_id == user_id)
    if start:
        stmt = stmt.where(OperationLog.created_at >= datetime.combine(start, time.min))
    if end:
        stmt = stmt.where(OperationLog.created_at <= datetime.combine(end, time.max))
    if keyword:
        like = f"%{_escape_like(keyword)}%"
        stmt = stmt.where(
            or_(
                OperationLog.target.like(like),
                OperationLog.detail.like(like),
                OperationLog.ip.like(like),
                User.username.like(like),
                User.real_name.like(like),
            )
        )

    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        await db.execute(
            stmt.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        OperationLogOut(
            id=log.id,
            user_id=log.user_id,
            username=username,
            real_name=real_name,
            action=log.action,
            target=log.target,
            detail=log.detail,
            ip=log.ip,
            created_at=log.created_at,
        )
        for log, username, real_name in rows
    ]
    return total, items
