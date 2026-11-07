"""合同管理业务逻辑：台账 CRUD、文件上传、到期扫描、AI 审查报告存储。"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.user import User
from app.schemas.contract import ContractCreate, ContractReviewIn, ContractUpdate


async def _get_contract_or_404(db: AsyncSession, contract_id: int) -> Contract:
    """读取合同，不存在抛 404。"""
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise NotFound("合同不存在")
    return contract


async def _attach_client_names(
    db: AsyncSession, contracts: list[Contract]
) -> list[Contract]:
    """批量注入 client_name（关联客户姓名），返回原列表。

    通过一次查询把 client_id → name 映射取回，逐个设置到 Contract 的
    非数据库字段 ``client_name`` 上，供 ``ContractOut`` 序列化输出。
    """
    if not contracts:
        return contracts
    client_ids = {c.client_id for c in contracts}
    rows = (
        await db.execute(
            select(ClientProfile.id, ClientProfile.name).where(
                ClientProfile.id.in_(client_ids)
            )
        )
    ).all()
    name_map = {cid: name for cid, name in rows}
    for c in contracts:
        c.client_name = name_map.get(c.client_id)
    return contracts


async def _attach_case_titles(
    db: AsyncSession, contracts: list[Contract]
) -> list[Contract]:
    """批量注入 case_title（关联案件标题），返回原列表。

    对 ``case_id`` 非空的合同，一次查询案件标题映射并注入到非数据库
    字段 ``case_title`` 上。
    """
    if not contracts:
        return contracts
    case_ids = {c.case_id for c in contracts if c.case_id}
    if not case_ids:
        return contracts
    rows = (
        await db.execute(
            select(Case.id, Case.title).where(Case.id.in_(case_ids))
        )
    ).all()
    title_map = {cid: title for cid, title in rows}
    for c in contracts:
        if c.case_id:
            c.case_title = title_map.get(c.case_id)
    return contracts


async def _attach_contract_names(
    db: AsyncSession, contracts: list[Contract]
) -> list[Contract]:
    """一次注入 client_name 与 case_title，返回原列表。"""
    await _attach_client_names(db, contracts)
    await _attach_case_titles(db, contracts)
    return contracts
async def _ensure_client(db: AsyncSession, client_id: int) -> ClientProfile:
    """校验客户存在。"""
    client = await db.get(ClientProfile, client_id)
    if client is None:
        raise NotFound("委托客户不存在")
    return client


async def _ensure_case(db: AsyncSession, case_id: int | None) -> None:
    """校验关联案件存在（可空）。"""
    if case_id is None:
        return
    case = await db.get(Case, case_id)
    if case is None:
        raise NotFound("关联案件不存在")


async def _contract_case_lawyer_ids(db: AsyncSession, case_id: int) -> set[int]:
    """返回合同关联案件的承办律师 id 集合。"""
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


async def _assert_contract_access(db: AsyncSession, contract: Contract, current: User) -> None:
    """合同访问权限校验。

    - 管理员：全量。
    - 律师：仅可操作本人主办/协办案件下的合同；无关联案件的合同仅创建人可操作。
    - 客户：只读，仅能访问本人委托客户的合同（在查询层过滤，此处兜底拒绝写操作）。
    """
    if current.role == "admin":
        return
    if current.role == "client":
        raise Forbidden("客户无权操作合同")

    # 律师：合同关联案件时，须为承办律师；否则须为创建人
    if contract.case_id:
        lawyer_ids = await _contract_case_lawyer_ids(db, contract.case_id)
        if current.id not in lawyer_ids:
            raise Forbidden("无权操作该合同")
    elif contract.created_by != current.id:
        raise Forbidden("无权操作该合同")


async def create_contract(
    db: AsyncSession, payload: ContractCreate, current: User
) -> Contract:
    """新增合同台账。

    律师新增的合同默认归属其可访问的客户/案件；管理员可跨全部。
    """
    await _ensure_client(db, payload.client_id)
    await _ensure_case(db, payload.case_id)

    # 律师只能为本人负责客户/案件建档（客户归属校验）
    if current.role == "lawyer":
        client = await db.get(ClientProfile, payload.client_id)
        if client.lawyer_id != current.id:
            raise Forbidden("只能为本人负责的客户创建合同")
        if payload.case_id:
            lawyer_ids = await _contract_case_lawyer_ids(db, payload.case_id)
            if current.id not in lawyer_ids:
                raise Forbidden("只能为本人承办的案件创建合同")

    contract = Contract(
        client_id=payload.client_id,
        case_id=payload.case_id,
        name=payload.name,
        contract_type=payload.contract_type,
        amount=payload.amount,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=payload.status,
        created_by=current.id,
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    await _attach_contract_names(db, [contract])
    return contract


async def list_contracts(
    db: AsyncSession,
    *,
    current: User,
    status: str | None = None,
    client_id: int | None = None,
    case_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Contract]]:
    """分页查询合同，按角色行级隔离。

    - 律师：仅本人承办案件的合同 + 本人创建的无案件合同。
    - 管理员：全量。
    - 客户：此处不支持（走 /api/my/contracts）。
    """
    if page < 1:
        raise BadRequest("页码必须大于等于 1")
    if not 1 <= page_size <= 100:
        raise BadRequest("每页数量需在 1~100 之间")

    stmt = select(Contract)

    if current.role == "lawyer":
        # 本人承办案件下的合同，或本人创建且未关联案件的合同
        stmt = stmt.where(
            or_(
                Contract.case_id.in_(
                    select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
                ),
                Contract.created_by == current.id,
            )
        )
    elif current.role == "client":
        raise Forbidden("无权查看合同列表")

    if status:
        stmt = stmt.where(Contract.status == status)
    if client_id:
        stmt = stmt.where(Contract.client_id == client_id)
    if case_id:
        stmt = stmt.where(Contract.case_id == case_id)
    if keyword:
        stmt = stmt.where(Contract.name.like(f"%{keyword}%"))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (
            await db.execute(
                stmt.order_by(Contract.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    await _attach_contract_names(db, list(rows))
    return total or 0, list(rows)


async def get_contract(db: AsyncSession, contract_id: int, current: User) -> Contract:
    """合同详情：校验权限后返回合同对象。"""
    contract = await _get_contract_or_404(db, contract_id)
    await _assert_contract_access(db, contract, current)
    await _attach_contract_names(db, [contract])
    return contract


async def update_contract(
    db: AsyncSession, contract_id: int, payload: ContractUpdate, current: User
) -> Contract:
    """修改合同台账（律师仅本人合同，管理员全量）。"""
    contract = await _get_contract_or_404(db, contract_id)
    await _assert_contract_access(db, contract, current)

    data = payload.model_dump(exclude_unset=True)

    # 客户/案件变更需校验存在性与归属
    if "client_id" in data and data["client_id"] is not None:
        await _ensure_client(db, data["client_id"])
        if current.role == "lawyer":
            client = await db.get(ClientProfile, data["client_id"])
            if client.lawyer_id != current.id:
                raise Forbidden("只能为本人负责的客户创建合同")
    if "case_id" in data:
        await _ensure_case(db, data["case_id"])
        if data["case_id"] and current.role == "lawyer":
            lawyer_ids = await _contract_case_lawyer_ids(db, data["case_id"])
            if current.id not in lawyer_ids:
                raise Forbidden("只能为本人承办的案件创建合同")

    # 日期区间校验（在服务层兜底，schema 层已校验新建时）
    start = data.get("start_date", contract.start_date)
    end = data.get("end_date", contract.end_date)
    if start and end and end < start:
        raise BadRequest("到期日期不能早于生效日期")

    for field, value in data.items():
        setattr(contract, field, value)

    await db.commit()
    await db.refresh(contract)
    await _attach_contract_names(db, [contract])
    return contract


async def save_contract_file(
    db: AsyncSession,
    *,
    contract_id: int,
    stored_path: str,
    current: User,
) -> Contract:
    """登记合同文件路径（文件已由路由层落盘）。"""
    contract = await _get_contract_or_404(db, contract_id)
    await _assert_contract_access(db, contract, current)

    contract.file_url = stored_path
    await db.commit()
    await db.refresh(contract)
    await _attach_contract_names(db, [contract])
    return contract


async def save_contract_review(
    db: AsyncSession,
    contract_id: int,
    payload: ContractReviewIn,
    current: User,
) -> Contract:
    """存储 AI 审查报告。"""
    contract = await _get_contract_or_404(db, contract_id)
    await _assert_contract_access(db, contract, current)

    contract.ai_review_report = payload.report
    contract.ai_review_at = datetime.now()
    await db.commit()
    await db.refresh(contract)
    await _attach_contract_names(db, [contract])
    return contract


async def list_expiring_contracts(
    db: AsyncSession,
    current: User,
    days: int = 30,
) -> list[Contract]:
    """到期扫描：返回 end_date 在 N 天内到期的合同。

    - 律师：本人承办/创建的合同。
    - 管理员：全量。
    """
    if not 1 <= days <= 365:
        raise BadRequest("预警天数需在 1~365 之间")

    today = date.today()
    deadline = today + timedelta(days=days)

    stmt = select(Contract).where(
        Contract.end_date.is_not(None),
        Contract.end_date >= today,
        Contract.end_date <= deadline,
        Contract.status == "active",
    )

    if current.role == "lawyer":
        stmt = stmt.where(
            or_(
                Contract.case_id.in_(
                    select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
                ),
                Contract.created_by == current.id,
            )
        )
    elif current.role == "client":
        raise Forbidden("无权查看到期合同")

    rows = (
        (await db.execute(stmt.order_by(Contract.end_date.asc()))).scalars().all()
    )
    await _attach_contract_names(db, list(rows))
    return list(rows)


async def list_my_contracts(db: AsyncSession, current: User) -> list[Contract]:
    """客户端：当前客户本人关联的合同列表（只读）。"""
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
                select(Contract)
                .join(ClientProfile, ClientProfile.id == Contract.client_id)
                .where(cond)
                .order_by(Contract.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    await _attach_contract_names(db, list(rows))
    return list(rows)


async def get_my_contract(
    db: AsyncSession, contract_id: int, current: User
) -> Contract:
    """客户端：当前客户本人关联的合同详情（只读，行级隔离）。"""
    if current.role != "client":
        raise Forbidden("仅客户可查看")

    contract = await _get_contract_or_404(db, contract_id)

    # 校验合同归属本人（通过 client_profile 的 user_id 或 phone 关联）
    cond = or_(
        ClientProfile.user_id == current.id,
        ClientProfile.phone == current.phone,
    )
    owned = await db.scalar(
        select(Contract.id)
        .join(ClientProfile, ClientProfile.id == Contract.client_id)
        .where(Contract.id == contract_id, cond)
    )
    if owned is None:
        raise Forbidden("无权查看该合同")

    await _attach_contract_names(db, [contract])
    return contract
