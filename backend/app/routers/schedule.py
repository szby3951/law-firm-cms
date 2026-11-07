"""日程路由：日历/列表/今日待办/新增/修改/状态标记/删除。

权限：仅律师与管理员可访问；客户通过 ``/api/my/notifications`` 接收对外提醒。
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import CurrentUser, DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.schedule import (
    CalendarDayOut,
    ScheduleCalendarOut,
    ScheduleIn,
    ScheduleListOut,
    ScheduleOut,
    ScheduleStatusIn,
)
from app.services import audit_service, schedule_service

router = APIRouter()

LawyerOrAdmin = Annotated[User, Depends(require_role("lawyer", "admin"))]


def _month_last_day(value: date) -> date:
    """取某月最后一天。"""
    first_next = (value.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next - timedelta(days=1)


@router.get(
    "/calendar",
    response_model=ScheduleCalendarOut,
    summary="日历数据（按月/周查询）",
)
async def schedule_calendar(
    db: DbSession,
    user: CurrentUser,
    start: Annotated[date | None, Query(description="开始日期，缺省本月 1 日")] = None,
    end: Annotated[
        date | None, Query(description="结束日期，缺省本月最后一天")
    ] = None,
) -> ScheduleCalendarOut:
    """返回区间内按天分组的日程，供前端渲染月/周/日视图。"""
    begin = start or date.today().replace(day=1)
    finish = end or _month_last_day(begin)

    begin, finish, rows = await schedule_service.list_calendar(
        db, current=user, start=begin, end=finish
    )

    grouped: dict[date, list[ScheduleOut]] = {}
    for row in rows:
        day = row.event_date.date()
        grouped.setdefault(day, []).append(ScheduleOut.model_validate(row))

    days = [
        CalendarDayOut(date=day, count=len(items), items=items)
        for day, items in sorted(grouped.items())
    ]
    return ScheduleCalendarOut(
        start=begin,
        end=finish,
        total=len(rows),
        days=days,
    )


@router.get(
    "/today", response_model=list[ScheduleOut], summary="今日日程（首页待办）"
)
async def today_schedules(db: DbSession, user: CurrentUser) -> list[ScheduleOut]:
    """今日全部日程（不含已取消），供首页待办卡片展示。"""
    rows = await schedule_service.list_today(db, user)
    return [ScheduleOut.model_validate(r) for r in rows]


@router.get(
    "/upcoming",
    response_model=list[ScheduleOut],
    summary="未来待办日程",
)
async def upcoming_schedules(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=7, ge=1, le=60, description="未来天数"),
) -> list[ScheduleOut]:
    """未来 N 天内待办日程（开庭/期限等），按时间升序。"""
    rows = await schedule_service.list_upcoming(db, user, days)
    return [ScheduleOut.model_validate(r) for r in rows]


@router.get("", response_model=ScheduleListOut, summary="日程列表（分页）")
async def list_schedules(
    db: DbSession,
    user: CurrentUser,
    start: Annotated[date | None, Query(description="开始日期")] = None,
    end: Annotated[date | None, Query(description="结束日期")] = None,
    schedule_type: str | None = Query(default=None, description="日程类型"),
    status: str | None = Query(default=None, description="状态"),
    case_id: int | None = Query(default=None, description="关联案件ID"),
    user_id: int | None = Query(default=None, description="承办律师ID"),
    keyword: str | None = Query(default=None, description="标题关键词"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> ScheduleListOut:
    """分页查询日程，律师仅见本人及本人承办案件下的日程。"""
    total, items = await schedule_service.list_schedules(
        db,
        current=user,
        start=start,
        end=end,
        schedule_type=schedule_type,
        status=status,
        case_id=case_id,
        user_id=user_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ScheduleListOut(
        total=total, items=[ScheduleOut.model_validate(x) for x in items]
    )


@router.post("", response_model=ScheduleOut, summary="新增日程")
async def create_schedule(
    payload: ScheduleIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> ScheduleOut:
    """新增日程；关联案件时自动带出委托客户。"""
    schedule = await schedule_service.create_schedule(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"schedule:{schedule.id}",
        detail=f"新增日程「{schedule.title}」",
        ip=client_ip(request),
    )
    return ScheduleOut.model_validate(schedule)


@router.get("/{schedule_id}", response_model=ScheduleOut, summary="日程详情")
async def get_schedule(
    schedule_id: int, db: DbSession, user: CurrentUser
) -> ScheduleOut:
    """日程详情。"""
    schedule = await schedule_service.get_schedule(db, schedule_id, user)
    return ScheduleOut.model_validate(schedule)


@router.put("/{schedule_id}", response_model=ScheduleOut, summary="修改日程")
async def update_schedule(
    schedule_id: int,
    payload: ScheduleIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> ScheduleOut:
    """全量更新日程（未传的可空字段会被清空）。"""
    schedule = await schedule_service.update_schedule(
        db, schedule_id, payload, user
    )
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"schedule:{schedule.id}",
        detail=f"修改日程「{schedule.title}」",
        ip=client_ip(request),
    )
    return ScheduleOut.model_validate(schedule)


@router.patch(
    "/{schedule_id}/status", response_model=ScheduleOut, summary="标记日程状态"
)
async def update_schedule_status(
    schedule_id: int,
    payload: ScheduleStatusIn,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> ScheduleOut:
    """标记完成 / 取消 / 恢复待办。"""
    schedule = await schedule_service.update_status(
        db, schedule_id, payload, user
    )
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"schedule:{schedule.id}",
        detail=f"日程「{schedule.title}」状态 → {schedule.status}",
        ip=client_ip(request),
    )
    return ScheduleOut.model_validate(schedule)


@router.delete("/{schedule_id}", status_code=204, summary="删除日程")
async def delete_schedule(
    schedule_id: int, request: Request, db: DbSession, user: LawyerOrAdmin
) -> None:
    """删除日程（仅归属人或管理员）。"""
    await schedule_service.delete_schedule(db, schedule_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"schedule:{schedule_id}",
        detail=f"删除日程 #{schedule_id}",
        ip=client_ip(request),
    )
