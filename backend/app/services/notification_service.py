"""站内通知业务逻辑：生成（带去重）、列表、未读数、标记已读。

定时任务与业务动作都通过 ``create_notification`` 落库；去重窗口用于避免
同一条提醒每天被重复推送（同一对象同一用户在一个窗口内只留一条）。
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import CLIENT_VISIBLE_TYPES


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    content: str | None = None,
    type: str = "system",
    related_type: str | None = None,
    related_id: int | None = None,
    dedupe_hours: int = 0,
) -> Notification | None:
    """创建一条通知；``dedupe_hours`` > 0 时同对象同用户在窗口内不重复推送。

    返回新建的通知；命中去重规则时返回 ``None``。
    """
    if dedupe_hours > 0 and related_id is not None:
        since = datetime.now() - timedelta(hours=dedupe_hours)
        exists = await db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.type == type,
                Notification.related_type == related_type,
                Notification.related_id == related_id,
                Notification.created_at >= since,
            )
        )
        if exists is not None:
            return None

    notice = Notification(
        user_id=user_id,
        title=title,
        content=content,
        type=type,
        is_read=False,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(notice)
    await db.flush()
    return notice


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: int,
    is_read: bool | None = None,
    type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, int, list[Notification]]:
    """当前用户的通知列表，同时返回未读总数。"""
    if page < 1 or not 1 <= page_size <= 100:
        raise BadRequest("分页参数不合法")

    base = select(Notification).where(Notification.user_id == user_id)
    if is_read is not None:
        base = base.where(Notification.is_read.is_(is_read))
    if type:
        base = base.where(Notification.type == type)

    total = (
        await db.scalar(select(func.count()).select_from(base.subquery()))
    ) or 0
    unread = (
        await db.scalar(
            select(func.count()).where(
                Notification.user_id == user_id, Notification.is_read.is_(False)
            )
        )
    ) or 0
    rows = (
        (
            await db.execute(
                base.order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return int(total), int(unread), list(rows)


async def count_unread(db: AsyncSession, user_id: int) -> int:
    """未读通知数量。"""
    value = await db.scalar(
        select(func.count()).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
    )
    return int(value or 0)


async def mark_read(
    db: AsyncSession, notification_id: int, user_id: int
) -> Notification:
    """标记单条通知已读（仅本人）。"""
    notice = await db.get(Notification, notification_id)
    if notice is None:
        raise NotFound("通知不存在")
    if notice.user_id != user_id:
        raise Forbidden("无权操作该通知")
    if not notice.is_read:
        notice.is_read = True
        await db.commit()
        await db.refresh(notice)
    return notice


async def mark_all_read(db: AsyncSession, user_id: int) -> int:
    """把当前用户的未读通知全部标记为已读，返回更新条数。"""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def delete_notification(
    db: AsyncSession, notification_id: int, user_id: int
) -> None:
    """删除单条通知（仅本人）。"""
    notice = await db.get(Notification, notification_id)
    if notice is None:
        raise NotFound("通知不存在")
    if notice.user_id != user_id:
        raise Forbidden("无权操作该通知")
    await db.delete(notice)
    await db.commit()


async def list_client_notifications(
    db: AsyncSession,
    *,
    current: User,
    is_read: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, int, list[Notification]]:
    """客户端通知列表：只下发与本人案件相关的对外类型。

    对外的类型见 ``CLIENT_VISIBLE_TYPES``（开庭/期限/缴费/合同），
    律所内部的跟进提醒、系统广播不会出现在客户端。
    """
    if current.role != "client":
        raise Forbidden("仅客户可查看")
    if page < 1 or not 1 <= page_size <= 100:
        raise BadRequest("分页参数不合法")

    base = select(Notification).where(
        Notification.user_id == current.id,
        Notification.type.in_(CLIENT_VISIBLE_TYPES),
    )
    if is_read is not None:
        base = base.where(Notification.is_read.is_(is_read))

    total = (
        await db.scalar(select(func.count()).select_from(base.subquery()))
    ) or 0
    unread = (
        await db.scalar(
            select(func.count()).where(
                Notification.user_id == current.id,
                Notification.is_read.is_(False),
                Notification.type.in_(CLIENT_VISIBLE_TYPES),
            )
        )
    ) or 0
    rows = (
        (
            await db.execute(
                base.order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return int(total), int(unread), list(rows)


async def count_client_unread(db: AsyncSession, current: User) -> int:
    """客户端未读通知数（仅对外类型）。"""
    if current.role != "client":
        raise Forbidden("仅客户可查看")
    value = await db.scalar(
        select(func.count()).where(
            Notification.user_id == current.id,
            Notification.is_read.is_(False),
            Notification.type.in_(CLIENT_VISIBLE_TYPES),
        )
    )
    return int(value or 0)
