"""系统管理路由：账号管理与操作日志查询（仅管理员）。"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.admin import (
    AdminUserListOut,
    AdminUserOut,
    LawyerCreateIn,
    OperationLogListOut,
    PasswordResetIn,
    UserStatusIn,
)
from app.services import admin_service, audit_service

router = APIRouter()

# 账号管理与日志查询一律仅限管理员
AdminOnly = Annotated[User, Depends(require_role("admin"))]


def _to_out(
    user: User,
    case_count: int = 0,
    profile: tuple[int, str] | None = None,
) -> AdminUserOut:
    """把 ORM 对象转成列表输出，附带承办案件数与客户建档情况。"""
    return AdminUserOut(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        role=user.role,
        phone=user.phone,
        email=user.email,
        status=user.status,
        created_at=user.created_at,
        case_count=case_count,
        profile_id=profile[0] if profile else None,
        profile_name=profile[1] if profile else None,
    )


@router.get("/users", response_model=AdminUserListOut, summary="账号列表（分页）")
async def list_users(
    db: DbSession,
    admin: AdminOnly,
    role: str | None = Query(default=None, description="角色：client/lawyer/admin"),
    keyword: str | None = Query(default=None, description="账号/姓名/手机模糊搜索"),
    status: int | None = Query(default=None, ge=0, le=1, description="1=正常 0=禁用"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> AdminUserListOut:
    """查询账号列表，律师额外返回承办案件数，客户额外返回建档情况。"""
    total, rows = await admin_service.list_users(
        db,
        role=role,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    lawyer_ids = [u.id for u in rows if u.role == "lawyer"]
    counts = await admin_service.lawyer_case_counts(db, lawyer_ids)
    profiles = await admin_service.client_profile_map(db, rows)
    return AdminUserListOut(
        total=total,
        items=[
            _to_out(u, counts.get(u.id, 0), profiles.get(u.id))
            for u in rows
        ],
    )


@router.post(
    "/users/lawyers",
    response_model=AdminUserOut,
    status_code=201,
    summary="开通律师账号",
)
async def create_lawyer(
    payload: LawyerCreateIn,
    request: Request,
    db: DbSession,
    admin: AdminOnly,
) -> AdminUserOut:
    """开通一个律师账号，初始状态为启用。"""
    user = await admin_service.create_lawyer(
        db,
        username=payload.username,
        password=payload.password,
        real_name=payload.real_name,
        phone=payload.phone,
        email=payload.email,
    )
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_CREATE,
        target=f"user:{user.id}",
        detail=f"开通律师账号 {user.username}（{user.real_name}）",
        ip=client_ip(request),
    )
    return _to_out(user)


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserOut,
    summary="启用/禁用账号",
)
async def update_user_status(
    user_id: int,
    payload: UserStatusIn,
    request: Request,
    db: DbSession,
    admin: AdminOnly,
) -> AdminUserOut:
    """禁用后该账号无法登录（登录时校验 status）。"""
    user = await admin_service.set_user_status(
        db, user_id=user_id, status=payload.status, current=admin
    )
    verb = "启用" if payload.status == 1 else "禁用"
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_UPDATE,
        target=f"user:{user.id}",
        detail=f"{verb}账号 {user.username}",
        ip=client_ip(request),
    )
    return _to_out(user)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminUserOut,
    summary="重置账号密码",
)
async def reset_user_password(
    user_id: int,
    payload: PasswordResetIn,
    request: Request,
    db: DbSession,
    admin: AdminOnly,
) -> AdminUserOut:
    """由管理员重置密码，无需旧密码。"""
    user = await admin_service.reset_password(
        db, user_id=user_id, new_password=payload.new_password, current=admin
    )
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_UPDATE,
        target=f"user:{user.id}",
        detail=f"重置账号 {user.username} 的密码",
        ip=client_ip(request),
    )
    return _to_out(user)


@router.get("/logs", response_model=OperationLogListOut, summary="操作日志（分页）")
async def list_logs(
    db: DbSession,
    admin: AdminOnly,
    action: str | None = Query(default=None, description="动作：login/create/update/..."),
    keyword: str | None = Query(default=None, description="对象/说明/IP/操作人模糊搜索"),
    user_id: int | None = Query(default=None, description="操作人 ID"),
    start: Annotated[date | None, Query(description="开始日期（含）")] = None,
    end: Annotated[date | None, Query(description="结束日期（含）")] = None,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> OperationLogListOut:
    """按动作、操作人、时间范围查询审计日志。"""
    total, items = await admin_service.list_logs(
        db,
        action=action,
        keyword=keyword,
        user_id=user_id,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )
    return OperationLogListOut(total=total, items=items)
