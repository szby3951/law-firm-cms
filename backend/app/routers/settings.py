"""系统设置路由：数据字典、律所信息、AI 配置（仅管理员）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import DbSession, client_ip, require_role
from app.models.user import User
from app.schemas.setting import (
    AIConfigIn,
    AIConfigOut,
    DictItemIn,
    DictItemOut,
    DictListOut,
    FirmInfoIn,
    FirmInfoOut,
)
from app.services import audit_service, setting_service

router = APIRouter()

# 系统设置一律仅限管理员，避免律师改到全所共用的字典与模型配置
AdminOnly = Annotated[User, Depends(require_role("admin"))]


# ---------------------------------------------------------------- 数据字典


@router.get("/dicts", response_model=DictListOut, summary="字典列表（可按分类过滤）")
async def list_dicts(
    db: DbSession,
    admin: AdminOnly,
    dict_type: str | None = Query(default=None, description="分类，如 case_cause"),
) -> DictListOut:
    """返回字典项与全部分类汇总。"""
    items, types = await setting_service.list_dicts(db, dict_type)
    return DictListOut(items=items, types=types)


@router.post(
    "/dicts", response_model=DictItemOut, status_code=201, summary="新增字典项"
)
async def create_dict(
    payload: DictItemIn, request: Request, db: DbSession, admin: AdminOnly
) -> DictItemOut:
    """新增一个下拉选项。"""
    item = await setting_service.create_dict(db, payload)
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_CREATE,
        target=f"dict:{item.id}",
        detail=f"新增字典 {item.dict_type}/{item.label}({item.value})",
        ip=client_ip(request),
    )
    return DictItemOut.model_validate(item)


@router.put("/dicts/{item_id}", response_model=DictItemOut, summary="修改字典项")
async def update_dict(
    item_id: int, payload: DictItemIn, request: Request, db: DbSession, admin: AdminOnly
) -> DictItemOut:
    """修改字典项的分类、显示名、取值或排序。"""
    item = await setting_service.update_dict(db, item_id, payload)
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_UPDATE,
        target=f"dict:{item.id}",
        detail=f"修改字典 {item.dict_type}/{item.label}({item.value})",
        ip=client_ip(request),
    )
    return DictItemOut.model_validate(item)


@router.delete("/dicts/{item_id}", status_code=204, summary="删除字典项")
async def delete_dict(
    item_id: int, request: Request, db: DbSession, admin: AdminOnly
) -> None:
    """删除字典项，历史数据不受影响。"""
    await setting_service.delete_dict(db, item_id)
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_DELETE,
        target=f"dict:{item_id}",
        detail="删除字典项",
        ip=client_ip(request),
    )


# ---------------------------------------------------------------- 律所信息


@router.get("/firm", response_model=FirmInfoOut, summary="律所信息")
async def get_firm(db: DbSession, admin: AdminOnly) -> FirmInfoOut:
    """读取律所信息（单行）。"""
    firm = await setting_service.get_firm(db)
    return FirmInfoOut.model_validate(firm)


@router.put("/firm", response_model=FirmInfoOut, summary="修改律所信息")
async def update_firm(
    payload: FirmInfoIn, request: Request, db: DbSession, admin: AdminOnly
) -> FirmInfoOut:
    """保存律所信息，律所名称同步到 AI 提示词。"""
    firm = await setting_service.update_firm(db, payload)
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_UPDATE,
        target="firm:1",
        detail=f"修改律所信息：{firm.name}",
        ip=client_ip(request),
    )
    return FirmInfoOut.model_validate(firm)


# ---------------------------------------------------------------- AI 配置


@router.get("/ai-config", response_model=AIConfigOut, summary="AI 配置")
async def get_ai_config(db: DbSession, admin: AdminOnly) -> AIConfigOut:
    """读取 AI 配置，API Key 只返回脱敏串。"""
    return await setting_service.get_ai_config(db)


@router.put("/ai-config", response_model=AIConfigOut, summary="修改 AI 配置")
async def update_ai_config(
    payload: AIConfigIn, request: Request, db: DbSession, admin: AdminOnly
) -> AIConfigOut:
    """保存 AI 配置，启用后立即覆盖 .env 中的对话模型参数。"""
    config = await setting_service.update_ai_config(db, payload)
    await audit_service.write_log_safe(
        db,
        user_id=admin.id,
        action=audit_service.ACTION_UPDATE,
        target="ai_config:1",
        detail=(
            f"AI 配置 {'启用' if config.status == 1 else '停用'}："
            f"{config.provider}/{config.model}"
        ),
        ip=client_ip(request),
    )
    return config
