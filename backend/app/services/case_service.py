"""案件管理业务逻辑：立案、分案、状态流转、事件登记、列表与详情。"""

from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.attachment import Attachment
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.user import User
from app.schemas.case import (
    CaseAssignIn,
    CaseCreate,
    CaseEventIn,
    CaseStatusIn,
)

# ---------------------------------------------------------------------------
# 状态机：案件全生命周期合法流转关系
# 咨询中 → 已立案 → 办理中 → 待结案 → 已结案 / 已退案
# ---------------------------------------------------------------------------
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "consulting": {"filed", "withdrawn"},
    "filed": {"handling", "withdrawn"},
    "handling": {"pending_close", "withdrawn"},
    "pending_close": {"closed", "handling", "withdrawn"},
    "closed": set(),  # 终态
    "withdrawn": set(),  # 终态
}

# 案件状态 → 中文名（供展示/审计）
STATUS_LABELS = {
    "consulting": "咨询中",
    "filed": "已立案",
    "handling": "办理中",
    "pending_close": "待结案",
    "closed": "已结案",
    "withdrawn": "已退案",
}

# 事件类型 → 中文名
EVENT_LABELS = {
    "filing": "立案",
    "accept": "受理",
    "hearing": "开庭",
    "evidence": "举证",
    "judgment": "判决",
    "other": "其他",
}


def _validate_transition(current: str, target: str) -> None:
    """校验状态流转合法性，非法则抛 BadRequest。"""
    allowed = STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise BadRequest(
            f"状态不能从「{STATUS_LABELS.get(current, current)}」流转到"
            f"「{STATUS_LABELS.get(target, target)}」"
        )


