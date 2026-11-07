"""合同管理路由：台账 CRUD、文件上传、到期预警、AI 审查报告存储。"""

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.config import settings
from app.core.exceptions import BadRequest
from app.dependencies import CurrentUser, DbSession, client_ip
from app.models.attachment import Attachment
from app.schemas.case import AttachmentOut
from app.schemas.contract import (
    ContractCreate,
    ContractListOut,
    ContractOut,
    ContractReviewIn,
    ContractUpdate,
)
from app.services import audit_service, contract_service

router = APIRouter()


@router.get("", response_model=ContractListOut, summary="合同台账列表（分页）")
async def list_contracts(
    db: DbSession,
    user: CurrentUser,
    status: str | None = Query(default=None, description="合同状态"),
    client_id: int | None = Query(default=None, description="客户ID"),
    case_id: int | None = Query(default=None, description="案件ID"),
    keyword: str | None = Query(default=None, description="名称模糊搜索"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> ContractListOut:
    """分页查询合同，律师仅见本人承办/创建合同，管理员见全部。"""
    total, items = await contract_service.list_contracts(
        db,
        current=user,
        status=status,
        client_id=client_id,
        case_id=case_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ContractListOut(
        total=total, items=[ContractOut.model_validate(x) for x in items]
    )


@router.get("/expiring", response_model=list[ContractOut], summary="到期合同预警")
async def list_expiring(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365, description="预警天数"),
) -> list[ContractOut]:
    """返回 N 天内到期的生效合同（按到期日升序）。"""
    items = await contract_service.list_expiring_contracts(db, user, days=days)
    return [ContractOut.model_validate(x) for x in items]


@router.post("", response_model=ContractOut, summary="新增合同")
async def create_contract(
    payload: ContractCreate, request: Request, db: DbSession, user: CurrentUser
) -> ContractOut:
    """新增合同台账（律师/管理员）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")
    contract = await contract_service.create_contract(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"contract:{contract.id}",
        detail=f"新增合同 {contract.name}",
        ip=client_ip(request),
    )
    return contract


@router.get("/{contract_id}", response_model=ContractOut, summary="合同详情")
async def get_contract(
    contract_id: int, db: DbSession, user: CurrentUser
) -> ContractOut:
    """合同详情（含 AI 审查报告、文件路径）。"""
    contract = await contract_service.get_contract(db, contract_id, user)
    return contract


@router.put("/{contract_id}", response_model=ContractOut, summary="修改合同")
async def update_contract(
    contract_id: int,
    payload: ContractUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ContractOut:
    """修改合同台账（律师仅本人合同，管理员全量）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")
    contract = await contract_service.update_contract(db, contract_id, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"contract:{contract.id}",
        detail=f"修改合同 {contract.name}",
        ip=client_ip(request),
    )
    return contract


@router.post(
    "/{contract_id}/upload", response_model=AttachmentOut, summary="上传合同文件"
)
async def upload_contract_file(
    contract_id: int,
    file: UploadFile,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> AttachmentOut:
    """上传合同 PDF/Word 文件，落盘 + 登记 attachment（biz_type=contract）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")

    # 先校验合同存在与权限
    await contract_service.get_contract(db, contract_id, user)

    content = await file.read()
    if len(content) > settings.max_upload_size:
        raise BadRequest(
            f"文件大小超过 {settings.max_upload_size // (1024 * 1024)}MB 上限"
        )

    original_name = file.filename or "未命名文件"
    ext = Path(original_name).suffix.lower()
    if not ext:
        ext = _guess_ext(file.content_type)
    safe_ext = ext if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", ext) else ""
    stored_name = f"{uuid4().hex}{safe_ext}"
    rel_dir = Path("contract") / str(contract_id)
    abs_dir = settings.upload_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / stored_name
    abs_path.write_bytes(content)

    rel_path = (rel_dir / stored_name).as_posix()

    # 登记 attachment 元信息 + 回写合同 file_url
    attachment = Attachment(
        biz_type="contract",
        biz_id=contract_id,
        file_name=original_name,
        file_path=rel_path,
        file_size=len(content),
        mime_type=file.content_type,
        uploader_id=user.id,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)  # 拿到 server_default 填充的 created_at

    await contract_service.save_contract_file(
        db, contract_id=contract_id, stored_path=rel_path, current=user
    )

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"contract:{contract_id}",
        detail=f"上传合同文件 {original_name}",
        ip=client_ip(request),
    )
    return AttachmentOut.model_validate(attachment)


@router.get("/{contract_id}/download", summary="下载合同文件")
async def download_contract_file(
    contract_id: int, db: DbSession, user: CurrentUser
) -> FileResponse:
    """下载合同文件（律师/管理员/客户按权限）。"""
    contract = await contract_service.get_contract(db, contract_id, user)
    if not contract.file_url:
        raise BadRequest("该合同尚未上传文件")

    abs_path = (settings.upload_dir / contract.file_url).resolve()
    upload_root = settings.upload_dir.resolve()
    if not str(abs_path).startswith(str(upload_root)):
        raise BadRequest("非法文件路径")
    if not abs_path.is_file():
        raise BadRequest("文件不存在或已被移除")

    # 取原始文件名（从 attachment 表反查）
    original_name = await db.scalar(
        select(Attachment.file_name)
        .where(Attachment.biz_type == "contract", Attachment.biz_id == contract_id)
        .order_by(Attachment.id.desc())
        .limit(1)
    )
    return FileResponse(
        path=abs_path,
        media_type="application/octet-stream",
        filename=original_name or "合同文件",
    )


@router.post(
    "/{contract_id}/review", response_model=ContractOut, summary="保存 AI 审查报告"
)
async def save_contract_review(
    contract_id: int,
    payload: ContractReviewIn,
    db: DbSession,
    user: CurrentUser,
) -> ContractOut:
    """存储 AI 风险审查报告（结构化 JSON）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")
    contract = await contract_service.save_contract_review(
        db, contract_id, payload, user
    )
    return contract


# 常见扩展名兜底（content_type → 扩展名）
_MIME_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}


def _guess_ext(content_type: str | None) -> str:
    return _MIME_EXT.get(content_type or "", ".bin")
