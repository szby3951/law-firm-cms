"""日程业务逻辑：CRUD、日期范围查询、日历数据、状态标记。

权限约定（与案件模块一致）：

- 管理员：全所日程可见可改；
- 律师：可见「本人日程」以及「本人主办/协办案件下的日程」，
  但只有日程归属人（``user_id``）本人可修改/删除，避免互相覆盖安排；
- 客户：不能访问本模块，只能通过 ``/api/my/notifications`` 收到对外提醒。
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import ScheduleIn, ScheduleStatusIn

# 日历一次最多查询的天数，防止前端传入超大区间拖垮数据库
MAX_CALENDAR_DAYS = 366


def _day_start(value: date) -> datetime:
    """当天 00:00:00。"""
    return datetime.combine(value, time.min)


def _day_end(value: date) -> datetime:
    """当天 23:59:59.999999。"""
    return datetime.combine(value, time.max)


async def _get_schedule_or_404(db: AsyncSession, schedule_id: int) -> Schedule:
    """读取日程，不存在抛 404。"""
    schedule = await db.get(Schedule, schedule_id)
    if schedule is None:
        raise NotFound("日程不存在")
    return schedule


async def _lawyer_case_ids(db: AsyncSession, user_id: int) -> set[int]:
    """律师主办/协办的案件 id 集合。"""
    rows = (
        (
            await db.execute(
                select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def _scope_conditions(current: User, lawyer_case_ids: set[int]) -> list:
    """列表可见范围：管理员全量，律师限本人或本人承办案件。"""
    if current.role == "admin":
        return []
    if current.role != "lawyer":
        raise Forbidden("无权访问日程")
    conds = [Schedule.user_id == current.id]
    if lawyer_case_ids:
        conds.append(Schedule.case_id.in_(lawyer_case_ids))
    return [or_(*conds)]


async def _attach_refs(db: AsyncSession, schedules: list[Schedule]) -> list[Schedule]:
    """批量注入案件编号/标题、客户姓名、承办律师姓名。"""
    if not schedules:
        return schedules

    case_ids = {s.case_id for s in schedules if s.case_id}
    if case_ids:
        rows = (
            await db.execute(
                select(Case.id, Case.case_no, Case.title).where(
                    Case.id.in_(case_ids)
                )
            )
        ).all()
        case_map = {cid: (no, title) for cid, no, title in rows}
        for s in schedules:
            if s.case_id:
                no, title = case_map.get(s.case_id, (None, None))
                s.case_no = no
                s.case_title = title

    client_ids = {s.client_id for s in schedules if s.client_id}
    if client_ids:
        rows = (
            await db.execute(
                select(ClientProfile.id, ClientProfile.name).where(
                    ClientProfile.id.in_(client_ids)
                )
            )
        ).all()
        name_map = dict(rows)
        for s in schedules:
            if s.client_id:
                s.client_name = name_map.get(s.client_id)

    user_ids = {s.user_id for s in schedules if s.user_id}
    if user_ids:
        rows = (
            await db.execute(
                select(User.id, User.real_name).where(User.id.in_(user_ids))
            )
        ).all()
        lawyer_map = dict(rows)
        for s in schedules:
            s.lawyer_name = lawyer_map.get(s.user_id)

    return schedules


async def _resolve_case(
    db: AsyncSession, case_id: int | None, current: User
) -> Case | None:
    """校验关联案件存在，且律师有权在该案件下建日程。"""
    if case_id is None:
        return None
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("关联案件不存在")
    if current.role == "admin":
        return case
    rel = await db.scalar(
        select(CaseLawyer.case_id).where(
            CaseLawyer.case_id == case_id, CaseLawyer.lawyer_id == current.id
        )
    )
    if rel is None:
        raise Forbidden("无权在该案件下创建日程")
    return case


async def _resolve_client(
    db: AsyncSession, client_id: int | None
) -> ClientProfile | None:
    """校验关联客户存在。"""
    if client_id is None:
        return None
    client = await db.get(ClientProfile, client_id)
    if client is None:
        raise NotFound("关联客户不存在")
    return client


def _resolve_owner(payload_user_id: int | None, current: User) -> int:
    """日程归属人：缺省当前用户，仅管理员可指定他人。"""
    if payload_user_id is None or payload_user_id == current.id:
        return current.id
    if current.role != "admin":
        raise Forbidden("只能为本人创建日程")
    return payload_user_id


async def _check_owner_user(db: AsyncSession, user_id: int) -> None:
    """校验指定的承办律师是有效律师账号。"""
    user = await db.get(User, user_id)
    if user is None or user.role != "lawyer":
        raise BadRequest("指定的承办律师不存在或不是律师账号")
    if user.status != 1:
        raise BadRequest("该律师账号已被禁用")


def _apply_scope(stmt: Select, current: User, lawyer_case_ids: set[int]) -> Select:
    """给查询语句套上可见范围。"""
    conds = _scope_conditions(current, lawyer_case_ids)
    return stmt.where(*conds) if conds else stmt


async def list_schedules(
    db: AsyncSession,
    *,
    current: User,
    start: date | None = None,
    end: date | None = None,
    schedule_type: str | None = None,
    status: str | None = None,
    case_id: int | None = None,
    user_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Schedule]]:
    """日程列表：支持日期区间、类型、状态、案件、律师、关键词筛选。"""
    if start and end and end < start:
        raise BadRequest("结束日期不能早于开始日期")
    if not 1 <= page_size <= 100 or page < 1:
        raise BadRequest("分页参数不合法")

    lawyer_case_ids = (
        await _lawyer_case_ids(db, current.id) if current.role == "lawyer" else set()
    )
    stmt = _apply_scope(select(Schedule), current, lawyer_case_ids)

    if start:
        stmt = stmt.where(Schedule.event_date >= _day_start(start))
    if end:
        stmt = stmt.where(Schedule.event_date <= _day_end(end))
    if schedule_type:
        stmt = stmt.where(Schedule.schedule_type == schedule_type)
    if status:
        stmt = stmt.where(Schedule.status == status)
    if case_id:
        stmt = stmt.where(Schedule.case_id == case_id)
    if user_id:
        stmt = stmt.where(Schedule.user_id == user_id)
    if keyword:
        stmt = stmt.where(Schedule.title.like(f"%{keyword.strip()}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        (
            await db.execute(
                stmt.order_by(Schedule.event_date.asc(), Schedule.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = await _attach_refs(db, list(rows))
    return int(total), items


async def list_calendar(
    db: AsyncSession,
    *,
    current: User,
    start: date,
    end: date,
) -> tuple[date, date, list[Schedule]]:
    """日历数据：返回区间内全部日程（已按时间升序），由路由层按天分组。"""
    if end < start:
        raise BadRequest("结束日期不能早于开始日期")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise BadRequest(f"日历查询区间不能超过 {MAX_CALENDAR_DAYS} 天")

    lawyer_case_ids = (
        await _lawyer_case_ids(db, current.id) if current.role == "lawyer" else set()
    )
    stmt = _apply_scope(select(Schedule), current, lawyer_case_ids)
    stmt = stmt.where(
        Schedule.event_date >= _day_start(start),
        Schedule.event_date <= _day_end(end),
    )
    rows = (
        (
            await db.execute(
                stmt.order_by(Schedule.event_date.asc(), Schedule.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return start, end, await _attach_refs(db, list(rows))


async def list_today(db: AsyncSession, current: User) -> list[Schedule]:
    """今日日程（首页待办：今日开庭与待办事项）。"""
    today = date.today()
    lawyer_case_ids = (
        await _lawyer_case_ids(db, current.id) if current.role == "lawyer" else set()
    )
    stmt = _apply_scope(select(Schedule), current, lawyer_case_ids)
    stmt = stmt.where(
        Schedule.event_date >= _day_start(today),
        Schedule.event_date <= _day_end(today),
        Schedule.status != "cancelled",
    )
    rows = (
        (await db.execute(stmt.order_by(Schedule.event_date.asc()))).scalars().all()
    )
    return await _attach_refs(db, list(rows))


async def list_upcoming(
    db: AsyncSession, current: User, days: int = 7
) -> list[Schedule]:
    """未来 N 天的待办日程（首页待办卡片）。"""
    if not 1 <= days <= 60:
        raise BadRequest("天数需在 1~60 之间")
    now = datetime.now()
    lawyer_case_ids = (
        await _lawyer_case_ids(db, current.id) if current.role == "lawyer" else set()
    )
    stmt = _apply_scope(select(Schedule), current, lawyer_case_ids)
    # 起点用「此刻」以排除今天已过时段的逾期项；终点取第 N 天的 23:59:59，
    # 不用 now + N 天（精确 N×24 小时）——否则同一天上午的日程能进列表、
    # 晚上 9 点的却被漏掉，是否显示取决于用户几点打开工作台。
    stmt = stmt.where(
        Schedule.status == "pending",
        Schedule.event_date >= now,
        Schedule.event_date <= _day_end(date.today() + timedelta(days=days)),
    )
    rows = (
        (await db.execute(stmt.order_by(Schedule.event_date.asc()))).scalars().all()
    )
    return await _attach_refs(db, list(rows))


async def _assert_writable(
    db: AsyncSession, schedule: Schedule, current: User
) -> None:
    """写权限：管理员或日程归属人本人。"""
    if current.role == "admin":
        return
    if current.role != "lawyer":
        raise Forbidden("无权操作日程")
    if schedule.user_id != current.id:
        raise Forbidden("只能修改本人负责的日程")


async def get_schedule(
    db: AsyncSession, schedule_id: int, current: User
) -> Schedule:
    """日程详情（可见即可读，写权限另行校验）。"""
    schedule = await _get_schedule_or_404(db, schedule_id)
    if current.role not in ("admin", "lawyer"):
        raise Forbidden("无权查看日程")
    if current.role == "lawyer":
        visible = schedule.user_id == current.id
        if not visible and schedule.case_id:
            rel = await db.scalar(
                select(CaseLawyer.case_id).where(
                    CaseLawyer.case_id == schedule.case_id,
                    CaseLawyer.lawyer_id == current.id,
                )
            )
            visible = rel is not None
        if not visible:
            raise Forbidden("无权查看该日程")

    await _attach_refs(db, [schedule])
    return schedule


async def create_schedule(
    db: AsyncSession, payload: ScheduleIn, current: User
) -> Schedule:
    """新建日程：校验案件/客户，自动补全客户归属。"""
    case = await _resolve_case(db, payload.case_id, current)
    client_id = payload.client_id
    if case is not None:
        if client_id is not None and client_id != case.client_id:
            raise BadRequest("关联客户与案件的委托客户不一致")
        client_id = case.client_id
    else:
        await _resolve_client(db, client_id)

    owner_id = _resolve_owner(payload.user_id, current)
    if owner_id != current.id:
        await _check_owner_user(db, owner_id)

    schedule = Schedule(
        case_id=payload.case_id,
        client_id=client_id,
        user_id=owner_id,
        title=payload.title,
        schedule_type=payload.schedule_type,
        event_date=payload.event_date,
        remind_at=payload.remind_at,
        status=payload.status,
        remark=payload.remark,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    await _attach_refs(db, [schedule])
    return schedule


async def update_schedule(
    db: AsyncSession, schedule_id: int, payload: ScheduleIn, current: User
) -> Schedule:
    """全量更新日程（PUT）。"""
    schedule = await _get_schedule_or_404(db, schedule_id)
    await _assert_writable(db, schedule, current)

    case = await _resolve_case(db, payload.case_id, current)
    client_id = payload.client_id
    if case is not None:
        if client_id is not None and client_id != case.client_id:
            raise BadRequest("关联客户与案件的委托客户不一致")
        client_id = case.client_id
    else:
        await _resolve_client(db, client_id)

    owner_id = _resolve_owner(payload.user_id, current)
    if owner_id != current.id:
        await _check_owner_user(db, owner_id)

    schedule.case_id = payload.case_id
    schedule.client_id = client_id
    schedule.user_id = owner_id
    schedule.title = payload.title
    schedule.schedule_type = payload.schedule_type
    schedule.event_date = payload.event_date
    schedule.remind_at = payload.remind_at
    schedule.status = payload.status
    schedule.remark = payload.remark

    await db.commit()
    await db.refresh(schedule)
    await _attach_refs(db, [schedule])
    return schedule


async def update_status(
    db: AsyncSession, schedule_id: int, payload: ScheduleStatusIn, current: User
) -> Schedule:
    """标记日程完成/取消/恢复待办。"""
    schedule = await _get_schedule_or_404(db, schedule_id)
    await _assert_writable(db, schedule, current)
    schedule.status = payload.status
    await db.commit()
    await db.refresh(schedule)
    await _attach_refs(db, [schedule])
    return schedule


async def delete_schedule(
    db: AsyncSession, schedule_id: int, current: User
) -> None:
    """删除日程。"""
    schedule = await _get_schedule_or_404(db, schedule_id)
    await _assert_writable(db, schedule, current)
    await db.delete(schedule)
    await db.commit()
