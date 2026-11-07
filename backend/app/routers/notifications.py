"""站内通知路由：列表、未读数、标记已读、手动触发扫描。

通知按接收人隔离：任何登录用户只能看到发给自己的通知。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUser, DbSession, require_role
from app.models.user import User
from app.scheduler import run_scan
from app.schemas.notification import (
    NotificationListOut,
    NotificationOut,
    NotificationReadAllOut,
    NotificationUnreadOut,
    ScanResultOut,
)
from app.services import notification_service

router = APIRouter()

AdminOnly = Annotated[User, Depends(require_role("admin"))]


@router.get("", response_model=NotificationListOut, summary="我的通知列表")
async def list_notifications(
    db: DbSession,
    user: CurrentUser,
    is_read: bool | None = Query(default=None, description="是否已读"),
    type: str | None = Query(default=None, description="通知类型"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> NotificationListOut:
    """当前登录用户的通知（按创建时间倒序），附带未读总数。"""
    total, unread, items = await notification_service.list_notifications(
        db,
        user_id=user.id,
        is_read=is_read,
        type=type,
        page=page,
        page_size=page_size,
    )
    return NotificationListOut(
        total=total,
        unread=unread,
        items=[NotificationOut.model_validate(x) for x in items],
    )


@router.get(
    "/unread-count", response_model=NotificationUnreadOut, summary="未读通知数"
)
async def unread_count(db: DbSession, user: CurrentUser) -> NotificationUnreadOut:
    """红点用：当前用户未读通知数量。"""
    return NotificationUnreadOut(
        count=await notification_service.count_unread(db, user.id)
    )


@router.patch(
    "/read-all", response_model=NotificationReadAllOut, summary="全部标记已读"
)
async def read_all(db: DbSession, user: CurrentUser) -> NotificationReadAllOut:
    """把当前用户的全部未读通知置为已读。"""
    updated = await notification_service.mark_all_read(db, user.id)
    return NotificationReadAllOut(updated=updated)


@router.post("/scan", response_model=ScanResultOut, summary="手动触发提醒扫描")
async def scan_reminders(user: AdminOnly) -> ScanResultOut:
    """管理员手动跑一轮提醒扫描（定时任务之外的补偿入口，便于验收/补推）。"""
    counts = await run_scan()
    return ScanResultOut(
        schedule=counts.get("schedule", 0),
        payment=counts.get("payment", 0),
        follow=counts.get("follow", 0),
        contract=counts.get("contract", 0),
        total=counts.get("total", 0),
        scanned_at=datetime.now(),
    )


@router.patch(
    "/{notification_id}/read", response_model=NotificationOut, summary="标记已读"
)
async def mark_read(
    notification_id: int, db: DbSession, user: CurrentUser
) -> NotificationOut:
    """标记单条通知已读（仅本人的通知）。"""
    notice = await notification_service.mark_read(db, notification_id, user.id)
    return NotificationOut.model_validate(notice)


@router.delete("/{notification_id}", status_code=204, summary="删除通知")
async def delete_notification(
    notification_id: int, db: DbSession, user: CurrentUser
) -> None:
    """删除单条通知（仅本人的通知）。"""
    await notification_service.delete_notification(db, notification_id, user.id)