async def _gen_case_no(db: AsyncSession) -> str:
    """生成唯一案号：LF + 年月 + 4 位序号。

    格式示例 ``LF2026110001``。取当月已存在的最大序号 +1，而不是按记录条数 +1，
    避免删除中间案件后案号序号出现空洞、导致与现存案号撞车（唯一键冲突）。
    并发下依赖 case_no 唯一索引兜底，冲突由调用方重试。
    """
    now = datetime.now()
    prefix = f"LF{now.strftime('%Y%m')}"
    # 取当月以该前缀开头的案号中的最大序号
    max_no = await db.scalar(
        select(func.max(Case.case_no)).where(Case.case_no.like(f"{prefix}%"))
    )
    if max_no:
        # 解析出末尾 4 位序号，+1 递增
        try:
            seq = int(max_no[len(prefix) :]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


async def _ensure_client(db: AsyncSession, client_id: int) -> ClientProfile:
    """校验客户存在。"""
    client = await db.get(ClientProfile, client_id)
    if client is None:
        raise NotFound("委托客户不存在")
    return client


async def _get_case_or_404(db: AsyncSession, case_id: int) -> Case:
    """读取案件，不存在抛 404。"""
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("案件不存在")
    return case


async def _case_lawyer_ids(db: AsyncSession, case_id: int) -> set[int]:
    """返回案件全部承办律师 id（主办+协办）。"""
    rows = (
        (
            await db.execute(
                select(CaseLawyer.lawyer_id).where(CaseLawyer.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def _lead_lawyer_map(
    db: AsyncSession, case_ids: list[int]
) -> dict[int, str | None]:
    """批量取各案件的主办律师姓名，避免列表页 N+1 查询。

    无分案记录的案件不会出现在返回的映射里，调用方按 None 处理。
    """
    if not case_ids:
        return {}
    rows = (
        await db.execute(
            select(CaseLawyer.case_id, User.real_name, User.username)
            .join(User, User.id == CaseLawyer.lawyer_id)
            .where(CaseLawyer.case_id.in_(case_ids), CaseLawyer.duty == "lead")
        )
    ).all()
    return {case_id: (real_name or username) for case_id, real_name, username in rows}


async def _assert_lawyer_access(db: AsyncSession, case: Case, current: User) -> None:
    """律师对案件的访问权限：仅本人主办或协办。"""
    if current.role == "admin":
        return
    if current.role != "lawyer":
        raise Forbidden("无权操作案件")
    lawyer_ids = await _case_lawyer_ids(db, case.id)
    if current.id not in lawyer_ids:
        raise Forbidden("无权操作该案件")


async def create_case(db: AsyncSession, payload: CaseCreate, current: User) -> Case:
    """立案：生成案号、创建案件，并自动写入一条「立案」事件。

    律师立案时默认自己为主办律师；管理员立案可指定客户但不自动分案。
    """
    await _ensure_client(db, payload.client_id)

    # 生成唯一案号（冲突重试，靠唯一索引兜底）
    case_no = await _gen_case_no(db)
    while await db.scalar(select(Case).where(Case.case_no == case_no)) is not None:
        case_no = await _gen_case_no(db)

    case = Case(
        case_no=case_no,
        client_id=payload.client_id,
        title=payload.title,
        case_cause=payload.case_cause,
        case_type=payload.case_type,
        court=payload.court,
        opposing_party=payload.opposing_party,
        amount=payload.amount,
        status="consulting",
        description=payload.description,
        created_by=current.id,
    )
    db.add(case)
    await db.flush()  # 拿到 case.id

    # 立案人若是律师，默认登记为主办律师
    if current.role == "lawyer":
        db.add(CaseLawyer(case_id=case.id, lawyer_id=current.id, duty="lead"))

    # 自动写入立案事件
    db.add(
        CaseEvent(
            case_id=case.id,
            event_type="filing",
            event_date=datetime.now(),
            description=f"案件立案，案号 {case_no}",
            created_by=current.id,
        )
    )

    await db.commit()
    await db.refresh(case)
    return case


async def list_cases(
    db: AsyncSession,
    *,
    current: User,
    status: str | None = None,
    cause: str | None = None,
    case_type: str | None = None,
    lawyer_id: int | None = None,
    client_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Case]]:
    """分页查询案件，按角色做行级隔离。

    - 律师：只看自己主办或协办的案件（case_lawyer 表关联）。
    - 管理员：全量，可按律师过滤。
    """
    if page < 1:
        raise BadRequest("页码必须大于等于 1")
    if not 1 <= page_size <= 100:
        raise BadRequest("每页数量需在 1~100 之间")

    stmt = select(Case)

    if current.role == "lawyer":
        # 本人主办或协办的案件
        stmt = stmt.where(
            Case.id.in_(
                select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
            )
        )
    elif current.role == "client":
        # 客户端走 /api/my/cases，此处不支持
        raise Forbidden("无权查看案件列表")

    if status:
        stmt = stmt.where(Case.status == status)
    if cause:
        stmt = stmt.where(Case.case_cause.like(f"%{cause}%"))
    if case_type:
        stmt = stmt.where(Case.case_type == case_type)
    if client_id:
        stmt = stmt.where(Case.client_id == client_id)
    if lawyer_id and current.role == "admin":
        stmt = stmt.where(
            Case.id.in_(
                select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == lawyer_id)
            )
        )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (
            await db.execute(
                stmt.order_by(Case.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    # 注入主办律师姓名（客户详情页/案件台账展示「谁在办」）
    lead_map = await _lead_lawyer_map(db, [c.id for c in rows])
    for case in rows:
        case.lead_lawyer_name = lead_map.get(case.id)

    return total or 0, list(rows)


async def get_case_detail(db: AsyncSession, case_id: int, current: User) -> Case:
    """案件详情：校验权限后返回案件对象（时间线/律师/附件由路由层聚合）。"""
    case = await _get_case_or_404(db, case_id)
    await _assert_lawyer_access(db, case, current)
    return case


async def assign_case(
    db: AsyncSession, case_id: int, payload: CaseAssignIn, current: User
) -> list[CaseLawyer]:
    """分案：管理员指定主办律师与协办律师。

    覆盖式分案：先清空原有承办关系，再按入参重建。
    校验主办/协办律师均为 lawyer 角色。
    """
    await _get_case_or_404(db, case_id)
    if current.role != "admin":
        raise Forbidden("只有管理员可以分案")

    # 校验律师角色与存在性
    lead = await db.get(User, payload.lead_lawyer_id)
    if lead is None or lead.role != "lawyer":
        raise BadRequest("主办律师不存在或角色不正确")

    assist_ids = []
    for aid in payload.assist_lawyer_ids:
        if aid == payload.lead_lawyer_id:
            continue
        lawyer = await db.get(User, aid)
        if lawyer is None or lawyer.role != "lawyer":
            raise BadRequest(f"协办律师 #{aid} 不存在或角色不正确")
        assist_ids.append(aid)

    # 覆盖式重建承办关系
    existing = (
        (await db.execute(select(CaseLawyer).where(CaseLawyer.case_id == case_id)))
        .scalars()
        .all()
    )
    for rel in existing:
        await db.delete(rel)

    db.add(CaseLawyer(case_id=case_id, lawyer_id=payload.lead_lawyer_id, duty="lead"))
    for aid in assist_ids:
        db.add(CaseLawyer(case_id=case_id, lawyer_id=aid, duty="assist"))

    await db.commit()

    rows = (
        (await db.execute(select(CaseLawyer).where(CaseLawyer.case_id == case_id)))
        .scalars()
        .all()
    )
    return list(rows)


async def update_case_status(
    db: AsyncSession, case_id: int, payload: CaseStatusIn, current: User
) -> Case:
    """状态流转：校验状态机合法性后更新，结案时写 closed_at。"""
    case = await _get_case_or_404(db, case_id)
    await _assert_lawyer_access(db, case, current)

    _validate_transition(case.status, payload.status)

    case.status = payload.status
    if payload.status in ("closed", "withdrawn"):
        case.closed_at = datetime.now()
    else:
        case.closed_at = None

    await db.commit()
    await db.refresh(case)
    return case


async def add_case_event(
    db: AsyncSession, case_id: int, payload: CaseEventIn, current: User
) -> CaseEvent:
    """登记案件事件，写入时间线。"""
    case = await _get_case_or_404(db, case_id)
    await _assert_lawyer_access(db, case, current)

    event = CaseEvent(
        case_id=case_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        description=payload.description,
        created_by=current.id,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def delete_case(db: AsyncSession, case_id: int, current: User) -> None:
    """删除案件（仅管理员），级联清理承办关系、事件与附件元信息。

    物理文件（uploads/case/{case_id}/）由调用方或运维另行清理，
    此处只删除数据库记录，避免误删磁盘文件。
    """
    if current.role != "admin":
        raise Forbidden("只有管理员可以删除案件")

    case = await _get_case_or_404(db, case_id)

    # 级联清理关联数据（case_lawyer / case_event / attachment）
    await db.execute(delete(CaseLawyer).where(CaseLawyer.case_id == case_id))
    await db.execute(delete(CaseEvent).where(CaseEvent.case_id == case_id))
    await db.execute(
        delete(Attachment).where(
            Attachment.biz_type == "case", Attachment.biz_id == case_id
        )
    )
    await db.delete(case)
    await db.commit()


async def list_case_lawyers(db: AsyncSession, case_id: int) -> list[CaseLawyer]:
    """查询案件承办律师（含姓名）。"""
    rows = (
        await db.execute(
            select(CaseLawyer, User.real_name)
            .join(User, User.id == CaseLawyer.lawyer_id)
            .where(CaseLawyer.case_id == case_id)
            .order_by(CaseLawyer.duty.desc())
        )
    ).all()
    return [(rel, name) for rel, name in rows]


async def list_case_events(db: AsyncSession, case_id: int) -> list[CaseEvent]:
    """查询案件时间线（按节点时间倒序）。"""
    return list(
        (
            await db.execute(
                select(CaseEvent)
                .where(CaseEvent.case_id == case_id)
                .order_by(CaseEvent.event_date.desc(), CaseEvent.id.desc())
            )
        )
        .scalars()
        .all()
    )


async def list_case_attachments(db: AsyncSession, case_id: int) -> list[Attachment]:
    """查询案件附件（证据/材料）。"""
    return list(
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.biz_type == "case", Attachment.biz_id == case_id)
                .order_by(Attachment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def list_my_cases(db: AsyncSession, current: User) -> list[Case]:
    """客户端：当前客户本人委托的案件列表。

    关联规则：client_profile.user_id == 本人，或 client_profile.phone == 本人手机号
    （双保险，兼容律师代录后尚未回填 user_id 的档案）。
    """
    if current.role != "client":
        raise Forbidden("仅客户可查看")

    # 归属本人的客户档案：优先 user_id 关联，手机号兜底
    cond = or_(
        ClientProfile.user_id == current.id,
        ClientProfile.phone == current.phone,
    )
    rows = (
        (
            await db.execute(
                select(Case)
                .join(ClientProfile, ClientProfile.id == Case.client_id)
                .where(cond)
                .order_by(Case.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_my_case(db: AsyncSession, case_id: int, current: User) -> Case:
    """客户端：读取本人委托的单个案件（按 user_id 或手机号隔离）。"""
    if current.role != "client":
        raise Forbidden("仅客户可查看")
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("案件不存在")
    # 校验案件委托客户确实关联到当前登录账号
    client = await db.get(ClientProfile, case.client_id)
    if client is None:
        raise Forbidden("无权查看该案件")
    is_owner = client.user_id == current.id or (
        current.phone and client.phone == current.phone
    )
    if not is_owner:
        raise Forbidden("无权查看该案件")
    return case


async def get_attachment(db: AsyncSession, attachment_id: int, current: User) -> Attachment:
    """读取案件附件并做行级权限校验（律师/管理员/客户三端共用）。

    返回附件对象供下载/预览；无权限或不存在抛 403/404。
    """
    attachment = await db.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFound("附件不存在")
    if attachment.biz_type != "case":
        raise NotFound("附件不存在")

    case_id = attachment.biz_id
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("案件不存在")

    # 按角色做行级隔离，与详情接口保持一致
    if current.role == "admin":
        pass
    elif current.role == "lawyer":
        lawyer_ids = await _case_lawyer_ids(db, case_id)
        if current.id not in lawyer_ids:
            raise Forbidden("无权查看该附件")
    elif current.role == "client":
        client = await db.get(ClientProfile, case.client_id)
        is_owner = client is not None and (
            client.user_id == current.id
            or (current.phone and client.phone == current.phone)
        )
        if not is_owner:
            raise Forbidden("无权查看该附件")
    else:
        raise Forbidden("无权查看该附件")

    return attachment


async def save_case_file(
    db: AsyncSession,
    *,
    case_id: int,
    original_name: str,
    stored_path: str,
    file_size: int,
    mime_type: str | None,
    current: User,
) -> Attachment:
    """登记案件附件元信息（文件已由路由层落盘）。"""
    case = await _get_case_or_404(db, case_id)
    await _assert_lawyer_access(db, case, current)

    attachment = Attachment(
        biz_type="case",
        biz_id=case_id,
        file_name=original_name,
        file_path=stored_path,
        file_size=file_size,
        mime_type=mime_type,
        uploader_id=current.id,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment
