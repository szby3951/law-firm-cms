"""定时任务：扫描开庭/期限、缴费、跟进、合同到期，生成站内通知。

设计要点：

- 使用 APScheduler 的 ``AsyncIOScheduler``，在应用启动时注册、关闭时停止；
- 每 ``settings.scheduler_interval_minutes`` 分钟扫描一次（默认 5 分钟），
  首次启动 15 秒后先跑一轮，便于刚启动就能看到提醒；
- 每条提醒按「同用户 + 同类型 + 同对象」做 23 小时去重，一天最多推一条，
  避免每个扫描周期重复轰炸；
- 扫描异常只记日志，不抛出，保证调度器不中断。
"""

from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.database import SessionLocal
from app.models.billing import FeePeriod, FeePlan
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.follow import FollowRecord
from app.models.schedule import Schedule
from app.services import notification_service

logger = get_logger(__name__)

# 日程类型 → 通知类型（回访/会议不下发客户端）
SCHEDULE_NOTICE_TYPE = {
    "hearing": "hearing",
    "deadline": "deadline",
    "visit": "follow",
    "meeting": "meeting",
}

SCHEDULE_NOTICE_TITLE = {
    "hearing": "开庭提醒",
    "deadline": "期限提醒",
    "visit": "回访提醒",
    "meeting": "会议提醒",
}

# 客户端可见的日程提醒类型（与 schemas.notification 保持一致）
CLIENT_NOTICE_TYPES = {"hearing", "deadline"}

_scheduler: AsyncIOScheduler | None = None


def _fmt(value: datetime | None) -> str:
    """时间格式化：2026-11-10 09:00。"""
    return value.strftime("%Y-%m-%d %H:%M") if value else "—"


async def _client_user_map(
    db: AsyncSession, client_ids: set[int]
) -> dict[int, int]:
    """客户档案 id → 登录账号 id（没有账号的线索客户不推送）。"""
    if not client_ids:
        return {}
    rows = (
        await db.execute(
            select(ClientProfile.id, ClientProfile.user_id).where(
                ClientProfile.id.in_(client_ids),
                ClientProfile.user_id.is_not(None),
            )
        )
    ).all()
    return {cid: uid for cid, uid in rows if uid}


async def scan_schedule_reminders(db: AsyncSession) -> int:
    """扫描即将开始或已到提醒时间的待办日程，提醒承办律师与客户。"""
    now = datetime.now()
    ahead = now + timedelta(days=settings.remind_ahead_days)

    rows = (
        (
            await db.execute(
                select(Schedule)
                .where(
                    Schedule.status == "pending",
                    # 过期一天内的日程仍提醒一次，避免漏掉刚过期的待办
                    Schedule.event_date >= now - timedelta(days=1),
                    or_(
                        and_(
                            Schedule.remind_at.is_not(None),
                            Schedule.remind_at <= now,
                        ),
                        and_(
                            Schedule.remind_at.is_(None),
                            Schedule.event_date <= ahead,
                        ),
                    ),
                )
                .order_by(Schedule.event_date.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    # 批量取案件信息与客户账号
    case_ids = {s.case_id for s in rows if s.case_id}
    case_map: dict[int, tuple[str, str, int]] = {}
    if case_ids:
        case_rows = (
            await db.execute(
                select(Case.id, Case.case_no, Case.title, Case.client_id).where(
                    Case.id.in_(case_ids)
                )
            )
        ).all()
        case_map = {cid: (no, title, client_id) for cid, no, title, client_id in case_rows}

    user_map = await _client_user_map(db, {v[2] for v in case_map.values()})

    created = 0
    for item in rows:
        notice_type = SCHEDULE_NOTICE_TYPE.get(item.schedule_type, "system")
        label = SCHEDULE_NOTICE_TITLE.get(item.schedule_type, "日程提醒")
        lines = [f"时间：{_fmt(item.event_date)}"]
        client_id = None
        if item.case_id and item.case_id in case_map:
            case_no, case_title, client_id = case_map[item.case_id]
            lines.append(f"案件：{case_no} {case_title}")
        if item.remark:
            lines.append(f"备注：{item.remark}")
        lines.append("请提前安排时间并准备相关材料。")
        content = "\n".join(lines)

        notice = await notification_service.create_notification(
            db,
            user_id=item.user_id,
            title=f"【{label}】{item.title}",
            content=content,
            type=notice_type,
            related_type="schedule",
            related_id=item.id,
            dedupe_hours=23,
        )
        if notice is not None:
            created += 1

        # 开庭/期限属于对外信息，同步推送给委托客户
        if notice_type in CLIENT_NOTICE_TYPES and client_id:
            client_user_id = user_map.get(client_id)
            if client_user_id:
                client_notice = await notification_service.create_notification(
                    db,
                    user_id=client_user_id,
                    title=f"【{label}】{item.title}",
                    content=content,
                    type=notice_type,
                    related_type="schedule",
                    related_id=item.id,
                    dedupe_hours=23,
                )
                if client_notice is not None:
                    created += 1

    return created


async def scan_payment_reminders(db: AsyncSession) -> int:
    """扫描临近应收日期或已逾期的收费期次，提醒承办律师与客户。"""
    today = date.today()
    ahead_date = today + timedelta(days=settings.remind_ahead_days)

    rows = (
        await db.execute(
            select(
                FeePeriod,
                FeePlan.case_id,
                Case.case_no,
                Case.title,
                Case.client_id,
            )
            .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
            .join(Case, Case.id == FeePlan.case_id)
            .where(
                FeePeriod.status != "paid",
                FeePeriod.due_date.is_not(None),
                FeePeriod.due_date <= ahead_date,
            )
            .order_by(FeePeriod.due_date.asc())
        )
    ).all()
    if not rows:
        return 0

    case_ids = {case_id for _, case_id, _, _, _ in rows}
    lawyer_rows = (
        await db.execute(
            select(CaseLawyer.case_id, CaseLawyer.lawyer_id).where(
                CaseLawyer.case_id.in_(case_ids)
            )
        )
    ).all()
    lawyer_map: dict[int, list[int]] = {}
    for case_id, lawyer_id in lawyer_rows:
        lawyer_map.setdefault(case_id, []).append(lawyer_id)

    user_map = await _client_user_map(db, {client_id for *_, client_id in rows})

    created = 0
    for period, case_id, case_no, case_title, client_id in rows:
        due = period.due_amount or 0
        paid = period.paid_amount or 0
        unpaid = due - paid
        overdue_days = (today - period.due_date).days if period.due_date else 0
        if overdue_days > 0:
            due_desc = f"应收日期：{period.due_date}（已逾期 {overdue_days} 天）"
        else:
            due_desc = f"应收日期：{period.due_date}（即将到期）"
        content = (
            f"案件：{case_no} {case_title}\n"
            f"第 {period.period_no} 期应收 {due} 元，"
            f"已收 {paid} 元，未收 {unpaid} 元\n"
            f"{due_desc}\n请及时跟进收款。"
        )
        title = f"【缴费提醒】{case_no} 第 {period.period_no} 期待收 {unpaid} 元"

        for lawyer_id in lawyer_map.get(case_id, []):
            notice = await notification_service.create_notification(
                db,
                user_id=lawyer_id,
                title=title,
                content=content,
                type="payment",
                related_type="fee_period",
                related_id=period.id,
                dedupe_hours=23,
            )
            if notice is not None:
                created += 1

        client_user_id = user_map.get(client_id)
        if client_user_id:
            notice = await notification_service.create_notification(
                db,
                user_id=client_user_id,
                title=f"【缴费提醒】{case_no} 第 {period.period_no} 期待缴 {unpaid} 元",
                content=content,
                type="payment",
                related_type="fee_period",
                related_id=period.id,
                dedupe_hours=23,
            )
            if notice is not None:
                created += 1

    return created


async def scan_follow_reminders(db: AsyncSession) -> int:
    """扫描到期的客户跟进计划，提醒跟进人（仅律所内部）。"""
    today = date.today()

    # 每位客户只取最后一条带下次跟进日期的记录，避免历史记录反复提醒
    latest = (
        select(
            FollowRecord.client_id.label("client_id"),
            func.max(FollowRecord.id).label("last_id"),
        )
        .where(FollowRecord.next_follow_date.is_not(None))
        .group_by(FollowRecord.client_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(FollowRecord, ClientProfile.name)
            .join(latest, FollowRecord.id == latest.c.last_id)
            .join(ClientProfile, ClientProfile.id == FollowRecord.client_id)
            .where(FollowRecord.next_follow_date <= today)
        )
    ).all()
    if not rows:
        return 0

    created = 0
    for record, client_name in rows:
        notice = await notification_service.create_notification(
            db,
            user_id=record.user_id,
            title=f"【跟进提醒】{client_name} 待跟进",
            content=(
                f"客户：{client_name}\n"
                f"计划跟进日期：{record.next_follow_date}（已到期）\n"
                f"上次跟进：{_fmt(record.created_at)}\n"
                f"请及时联系客户并记录跟进结果。"
            ),
            type="follow",
            related_type="client",
            related_id=record.client_id,
            dedupe_hours=23,
        )
        if notice is not None:
            created += 1
    return created


async def scan_contract_expiry(db: AsyncSession) -> int:
    """扫描临近到期的生效合同，提醒登记人（无登记人时提醒客户负责律师）。"""
    today = date.today()
    limit = today + timedelta(days=settings.contract_expiry_days)

    rows = (
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.status == "active",
                    Contract.end_date.is_not(None),
                    Contract.end_date >= today,
                    Contract.end_date <= limit,
                )
                .order_by(Contract.end_date.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    client_rows = (
        await db.execute(
            select(
                ClientProfile.id,
                ClientProfile.name,
                ClientProfile.lawyer_id,
                ClientProfile.user_id,
            ).where(ClientProfile.id.in_({c.client_id for c in rows}))
        )
    ).all()
    client_map = {
        cid: (name, lawyer_id, user_id)
        for cid, name, lawyer_id, user_id in client_rows
    }

    created = 0
    for contract in rows:
        client_name, owner_lawyer, client_user_id = client_map.get(
            contract.client_id, (None, None, None)
        )
        days_left = (contract.end_date - today).days
        title = f"【合同预警】{contract.name} 将于 {days_left} 天后到期"
        content = (
            f"合同：{contract.name}\n"
            f"客户：{client_name or '—'}\n"
            f"到期日期：{contract.end_date}（剩余 {days_left} 天）\n"
            f"请及时评估续签或归档。"
        )

        receiver = contract.created_by or owner_lawyer
        if receiver:
            notice = await notification_service.create_notification(
                db,
                user_id=receiver,
                title=title,
                content=content,
                type="contract",
                related_type="contract",
                related_id=contract.id,
                dedupe_hours=23,
            )
            if notice is not None:
                created += 1

        # 合同到期属于对外信息，同步提醒委托客户（客户可见类型含 contract）
        if client_user_id:
            client_notice = await notification_service.create_notification(
                db,
                user_id=client_user_id,
                title=title,
                content=content,
                type="contract",
                related_type="contract",
                related_id=contract.id,
                dedupe_hours=23,
            )
            if client_notice is not None:
                created += 1
    return created


async def run_scan() -> dict[str, int]:
    """执行一轮全量提醒扫描，返回各类新增通知数量。

    独立开启数据库会话：定时任务不在请求生命周期内，不能复用 FastAPI 的
    ``get_db`` 依赖。
    """
    counts: dict[str, int] = {}
    async with SessionLocal() as db:
        counts["schedule"] = await scan_schedule_reminders(db)
        counts["payment"] = await scan_payment_reminders(db)
        counts["follow"] = await scan_follow_reminders(db)
        counts["contract"] = await scan_contract_expiry(db)
        await db.commit()
    counts["total"] = sum(counts.values())
    logger.info(
        "提醒扫描完成 | 日程 %s | 缴费 %s | 跟进 %s | 合同 %s | 合计 %s",
        counts["schedule"],
        counts["payment"],
        counts["follow"],
        counts["contract"],
        counts["total"],
    )
    return counts


async def _job_entry() -> None:
    """调度任务入口：吞掉异常，保证调度器持续运行。"""
    try:
        await run_scan()
    except Exception:  # 定时任务不允许因单次失败而中断
        logger.exception("提醒扫描任务执行失败")


def start_scheduler() -> None:
    """应用启动时注册定时任务（未开启则跳过）。"""
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("定时任务已关闭（scheduler_enabled=false）")
        return
    if _scheduler is not None:
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job_entry,
        trigger=IntervalTrigger(minutes=settings.scheduler_interval_minutes),
        id="reminder-scan",
        name="提醒扫描（开庭/缴费/跟进/合同）",
        max_instances=1,  # 上一轮没跑完不叠加
        coalesce=True,  # 错过多次只补一次
        misfire_grace_time=300,
        replace_existing=True,
        next_run_time=datetime.now() + timedelta(seconds=15),
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "定时任务已注册 | job=reminder-scan | 每 %s 分钟执行一次 | 首次约 15 秒后",
        settings.scheduler_interval_minutes,
    )


def shutdown_scheduler() -> None:
    """应用关闭时停止定时任务。"""
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")
    except Exception:  # 关闭阶段的异常不影响进程退出
        logger.warning("定时任务停止时出现异常", exc_info=True)
    finally:
        _scheduler = None
