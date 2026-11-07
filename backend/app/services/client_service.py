"""客户关系管理业务逻辑：客户档案 CRUD 与跟进记录。"""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Conflict, Forbidden, NotFound
from app.models.client import ClientProfile
from app.models.follow import FollowRecord
from app.models.user import User
from app.schemas.client import ClientCreate, ClientUpdate, FollowCreate


async def resolve_client_user_id(db: AsyncSession, phone: str | None) -> int | None:
    """按手机号匹配客户登录账号（role=client），用于打通档案与账号。

    - 匹配到则返回该账号的 user.id；否则返回 None。
    - 手机号作为客户账号的唯一标识（自助注册时 username=phone）。
    """
    if not phone:
        return None
    user = await db.scalar(
        select(User).where(User.role == "client", User.phone == phone)
    )
    return user.id if user else None


async def list_clients(
    db: AsyncSession,
    *,
    current: User,
    keyword: str | None = None,
    status: str | None = None,
    level: str | None = None,
    source: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[ClientProfile]]:
    """分页查询客户，按角色做行级隔离。

    律师只能看到自己负责（owner）的客户；管理员看到全部。
    """
    if page < 1:
        raise BadRequest("页码必须大于等于 1")
    if not 1 <= page_size <= 100:
        raise BadRequest("每页数量需在 1~100 之间")

    stmt = select(ClientProfile)

    if current.role == "lawyer":
        stmt = stmt.where(ClientProfile.lawyer_id == current.id)

    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                ClientProfile.name.like(like),
                ClientProfile.phone.like(like),
                ClientProfile.id_no.like(like),
            )
        )
    if status:
        stmt = stmt.where(ClientProfile.status == status)
    if level:
        stmt = stmt.where(ClientProfile.level == level)
    if source:
        stmt = stmt.where(ClientProfile.source_channel == source)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (
            await db.execute(
                stmt.order_by(ClientProfile.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return total or 0, list(rows)


async def get_client(db: AsyncSession, client_id: int, current: User) -> ClientProfile:
    """读取单个客户，同样按角色隔离。"""
    client = await db.get(ClientProfile, client_id)
    if client is None:
        raise NotFound("客户不存在")
    if current.role == "lawyer" and client.lawyer_id != current.id:
        raise Forbidden("无权查看该客户")
    return client


async def _claim_client(
    db: AsyncSession,
    client: ClientProfile,
    payload: ClientCreate,
    lawyer_id: int | None,
    linked_user_id: int | None,
) -> ClientProfile:
    """认领已存在的档案（客户自助注册时自动生成的那条）。

    只覆盖请求里显式传入的字段，未传的保持原值——避免律师新建客户时
    把注册档案里已有的分级、状态等信息冲掉。
    """
    provided = payload.model_dump(exclude_unset=True)
    client.lawyer_id = lawyer_id
    if linked_user_id:
        client.user_id = linked_user_id
    for field in (
        "name",
        "client_type",
        "id_no",
        "gender",
        "address",
        "source_channel",
        "level",
        "status",
        "remark",
    ):
        value = provided.get(field)
        if value not in (None, ""):
            setattr(client, field, value)

    await db.commit()
    await db.refresh(client)
    return client


async def create_client(
    db: AsyncSession, payload: ClientCreate, current: User
) -> ClientProfile:
    """新增客户。

    律师默认归属自己；管理员可指定负责律师（lawyer_id）。
    """
    lawyer_id = payload.lawyer_id
    if current.role == "lawyer":
        lawyer_id = current.id
    elif lawyer_id is not None:
        # 管理员指定了负责律师，校验其确为律师
        owner = await db.get(User, lawyer_id)
        if owner is None or owner.role != "lawyer":
            raise BadRequest("负责律师不存在或角色不正确")

    # 手机号自动匹配客户登录账号，打通档案与账号（供客户端「我的案件」查询）
    linked_user_id = await resolve_client_user_id(db, payload.phone)

    # 客户自助注册时已自动建档，这里按手机号复用，避免同一客户出现两条档案
    if payload.phone:
        existing = await db.scalar(
            select(ClientProfile)
            .where(ClientProfile.phone == payload.phone)
            .order_by(ClientProfile.id.asc())
        )
        if existing is not None:
            if existing.lawyer_id not in (None, lawyer_id):
                raise Conflict("该手机号已有客户档案并归属其他律师，请核对后再录入")
            return await _claim_client(
                db, existing, payload, lawyer_id, linked_user_id
            )

    client = ClientProfile(
        name=payload.name,
        client_type=payload.client_type,
        id_no=payload.id_no,
        gender=payload.gender,
        phone=payload.phone,
        address=payload.address,
        source_channel=payload.source_channel,
        level=payload.level,
        status=payload.status,
        lawyer_id=lawyer_id,
        user_id=linked_user_id,
        remark=payload.remark,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def update_client(
    db: AsyncSession, client_id: int, payload: ClientUpdate, current: User
) -> ClientProfile:
    """修改客户，仅更新传入的字段。"""
    client = await get_client(db, client_id, current)

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise BadRequest("没有需要更新的字段")

    # 管理员可改负责律师；律师改自己客户时不改归属
    if "lawyer_id" in data:
        if current.role == "lawyer":
            data.pop("lawyer_id")
        else:
            lid = data["lawyer_id"]
            if lid is not None:
                owner = await db.get(User, lid)
                if owner is None or owner.role != "lawyer":
                    raise BadRequest("负责律师不存在或角色不正确")

    for field, value in data.items():
        setattr(client, field, value)

    # 手机号变更时重新匹配客户登录账号，保持档案-账号关联最新
    if "phone" in data:
        client.user_id = await resolve_client_user_id(db, client.phone)

    await db.commit()
    await db.refresh(client)
    return client


async def delete_client(db: AsyncSession, client_id: int, current: User) -> None:
    """删除客户（仅管理员）。删除前校验无跟进记录关联。"""
    if current.role != "admin":
        raise Forbidden("只有管理员可以删除客户")

    client = await db.get(ClientProfile, client_id)
    if client is None:
        raise NotFound("客户不存在")

    follow_count = await db.scalar(
        select(func.count())
        .select_from(FollowRecord)
        .where(FollowRecord.client_id == client_id)
    )
    if follow_count:
        raise BadRequest(f"该客户存在 {follow_count} 条跟进记录，请先删除跟进记录")

    await db.delete(client)
    await db.commit()


async def add_follow(
    db: AsyncSession, client_id: int, payload: FollowCreate, current: User
) -> FollowRecord:
    """给客户添加跟进记录。"""
    client = await get_client(db, client_id, current)

    follow = FollowRecord(
        client_id=client.id,
        user_id=current.id,
        content=payload.content,
        method=payload.method,
        next_follow_date=payload.next_follow_date,
    )
    db.add(follow)
    await db.commit()
    await db.refresh(follow)
    return follow


async def list_follows(
    db: AsyncSession, client_id: int, current: User
) -> list[FollowRecord]:
    """查询客户的跟进记录（按时间倒序）。"""
    await get_client(db, client_id, current)  # 复用行级隔离校验

    rows = (
        (
            await db.execute(
                select(FollowRecord)
                .where(FollowRecord.client_id == client_id)
                .order_by(FollowRecord.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def iter_clients_for_export(
    db: AsyncSession, current: User
) -> list[ClientProfile]:
    """导出用：按角色拉取全量客户（不分页）。"""
    stmt = select(ClientProfile)
    if current.role == "lawyer":
        stmt = stmt.where(ClientProfile.lawyer_id == current.id)
    rows = (
        (await db.execute(stmt.order_by(ClientProfile.created_at.desc())))
        .scalars()
        .all()
    )
    return list(rows)


async def clients_with_upcoming_follow(
    db: AsyncSession, current: User
) -> list[ClientProfile]:
    """待跟进客户：存在下次跟进日期 >= 今天的客户。

    预留能力，供后续「待跟进列表」使用；本模块路由暂未挂载。
    """
    stmt = select(ClientProfile).where(
        ClientProfile.id.in_(
            select(FollowRecord.client_id).where(
                FollowRecord.next_follow_date >= date.today()
            )
        )
    )
    if current.role == "lawyer":
        stmt = stmt.where(ClientProfile.lawyer_id == current.id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
