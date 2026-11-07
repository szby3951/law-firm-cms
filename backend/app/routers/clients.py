"""客户关系管理路由：客户 CRUD、跟进记录、导出、AI 客户画像。"""

import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.core.utils import mask_id_no
from app.dependencies import CurrentUser, DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.ai import AiProfileIn, AiProfileOut
from app.schemas.client import (
    ClientCreate,
    ClientListOut,
    ClientOut,
    ClientUpdate,
    FollowCreate,
    FollowOut,
)
from app.services import ai_service, audit_service, client_service

router = APIRouter()

# 新增/修改客户：律师、管理员均可
LawyerOrAdmin = Annotated[User, Depends(require_role("lawyer", "admin"))]
# 删除客户：仅管理员
AdminOnly = Annotated[User, Depends(require_role("admin"))]

# 导出列：中文表头，与 _row_values 一一对应
_EXPORT_HEADERS = [
    "姓名",
    "类型",
    "联系电话",
    "证件号",
    "来源渠道",
    "分级",
    "漏斗状态",
    "备注",
    "创建时间",
]


def _row_values(client) -> list[str]:
    """把客户对象转成导出用的一行数据。"""
    client_type = "个人" if client.client_type == "personal" else "机构"
    level = "VIP" if client.level == "vip" else "普通"
    status_map = {"potential": "潜在", "deal": "成交", "lost": "流失"}
    status = status_map.get(client.status, client.status)
    created = client.created_at.strftime("%Y-%m-%d %H:%M") if client.created_at else ""
    return [
        client.name,
        client_type,
        client.phone or "",
        mask_id_no(client.id_no) or "",
        client.source_channel or "",
        level,
        status,
        client.remark or "",
        created,
    ]


@router.get("/export", summary="导出客户 Excel")
async def export_clients(request: Request, db: DbSession, user: CurrentUser):
    """导出当前用户可见的客户为 xlsx（律师导出本人客户，管理员导出全部）。

    注意：本路由必须声明在 ``/{client_id}`` 之前，否则 ``export`` 会被
    动态路径当作 client_id 解析而报 422。
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    clients = await client_service.iter_clients_for_export(db, user)

    wb = Workbook()
    ws = wb.active
    ws.title = "客户列表"

    header_fill = PatternFill(
        start_color="14213D", end_color="14213D", fill_type="solid"
    )
    header_font = Font(color="FFFFFF", bold=True)
    center = Alignment(horizontal="center", vertical="center")

    ws.append(_EXPORT_HEADERS)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center

    for client in clients:
        ws.append(_row_values(client))

    widths = [12, 8, 14, 22, 12, 8, 10, 30, 18]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_EXPORT,
        target="client",
        detail=f"导出客户 {len(clients)} 条",
        ip=client_ip(request),
    )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"clients_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=ClientListOut, summary="客户列表（分页）")
async def list_clients(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="姓名/电话/证件号模糊搜索"),
    status: str | None = Query(default=None, description="漏斗状态"),
    level: str | None = Query(default=None, description="客户分级"),
    source: str | None = Query(default=None, description="来源渠道"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> ClientListOut:
    """分页查询客户，律师仅见本人负责客户，管理员见全部。"""
    total, items = await client_service.list_clients(
        db,
        current=user,
        keyword=keyword,
        status=status,
        level=level,
        source=source,
        page=page,
        page_size=page_size,
    )
    return ClientListOut(
        total=total, items=[ClientOut.model_validate(x) for x in items]
    )


@router.post("", response_model=ClientOut, summary="新增客户")
async def create_client(
    payload: ClientCreate, request: Request, db: DbSession, user: LawyerOrAdmin
) -> ClientOut:
    """新增客户，律师归属本人，管理员可指定负责律师。"""
    client = await client_service.create_client(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"client:{client.id}",
        detail=f"新增客户 {client.name}",
        ip=client_ip(request),
    )
    return client


@router.get("/{client_id}", response_model=ClientOut, summary="客户详情")
async def get_client(client_id: int, db: DbSession, user: CurrentUser) -> ClientOut:
    """读取单个客户，律师仅见本人负责客户。"""
    return await client_service.get_client(db, client_id, user)


@router.put("/{client_id}", response_model=ClientOut, summary="修改客户")
async def update_client(
    client_id: int,
    payload: ClientUpdate,
    request: Request,
    db: DbSession,
    user: LawyerOrAdmin,
) -> ClientOut:
    """修改客户，仅更新传入字段。"""
    client = await client_service.update_client(db, client_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"client:{client.id}",
        detail=f"修改客户 {client.name}",
        ip=client_ip(request),
    )
    return client


@router.delete("/{client_id}", status_code=204, summary="删除客户")
async def delete_client(
    client_id: int, request: Request, db: DbSession, user: AdminOnly
) -> None:
    """删除客户，仅管理员可操作。"""
    await client_service.delete_client(db, client_id, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"client:{client_id}",
        detail=f"删除客户 #{client_id}",
        ip=client_ip(request),
    )


@router.post("/{client_id}/follows", response_model=FollowOut, summary="添加跟进记录")
async def add_follow(
    client_id: int,
    payload: FollowCreate,
    db: DbSession,
    user: LawyerOrAdmin,
) -> FollowOut:
    """给客户添加跟进记录。"""
    return await client_service.add_follow(db, client_id, payload, user)


@router.get(
    "/{client_id}/follows",
    response_model=list[FollowOut],
    summary="跟进记录列表",
)
async def list_follows(
    client_id: int, db: DbSession, user: CurrentUser
) -> list[FollowOut]:
    """查询客户的跟进记录，按时间倒序。"""
    return await client_service.list_follows(db, client_id, user)


@router.post(
    "/{client_id}/ai-profile",
    response_model=AiProfileOut,
    summary="生成 / 刷新 AI 客户画像",
)
async def generate_ai_profile(
    client_id: int,
    db: DbSession,
    user: LawyerOrAdmin,
    payload: AiProfileIn | None = None,
) -> AiProfileOut:
    """聚合客户档案、跟进、案件、合同、收费与沟通数据，生成结构化画像。

    仅负责律师与管理员可用；客户账号 403（画像含「价格敏感」「可能流失」这类
    内部判断）。生成的画像按客户存档，负责律师之间共享，写入
    ``client_profile.ai_profile`` 与 ``ai_profile_at``。
    """
    return await ai_service.generate_client_profile(
        db, user, client_id, payload or AiProfileIn()
    )


@router.get(
    "/{client_id}/ai-profile",
    response_model=AiProfileOut,
    summary="读取已存档的 AI 客户画像",
)
async def get_ai_profile(
    client_id: int, db: DbSession, user: LawyerOrAdmin
) -> AiProfileOut:
    """读取最近一次生成的画像；从未生成时 ``profile`` 为空。"""
    return await ai_service.get_client_profile(db, user, client_id)
